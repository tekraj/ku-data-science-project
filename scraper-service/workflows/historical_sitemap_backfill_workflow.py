from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities.historical_sitemap_backfill_activities import (
        claim_next_pending_url_activity,
        discover_and_enqueue_urls_activity,
        fetch_and_classify_url_activity,
        get_sitemap_backfill_progress_activity,
        mark_url_failed_activity,
        reap_stale_claims_activity,
        upsert_backfill_progress_activity,
    )
    from activities.news_activities import write_articles_activity

_DEFAULT_RETRY_POLICY = RetryPolicy(maximum_attempts=3)

# Gap between consecutive fetches WITHIN a single batched tick, so a
# higher batch_size still makes one request at a time rather than bursting
# concurrently -- see HistoricalSitemapBackfillTickWorkflow.
_BATCH_ITEM_PAUSE_SECONDS = 3

# Portal metadata needed by the workflow itself (tier, for the write path).
# Kept here rather than imported from scraper.historical_sitemap_discovery
# to avoid pulling requests/bs4 into workflow sandbox code -- workflows
# should only import activities, config, and stdlib.
_PORTAL_TIERS: dict[str, str] = {
    "karobardaily": "finance",
    "myrepublica": "general",
    "himalayantimes": "general",
}


@workflow.defn
class HistoricalSitemapDiscoveryWorkflow:
    """One-shot (safe-to-repeat) discovery run for a single sitemap-based
    historical backfill portal. Triggered manually / occasionally (NOT on
    the per-tick backfill schedule) since it just enumerates sitemap URLs --
    cheap, not subject to the per-article rate limit, and re-running it is
    a no-op for URLs already queued (ON CONFLICT DO NOTHING)."""

    @workflow.run
    async def run(self, source: str, timeout: int = 20) -> dict[str, int]:
        return await workflow.execute_activity(
            discover_and_enqueue_urls_activity,
            args=[source, timeout],
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=_DEFAULT_RETRY_POLICY,
        )


@workflow.defn
class HistoricalSitemapBackfillTickWorkflow:
    """Processes up to `batch_size` queued URLs for `source` per execution,
    sequentially, each fetch separated by a short in-workflow pause (see
    workflow.sleep below) so a single tick still makes one request at a
    time against the target site rather than bursting -- it just does more
    total work per schedule firing than the original one-URL-per-tick
    design. Meant to be fired on a fixed cadence by its own independent
    Temporal Schedule (see register_schedules.py's _BACKFILL_TICK_INTERVAL)
    so each portal's tick rate is still enforced by the schedule itself,
    matching every other short-lived schedule-driven workflow already in
    this codebase. Each portal has its own schedule and its own work queue
    (historical_backfill_urls filtered by source), so all portals tick in
    parallel with each other even though each one individually paces
    itself.

    Increasing batch_size (rather than shortening the schedule interval)
    was the deliberate choice for raising throughput: it multiplies work
    done per tick without increasing how often the schedule itself fires,
    so Temporal's own scheduling/workflow-history overhead doesn't scale
    with it the way it would from a much shorter interval.

    A tick that runs out of pending URLs mid-batch (queue drains) just
    returns early with whatever it completed -- that's the expected steady
    state once a portal's queue is fully drained, and the schedule keeps
    ticking (harmlessly, one quick no-op claim check) until a future
    discovery run adds more URLs.
    """

    @workflow.run
    async def run(
        self, source: str, timeout: int = 20, batch_size: int = 1
    ) -> dict[str, Any]:
        tier = _PORTAL_TIERS.get(source)
        if tier is None:
            raise ValueError(f"Unknown sitemap backfill portal: {source}")

        processed = 0
        inserted_total = 0
        statuses: dict[str, int] = {}

        for i in range(batch_size):
            if i > 0:
                await workflow.sleep(timedelta(seconds=_BATCH_ITEM_PAUSE_SECONDS))

            claimed = await workflow.execute_activity(
                claim_next_pending_url_activity,
                args=[source],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

            if claimed is None:
                break

            try:
                outcome = await workflow.execute_activity(
                    fetch_and_classify_url_activity,
                    args=[claimed["id"], claimed["url"], source, tier, timeout],
                    start_to_close_timeout=timedelta(seconds=45),
                    retry_policy=_DEFAULT_RETRY_POLICY,
                )
            except Exception as e:  # noqa: BLE001 - one bad url must not fail the whole batch
                await workflow.execute_activity(
                    mark_url_failed_activity,
                    args=[claimed["id"], str(e)],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_DEFAULT_RETRY_POLICY,
                )
                processed += 1
                statuses["failed"] = statuses.get("failed", 0) + 1
                continue

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
            return {"status": "idle", "message": "no pending urls"}

        return {
            "status": "batch_complete",
            "processed": processed,
            "inserted": inserted_total,
            "by_status": statuses,
        }


@workflow.defn
class HistoricalSitemapBackfillStatusWorkflow:
    """Read-only status check for a sitemap backfill portal's queue depth."""

    @workflow.run
    async def run(self, source: str) -> dict[str, int]:
        return await workflow.execute_activity(
            get_sitemap_backfill_progress_activity,
            args=[source],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DEFAULT_RETRY_POLICY,
        )


@workflow.defn
class HistoricalBackfillReapWorkflow:
    """Periodically resets any historical_backfill_urls row stuck in
    "processing" (claimed by a ticker that died -- container restart,
    crash -- before finishing) back to "pending" so it gets retried.
    Covers all backfill sources (karobardaily, myrepublica, sharesansar) in
    one run since they share this table. Fired on its own schedule (see
    register_schedules.py) at a much coarser interval than the per-article
    ticks, since staleness is only worth checking every few minutes, not
    every tick."""

    @workflow.run
    async def run(self) -> int:
        return await workflow.execute_activity(
            reap_stale_claims_activity,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DEFAULT_RETRY_POLICY,
        )
