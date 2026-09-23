from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from temporalio import activity

from nepse_common.config import load_app_config
from nepse_common.db.session import session_scope
from nepse_common.models import HistoricalBackfillUrl, HistoricalCursorState
from nepse_common.schemas.scraped import ScrapedArticle

from scraper.historical_article_extractor import extract_article
from scraper.historical_cursor_scraper import SOURCE, TIER, fetch_cursor_page

from activities.historical_sitemap_backfill_activities import (
    BACKFILL_END_DATE,
    BACKFILL_START_DATE,
    MAX_FETCH_ATTEMPTS,
)


@activity.defn
async def get_cursor_state_activity() -> dict[str, Any]:
    """Returns {"cursor": str | None, "exhausted": bool}. cursor=None with
    exhausted=False means "start from the newest page" (first-ever run)."""
    config = load_app_config()

    with session_scope(config.database) as session:
        row = session.get(HistoricalCursorState, SOURCE)
        if row is None:
            return {"cursor": None, "exhausted": False}
        return {"cursor": row.cursor, "exhausted": row.exhausted}


@activity.defn
async def save_cursor_state_activity(next_cursor: str | None) -> None:
    """Persists the cursor to resume from on the next tick. next_cursor=None
    means the chain is exhausted (no more older pages)."""
    config = load_app_config()
    exhausted = next_cursor is None

    with session_scope(config.database) as session:
        stmt = (
            pg_insert(HistoricalCursorState)
            .values(
                source=SOURCE,
                cursor=next_cursor,
                exhausted=exhausted,
                updated_at=datetime.utcnow(),
            )
            .on_conflict_do_update(
                index_elements=["source"],
                set_={"cursor": next_cursor, "exhausted": exhausted, "updated_at": datetime.utcnow()},
            )
        )
        session.execute(stmt)


@activity.defn
async def fetch_cursor_listing_page_activity(cursor: str | None, timeout: int) -> dict[str, Any]:
    """Fetches one sharesansar /category/latest listing page and enqueues
    every article on it (with its listing-page date already known -- see
    historical_cursor_scraper module docstring for why the article page's
    own date cannot be trusted). Returns the next cursor to resume from.

    fetch_cursor_page is synchronous (blocking requests.get()) -- run it
    via asyncio.to_thread so it can't freeze the shared asyncio event loop
    (see the matching note on scrape_historical_day_activity)."""
    page = await asyncio.to_thread(fetch_cursor_page, cursor, timeout=timeout)

    config = load_app_config()
    records = [
        {
            "source": SOURCE,
            "url": a.url,
            "status": "pending",
            "published_at": a.published_at,
        }
        for a in page.articles
    ]

    newly_queued = 0
    if records:
        with session_scope(config.database) as session:
            stmt = (
                pg_insert(HistoricalBackfillUrl)
                .values(records)
                .on_conflict_do_nothing(index_elements=["source", "url"])
                .returning(HistoricalBackfillUrl.id)
            )
            result = session.execute(stmt)
            newly_queued = len(result.fetchall())

    activity.logger.info(
        f"[HistoricalBackfill] sharesansar: listing page yielded {len(page.articles)} "
        f"articles, {newly_queued} newly queued, next_cursor={'set' if page.next_cursor else 'none'}."
    )

    return {
        "articles_on_page": len(page.articles),
        "newly_queued": newly_queued,
        "next_cursor": page.next_cursor,
    }


@activity.defn
async def claim_next_pending_sharesansar_url_activity() -> dict[str, Any] | None:
    """Same claim semantics as claim_next_pending_url_activity, scoped to
    the real sharesansar source (not the cursor-state sentinel row)."""
    config = load_app_config()

    with session_scope(config.database) as session:
        stmt = (
            select(HistoricalBackfillUrl)
            .where(
                HistoricalBackfillUrl.source == SOURCE,
                HistoricalBackfillUrl.status == "pending",
            )
            .order_by(HistoricalBackfillUrl.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = session.execute(stmt).scalars().first()
        if row is None:
            return None

        row.status = "processing"
        row.claimed_at = datetime.utcnow()
        # Serialize to an ISO string here (rather than returning the raw
        # datetime) so the activity's return value crosses the Temporal
        # data-converter boundary as an unambiguous JSON-safe type -- the
        # workflow side receives whatever the converter round-trips a bare
        # datetime into, which is not guaranteed to still be a datetime
        # object (confirmed directly: it comes back as a plain str).
        published_at_iso = row.published_at.isoformat() if row.published_at else None
        return {"id": row.id, "url": row.url, "published_at_iso": published_at_iso}


@activity.defn
async def fetch_and_classify_sharesansar_url_activity(
    url_id: int, url: str, published_at_iso: str | None, timeout: int
) -> dict[str, Any]:
    """Like fetch_and_classify_url_activity, but the published_at is
    already known from the listing page (sharesansar's own article pages
    have no trustworthy date, see module docstrings) -- this activity only
    fetches the article page for title/body/category.

    extract_article is synchronous (blocking requests.get()) -- run it via
    asyncio.to_thread so it can't freeze the shared asyncio event loop
    (see the matching note on scrape_historical_day_activity)."""
    config = load_app_config()

    title, body, category, _article_page_published_at = await asyncio.to_thread(
        extract_article, url, timeout=timeout
    )
    published_at = datetime.fromisoformat(published_at_iso) if published_at_iso else None

    in_range = (
        published_at is not None
        and BACKFILL_START_DATE <= published_at.date() <= BACKFILL_END_DATE
    )

    with session_scope(config.database) as session:
        row = session.get(HistoricalBackfillUrl, url_id)
        if row is None:
            return {"status": "missing_row", "article": None}

        row.processed_at = datetime.utcnow()

        if not title:
            # See fetch_and_classify_url_activity's matching comment:
            # extract_article() swallows its own fetch/parse exceptions, so
            # transient failures land here rather than as a raised
            # exception -- retry up to MAX_FETCH_ATTEMPTS before giving up.
            row.attempt_count = (row.attempt_count or 0) + 1
            row.error_text = "empty title / fetch failed"
            row.status = "pending" if row.attempt_count < MAX_FETCH_ATTEMPTS else "failed"
            return {"status": row.status, "article": None}

        if not in_range:
            row.status = "out_of_range"
            return {"status": "out_of_range", "article": None}

        row.status = "inserted"

    article = ScrapedArticle.model_validate(
        {
            "source": SOURCE,
            "portal_tier": TIER,
            "url": url,
            "title": title,
            "body": body,
            "category": category,
            "published_at": published_at,
        }
    )
    return {"status": "inserted", "article": article.model_dump(mode="json")}
