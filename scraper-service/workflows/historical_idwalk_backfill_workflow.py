from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities.historical_idwalk_backfill_activities import (
        fetch_and_classify_idwalk_id_activity,
        get_idwalk_progress_activity,
        get_next_idwalk_id_activity,
    )
    from activities.historical_sitemap_backfill_activities import (
        upsert_backfill_progress_activity,
    )
    from activities.news_activities import write_articles_activity

_DEFAULT_RETRY_POLICY = RetryPolicy(maximum_attempts=3)

# Gap between consecutive fetches within a single batched tick -- same
# pattern/rationale as HistoricalSitemapBackfillTickWorkflow's constant.
_BATCH_ITEM_PAUSE_SECONDS = 3


@workflow.defn
class HistoricalIdWalkBackfillTickWorkflow:
    """Processes up to `batch_size` sequential numeric IDs for `source`
    per execution (setopati, merolagani, onlinekhabar -- see
    scraper/historical_idwalk_discovery.py for why these portals need
    ID-guessing instead of a sitemap/cursor). Each ID is fetched, checked
    for existence, and classified by published_at against the fixed
    backfill window, separately paced (see _BATCH_ITEM_PAUSE_SECONDS) so a
    bigger batch still makes one request at a time. Fired on a fixed
    cadence by its own Temporal Schedule (see register_schedules.py), same
    throughput-via-batching design as the sitemap/cursor backfill tickers.

    A missing ID (not_found) is a normal, expected, high-frequency outcome
    for these portals (confirmed sparse ID spaces / interleaved
    non-article post types) -- NOT a failure, and NOT retried; the cursor
    just advances past it. There is no separate discovery phase: unlike
    the sitemap backfill, fetching an ID IS how existence is discovered,
    so this workflow's queue is just "the next ID to try," tracked by
    get_next_idwalk_id_activity."""

    @workflow.run
    async def run(self, source: str, timeout: int = 20, batch_size: int = 1) -> dict[str, Any]:
        processed = 0
        inserted_total = 0
        statuses: dict[str, int] = {}

        for i in range(batch_size):
            if i > 0:
                await workflow.sleep(timedelta(seconds=_BATCH_ITEM_PAUSE_SECONDS))

            next_id_result = await workflow.execute_activity(
                get_next_idwalk_id_activity,
                args=[source],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

            if next_id_result is None:
                break  # this source's calibrated bracket is fully walked

            outcome = await workflow.execute_activity(
                fetch_and_classify_idwalk_id_activity,
                args=[source, next_id_result["id"], timeout],
                start_to_close_timeout=timedelta(seconds=45),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

            processed += 1
            statuses[outcome["status"]] = statuses.get(outcome["status"], 0) + 1

            if outcome["status"] == "inserted" and outcome["article"] is not None:
                inserted = await workflow.execute_activity(
                    write_articles_activity,
                    args=[[outcome["article"]]],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_DEFAULT_RETRY_POLICY,
                )
                inserted_total += inserted

                target_date_iso = outcome["article"]["published_at"][:10]
                await workflow.execute_activity(
                    upsert_backfill_progress_activity,
                    args=[source, target_date_iso, 1, inserted],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_DEFAULT_RETRY_POLICY,
                )

        if processed == 0:
            return {"status": "idle", "message": "id range exhausted"}

        return {
            "status": "batch_complete",
            "processed": processed,
            "inserted": inserted_total,
            "by_status": statuses,
        }


@workflow.defn
class HistoricalIdWalkStatusWorkflow:
    """Read-only status check: current cursor position / exhaustion for
    each id-walk source."""

    @workflow.run
    async def run(self) -> dict[str, dict[str, Any]]:
        return await workflow.execute_activity(
            get_idwalk_progress_activity,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DEFAULT_RETRY_POLICY,
        )
