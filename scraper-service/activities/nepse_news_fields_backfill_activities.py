from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from temporalio import activity

from nepse_common.config import load_app_config
from nepse_common.db.session import session_scope
from nepse_common.models import NewsArticle

from scraper.nepse_news_fields_backfill import SUPPORTED_SOURCES, backfill_fields

# A row that keeps coming back no_new_data/fetch_failed (dead link,
# permanent error, or content that's genuinely unfixable -- e.g. a
# nepalipaisa article that's only a video embed with no text body) would
# otherwise be reclaimed forever: the claim query orders by id ASC, so the
# single lowest-id stuck row gets picked first on every tick, permanently
# blocking every other row behind it in the queue. CONFIRMED directly in
# production: one such row blocked ~10,900 others from ever being
# attempted. Once a row's fields_backfill_attempts reaches this, it's
# excluded from future claims.
MAX_BACKFILL_ATTEMPTS = 3


def _needs_backfill_filter():
    return or_(
        NewsArticle.published_at.is_(None),
        NewsArticle.body.is_(None),
        NewsArticle.body == "",
    )


@activity.defn
async def claim_next_fields_backfill_row_activity() -> dict[str, Any] | None:
    """Atomically claims one nepse_news row missing published_at and/or
    body, from a source this worker knows how to fix (SUPPORTED_SOURCES),
    returning {id, source, url, needs_published_at, needs_body} or None if
    there's nothing left to claim. Nothing to update-and-mark-processing
    here the way historical_backfill_urls works -- this activity just
    reads and returns candidate info; the actual UPDATE happens in
    apply_fields_backfill_activity once the fetch succeeds, so a claim
    that never gets processed (crash mid-tick) simply remains eligible to
    be claimed again next time -- no separate "processing" state or reap
    step needed since re-claiming a not-yet-fixed row is always safe
    (idempotent: fetching + writing the same missing fields again is a
    no-op difference from writing them once)."""
    config = load_app_config()

    with session_scope(config.database) as session:
        stmt = (
            select(NewsArticle)
            .where(
                NewsArticle.source.in_(SUPPORTED_SOURCES),
                NewsArticle.fields_backfill_attempts < MAX_BACKFILL_ATTEMPTS,
                _needs_backfill_filter(),
            )
            .order_by(NewsArticle.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = session.execute(stmt).scalars().first()
        if row is None:
            return None

        return {
            "id": row.id,
            "source": row.source,
            "url": row.url,
            "needs_published_at": row.published_at is None,
            "needs_body": not row.body,
        }


@activity.defn
async def apply_fields_backfill_activity(
    row_id: int, source: str, url: str, timeout: int
) -> dict[str, Any]:
    """Fetches `url` via the source's backfill_fields() strategy and
    UPDATEs only the fields that were actually missing AND actually came
    back non-empty -- never overwrites an existing published_at/body with
    None, and never touches fields that weren't missing in the first
    place.

    Any outcome other than a real field update increments
    fields_backfill_attempts, so a row that's genuinely unfixable (dead
    link, or content backfill_fields() can't extract text from -- e.g. a
    nepalipaisa article that's only a video embed) stops being claimed
    after MAX_BACKFILL_ATTEMPTS instead of permanently blocking every
    other row behind it in the claim queue (confirmed this happened in
    production before this counter existed).

    backfill_fields() is synchronous (blocking requests.get()) -- run it
    via asyncio.to_thread so it can't freeze the shared asyncio event loop
    (see the matching note on scrape_historical_day_activity)."""
    result = await asyncio.to_thread(backfill_fields, source, url, timeout=timeout)

    config = load_app_config()

    if result.fetch_failed:
        with session_scope(config.database) as session:
            row = session.get(NewsArticle, row_id)
            if row is not None:
                row.fields_backfill_attempts = (row.fields_backfill_attempts or 0) + 1
        return {"status": "fetch_failed"}

    updates: dict[str, Any] = {}

    with session_scope(config.database) as session:
        row = session.get(NewsArticle, row_id)
        if row is None:
            return {"status": "missing_row"}

        if row.published_at is None and result.published_at is not None:
            row.published_at = result.published_at
            updates["published_at"] = result.published_at.isoformat()

        if not row.body and result.body:
            row.body = result.body
            updates["body"] = True

        if not updates:
            row.fields_backfill_attempts = (row.fields_backfill_attempts or 0) + 1

    if not updates:
        return {"status": "no_new_data"}

    return {"status": "updated", "updates": updates}


@activity.defn
async def get_fields_backfill_progress_activity() -> dict[str, dict[str, int]]:
    """Returns, per source, how many rows still need published_at/body:
    "claimable" (still eligible to be picked up by a future tick) and
    "given_up" (hit MAX_BACKFILL_ATTEMPTS -- permanently unfixable content,
    e.g. a video-only article, or a persistently dead link). Keeping these
    separate avoids the progress report looking stuck forever on rows this
    worker has already concluded it can't fix."""
    config = load_app_config()

    with session_scope(config.database) as session:
        claimable_stmt = select(NewsArticle.source, NewsArticle.id).where(
            NewsArticle.source.in_(SUPPORTED_SOURCES),
            NewsArticle.fields_backfill_attempts < MAX_BACKFILL_ATTEMPTS,
            _needs_backfill_filter(),
        )
        given_up_stmt = select(NewsArticle.source, NewsArticle.id).where(
            NewsArticle.source.in_(SUPPORTED_SOURCES),
            NewsArticle.fields_backfill_attempts >= MAX_BACKFILL_ATTEMPTS,
            _needs_backfill_filter(),
        )
        claimable_rows = session.execute(claimable_stmt).all()
        given_up_rows = session.execute(given_up_stmt).all()

    counts: dict[str, dict[str, int]] = {}
    for source, _id in claimable_rows:
        counts.setdefault(source, {"claimable": 0, "given_up": 0})["claimable"] += 1
    for source, _id in given_up_rows:
        counts.setdefault(source, {"claimable": 0, "given_up": 0})["given_up"] += 1
    return counts
