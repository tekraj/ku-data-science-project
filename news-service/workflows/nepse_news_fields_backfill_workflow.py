from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities.nepse_news_fields_backfill_activities import (
        apply_fields_backfill_activity,
        claim_next_fields_backfill_row_activity,
        get_fields_backfill_progress_activity,
    )

_DEFAULT_RETRY_POLICY = RetryPolicy(maximum_attempts=3)

# Gap between consecutive fetches within a single batched tick -- same
# pattern/rationale as HistoricalSitemapBackfillTickWorkflow's constant.
_BATCH_ITEM_PAUSE_SECONDS = 3


@workflow.defn
class NepseNewsFieldsBackfillTickWorkflow:
    """One-time cleanup pass over existing nepse_news rows that are
    missing published_at and/or body (root cause: several live scrapers'
    CSS selectors had gone stale against current site markup, and one
    source, nepalipaisa, never had body in its server-rendered HTML at
    all -- see scraper/nepse_news_fields_backfill.py for the full
    per-source research notes). Processes up to `batch_size` rows per
    execution, each fetch separately paced (see _BATCH_ITEM_PAUSE_SECONDS)
    so a bigger batch still makes one request at a time rather than
    bursting. Fired on a fixed cadence by its own Temporal Schedule (see
    register_schedules.py), same throughput-via-batching design as the
    historical sitemap/cursor backfill tickers.

    Unlike that backfill, there is no separate work-queue table here --
    each tick queries nepse_news directly for rows still missing a field,
    among sources this worker has a fix for (see
    scraper.nepse_news_fields_backfill.SUPPORTED_SOURCES). A row is simply
    left alone (still eligible, re-claimed next tick) if its fetch fails,
    since re-fetching an already-fixed field is a harmless no-op -- there
    is no terminal "gave up" state, this queue naturally drains as rows
    get fixed and 404s/dead links stay a small, static residual.
    """

    @workflow.run
    async def run(self, timeout: int = 20, batch_size: int = 1) -> dict[str, Any]:
        processed = 0
        updated = 0
        statuses: dict[str, int] = {}

        for i in range(batch_size):
            if i > 0:
                await workflow.sleep(timedelta(seconds=_BATCH_ITEM_PAUSE_SECONDS))

            claimed = await workflow.execute_activity(
                claim_next_fields_backfill_row_activity,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

            if claimed is None:
                break

            outcome = await workflow.execute_activity(
                apply_fields_backfill_activity,
                args=[claimed["id"], claimed["source"], claimed["url"], timeout],
                start_to_close_timeout=timedelta(seconds=45),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

            processed += 1
            statuses[outcome["status"]] = statuses.get(outcome["status"], 0) + 1
            if outcome["status"] == "updated":
                updated += 1

        if processed == 0:
            return {"status": "idle", "message": "no rows need backfill"}

        return {
            "status": "batch_complete",
            "processed": processed,
            "updated": updated,
            "by_status": statuses,
        }


@workflow.defn
class NepseNewsFieldsBackfillStatusWorkflow:
    """Read-only status check: how many nepse_news rows still need
    published_at/body backfill, broken down by source, split into
    "claimable" (still eligible) and "given_up" (hit the attempt limit --
    see MAX_BACKFILL_ATTEMPTS)."""

    @workflow.run
    async def run(self) -> dict[str, dict[str, int]]:
        return await workflow.execute_activity(
            get_fields_backfill_progress_activity,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DEFAULT_RETRY_POLICY,
        )
