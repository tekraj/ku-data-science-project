from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from temporalio import activity

from nepse_common.config import load_app_config
from nepse_common.db.session import session_scope
from nepse_common.models import HistoricalBackfillProgress, HistoricalBackfillUrl
from nepse_common.schemas.scraped import ScrapedArticle

from scraper.historical_article_extractor import extract_article
from scraper.historical_sitemap_discovery import PORTALS_BY_SOURCE, discover_portal_urls

# Fixed backfill window, per the user's original ask: 2021-01-01 through
# the last date the live pipeline had *no* coverage at all, 2026-06-29
# (live 30-min scraping and the CSV-backed nepse_index import both start
# on/after that date). Anything discovered outside this range is marked
# "out_of_range" and never written to nepse_news -- it's either too old to
# matter or already covered by the live/daily-historical pipelines. Left
# as a fixed historical constant for karobardaily/myrepublica/sharesansar,
# which this window was originally calibrated for.
BACKFILL_START_DATE = date(2021, 1, 1)
BACKFILL_END_DATE = date(2026, 6, 29)

# Wider window for sources whose backfill is specifically reaching back to
# 2014 (himalayantimes's sitemap goes back that far; the id-walk sources in
# historical_idwalk_backfill_activities.py too), per the follow-up ask to
# close the gap all the way from 2014 up to whatever each source's live
# scraping already covers. Unlike BACKFILL_END_DATE above, the upper bound
# here is intentionally NOT a fixed date -- it's "today", computed fresh
# each call -- since the target is "keep pace with live coverage" rather
# than a specific historical cutoff; a hardcoded date would go stale again
# the same way BACKFILL_END_DATE did.
EARLY_BACKFILL_SOURCES: frozenset[str] = frozenset({"himalayantimes"})
EARLY_BACKFILL_START_DATE = date(2014, 1, 1)


def early_backfill_end_date() -> date:
    return date.today()

# A URL that keeps failing (dead link, permanent 4xx/5xx, unparseable page)
# would otherwise cycle pending -> processing -> failed -> pending forever
# at ~1 attempt/minute. After this many attempts it's left in a terminal
# "failed" status instead of being reset to "pending" again.
MAX_FETCH_ATTEMPTS = 5

# A row claimed (status="processing") by a ticker that then dies before
# finishing (container restart/redeploy, crash) would otherwise stay stuck
# in "processing" forever -- observed directly in production across a
# handful of redeploys. Any row still "processing" after this long is
# considered abandoned and reset to "pending" by reap_stale_claims_activity.
# Generously larger than any single fetch's own activity timeout (45s in
# the tick workflows) so this never fights a merely-slow-but-alive fetch.
STALE_CLAIM_TIMEOUT = timedelta(minutes=10)


@activity.defn
async def discover_and_enqueue_urls_activity(source: str, timeout: int) -> dict[str, int]:
    """One-shot (well, safe-to-repeat) bulk discovery step for a sitemap
    portal: walks its sitemap(s) and inserts every not-yet-seen candidate
    URL into historical_backfill_urls as "pending". Cheap relative to the
    per-article fetch -- sitemap files are small XML, not full article
    pages -- so this is NOT rate limited the way per-article ticks are.

    Safe to re-run: a new URL is inserted as "pending"; an already-known
    URL has its discovery_rank UPDATED (in case a later run has better rank
    info -- e.g. this activity shipped before discovery_rank existed, so
    the first re-run after that needs to backfill rank onto the existing
    backlog) but ONLY while it's still "pending" -- a row already
    processing/inserted/out_of_range/failed is left untouched, both
    because re-ranking a finished row is pointless and because touching a
    "processing" row here would race with whatever ticker currently holds
    it.

    discover_portal_urls is synchronous (blocking requests.get() across
    hundreds of sub-sitemap fetches) -- run it via asyncio.to_thread so it
    can't freeze the shared asyncio event loop (see the matching note on
    scrape_historical_day_activity, where this exact pattern was confirmed
    to cause a multi-minute worker-wide stall in production).
    """
    ranked_urls = await asyncio.to_thread(discover_portal_urls, source, timeout=timeout)
    if not ranked_urls:
        return {"discovered": 0, "newly_queued": 0}

    config = load_app_config()
    records = [
        {"source": source, "url": r.url, "status": "pending", "discovery_rank": r.rank}
        for r in ranked_urls
    ]

    with session_scope(config.database) as session:
        stmt = (
            pg_insert(HistoricalBackfillUrl)
            .values(records)
            .on_conflict_do_update(
                index_elements=["source", "url"],
                set_={"discovery_rank": pg_insert(HistoricalBackfillUrl).excluded.discovery_rank},
                where=(HistoricalBackfillUrl.status == "pending"),
            )
            .returning(HistoricalBackfillUrl.id)
        )
        result = session.execute(stmt)
        # With ON CONFLICT DO UPDATE, RETURNING yields a row for both new
        # inserts and rank-updated existing rows, so this now means
        # "queued or re-ranked", not strictly "newly queued".
        affected = len(result.fetchall())

    activity.logger.info(
        f"[HistoricalBackfill] {source}: discovered {len(ranked_urls)} urls, {affected} queued/re-ranked."
    )
    return {"discovered": len(ranked_urls), "newly_queued": affected}


@activity.defn
async def claim_next_pending_url_activity(source: str) -> dict[str, Any] | None:
    """Atomically claims one pending URL for `source` (sets its status to
    "processing" so a concurrent/overlapping run never double-claims it),
    returning {id, url} or None if the queue is empty. FOR UPDATE SKIP
    LOCKED makes this safe even if more than one worker process is ever
    running against the same queue.

    Orders by discovery_rank DESC first -- higher rank means the URL was
    discovered from a sub-sitemap chunk believed to hold older content
    (see RankedUrl / historical_sitemap_discovery.py), so this
    preferentially works through probably-older URLs first rather than
    strict discovery order. Falls back to id ASC as a tiebreaker (also the
    only ordering in effect for portals where every row has rank=0, e.g.
    myrepublica, which has no reliable per-sub-sitemap age signal)."""
    config = load_app_config()

    with session_scope(config.database) as session:
        stmt = (
            select(HistoricalBackfillUrl)
            .where(
                HistoricalBackfillUrl.source == source,
                HistoricalBackfillUrl.status == "pending",
            )
            .order_by(HistoricalBackfillUrl.discovery_rank.desc(), HistoricalBackfillUrl.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = session.execute(stmt).scalars().first()
        if row is None:
            return None

        row.status = "processing"
        row.claimed_at = datetime.utcnow()
        row_id = row.id
        row_url = row.url

    return {"id": row_id, "url": row_url}


@activity.defn
async def fetch_and_classify_url_activity(
    url_id: int, url: str, source: str, tier: str, timeout: int
) -> dict[str, Any]:
    """Fetches one article, classifies it by published_at against the
    fixed backfill window, and updates its historical_backfill_urls row.
    Returns a dict describing the outcome; does NOT write to nepse_news
    itself (kept separate so the caller can batch/validate through the
    same ScrapedArticle path the live pipeline uses).

    extract_article is synchronous (blocking requests.get()) -- run it via
    asyncio.to_thread so it can't freeze the shared asyncio event loop
    (see the matching note on scrape_historical_day_activity)."""
    config = load_app_config()

    title, body, category, published_at = await asyncio.to_thread(
        extract_article, url, timeout=timeout
    )

    if source in EARLY_BACKFILL_SOURCES:
        window_start = EARLY_BACKFILL_START_DATE
        window_end = early_backfill_end_date()
    else:
        window_start = BACKFILL_START_DATE
        window_end = BACKFILL_END_DATE
    in_range = published_at is not None and window_start <= published_at.date() <= window_end

    with session_scope(config.database) as session:
        row = session.get(HistoricalBackfillUrl, url_id)
        if row is None:
            return {"status": "missing_row", "article": None}

        row.processed_at = datetime.utcnow()
        row.published_at = published_at

        if not title:
            # extract_article() swallows its own fetch/parse exceptions and
            # returns ("", "", "", None) rather than raising (see
            # historical_article_extractor.extract_article), so a transient
            # failure (timeout, momentary 5xx) lands here, not in the
            # workflow's except-Exception branch. Retry like any other
            # failure, up to MAX_FETCH_ATTEMPTS, before giving up for good.
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
            "source": source,
            "portal_tier": tier,
            "url": url,
            "title": title,
            "body": body,
            "category": category,
            "published_at": published_at,
        }
    )
    return {"status": "inserted", "article": article.model_dump(mode="json")}


@activity.defn
async def mark_url_failed_activity(url_id: int, error_text: str) -> None:
    """Records a fetch failure, used when fetch_and_classify_url_activity
    itself raises rather than returning a clean failure outcome. Resets
    the URL to "pending" so a future tick retries it, UNLESS this was
    already its MAX_FETCH_ATTEMPTS'th failure, in which case it's left in
    a terminal "failed" status so a permanently broken URL doesn't retry
    forever."""
    config = load_app_config()

    with session_scope(config.database) as session:
        row = session.get(HistoricalBackfillUrl, url_id)
        if row is None:
            return

        row.attempt_count = (row.attempt_count or 0) + 1
        row.error_text = error_text[:2000]
        row.status = "pending" if row.attempt_count < MAX_FETCH_ATTEMPTS else "failed"


@activity.defn
async def reap_stale_claims_activity() -> int:
    """Resets any historical_backfill_urls row stuck in "processing" for
    longer than STALE_CLAIM_TIMEOUT back to "pending" so it gets retried.
    Covers all sources in one pass (karobardaily, myrepublica, sharesansar
    all share this table) since this is cheap and there's no reason to
    scope it per-portal. Returns the number of rows reaped."""
    config = load_app_config()
    cutoff = datetime.utcnow() - STALE_CLAIM_TIMEOUT

    with session_scope(config.database) as session:
        stmt = select(HistoricalBackfillUrl).where(
            HistoricalBackfillUrl.status == "processing",
            HistoricalBackfillUrl.claimed_at < cutoff,
        )
        stale_rows = session.execute(stmt).scalars().all()

        for row in stale_rows:
            row.status = "pending"

    if stale_rows:
        activity.logger.info(f"[HistoricalBackfill] Reaped {len(stale_rows)} stale processing claim(s).")

    return len(stale_rows)


@activity.defn
async def get_sitemap_backfill_progress_activity(source: str) -> dict[str, int]:
    """Returns queue-depth counts for `source`, used for status/monitoring
    (e.g. is this portal's backfill effectively drained)."""
    config = load_app_config()

    with session_scope(config.database) as session:
        counts: dict[str, int] = {}
        for status in ("pending", "processing", "inserted", "out_of_range", "failed"):
            stmt = select(HistoricalBackfillUrl.id).where(
                HistoricalBackfillUrl.source == source,
                HistoricalBackfillUrl.status == status,
            )
            counts[status] = len(session.execute(stmt).fetchall())

    return counts


@activity.defn
async def upsert_backfill_progress_activity(
    source: str, target_date_iso: str, found_delta: int, inserted_delta: int
) -> None:
    """Increments the (source, target_date) row in
    historical_backfill_progress. Used for the coarse per-day "already
    done" summary the user asked for; the real work-tracking dedup lives in
    historical_backfill_urls's own (source, url) uniqueness."""
    config = load_app_config()
    target_date = datetime.strptime(target_date_iso, "%Y-%m-%d").date()

    with session_scope(config.database) as session:
        stmt = select(HistoricalBackfillProgress).where(
            HistoricalBackfillProgress.source == source,
            HistoricalBackfillProgress.target_date == target_date,
        )
        row = session.execute(stmt).scalars().first()

        if row is None:
            row = HistoricalBackfillProgress(
                source=source,
                target_date=target_date,
                articles_found=found_delta,
                articles_inserted=inserted_delta,
            )
            session.add(row)
        else:
            row.articles_found = (row.articles_found or 0) + found_delta
            row.articles_inserted = (row.articles_inserted or 0) + inserted_delta


SITEMAP_BACKFILL_SOURCES: tuple[str, ...] = tuple(PORTALS_BY_SOURCE.keys())
