from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from temporalio import activity

from nepse_common.config import load_app_config
from nepse_common.db.session import session_scope
from nepse_common.models import HistoricalIdWalkCursor
from nepse_common.schemas.scraped import ScrapedArticle

from scraper.historical_idwalk_discovery import PORTALS_BY_SOURCE

from activities.historical_sitemap_backfill_activities import (
    BACKFILL_END_DATE,
    EARLY_BACKFILL_START_DATE,
)

ID_WALK_SOURCES: tuple[str, ...] = tuple(PORTALS_BY_SOURCE.keys())


@activity.defn
async def get_next_idwalk_id_activity(source: str) -> dict[str, Any] | None:
    """Returns {"id": <next numeric id to try>} for `source`, or None if
    the portal's calibrated bracket is already fully walked (exhausted).
    Initializes the cursor at the portal's id_range_start on first call.

    Unlike historical_backfill_urls's claim/queue model, there is no
    separate discovery phase here -- fetching an ID IS the only way to
    learn whether it's a real article, so this simply hands out "the next
    ID to try" without knowing in advance if it exists. The actual
    existence check + classification happens in
    fetch_and_classify_idwalk_id_activity."""
    spec = PORTALS_BY_SOURCE.get(source)
    if spec is None:
        raise ValueError(f"Unknown id-walk portal: {source}")

    config = load_app_config()

    with session_scope(config.database) as session:
        row = session.get(HistoricalIdWalkCursor, source)
        if row is None:
            row = HistoricalIdWalkCursor(source=source, next_id=spec.id_range_start, exhausted=False)
            session.add(row)
            session.flush()

        if row.exhausted:
            return None

        current_id = row.next_id
        next_id = current_id + 1
        if next_id > spec.id_range_end:
            row.next_id = next_id
            row.exhausted = True
        else:
            row.next_id = next_id

    return {"id": current_id}


@activity.defn
async def fetch_and_classify_idwalk_id_activity(source: str, article_id: int, timeout: int) -> dict[str, Any]:
    """Fetches one numeric ID for `source`, classifies it by published_at
    against the fixed backfill window, and returns an outcome. Does NOT
    write to nepse_news itself (same separation as the sitemap/cursor
    backfills, so the caller can batch/validate through the same
    ScrapedArticle path the live pipeline uses).

    A non-existent ID (spec.fetch's exists=False -- e.g. merolagani's
    sparse ID space, or a genuine 404) is a normal, expected outcome here,
    NOT a failure -- these portals' ID spaces have confirmed gaps
    (deleted/moved articles, attachment/custom-post-type IDs interleaved
    with real articles), so a missing ID must never be treated as
    end-of-data or as something to retry.

    spec.fetch is synchronous (blocking requests.get()) -- run it via
    asyncio.to_thread so it can't freeze the shared asyncio event loop
    (see the matching note on scrape_historical_day_activity)."""
    spec = PORTALS_BY_SOURCE.get(source)
    if spec is None:
        raise ValueError(f"Unknown id-walk portal: {source}")

    result = await asyncio.to_thread(spec.fetch, article_id, timeout)

    if not result.exists:
        return {"status": "not_found", "article": None}

    in_range = (
        result.published_at is not None
        and EARLY_BACKFILL_START_DATE <= result.published_at.date() <= BACKFILL_END_DATE
    )
    if not in_range:
        return {"status": "out_of_range", "article": None}

    article = ScrapedArticle.model_validate(
        {
            "source": source,
            "portal_tier": spec.tier,
            "url": result.url,
            "title": result.title,
            "body": result.body,
            "category": result.category,
            "published_at": result.published_at,
        }
    )
    return {"status": "inserted", "article": article.model_dump(mode="json")}


@activity.defn
async def get_idwalk_progress_activity() -> dict[str, dict[str, Any]]:
    """Returns, per id-walk source, the current cursor position and
    whether it's exhausted -- for monitoring."""
    config = load_app_config()

    with session_scope(config.database) as session:
        progress: dict[str, dict[str, Any]] = {}
        for source in ID_WALK_SOURCES:
            row = session.get(HistoricalIdWalkCursor, source)
            spec = PORTALS_BY_SOURCE[source]
            if row is None:
                progress[source] = {
                    "next_id": spec.id_range_start,
                    "range_end": spec.id_range_end,
                    "exhausted": False,
                }
            else:
                progress[source] = {
                    "next_id": row.next_id,
                    "range_end": spec.id_range_end,
                    "exhausted": row.exhausted,
                }
    return progress
