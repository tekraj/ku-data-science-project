from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities.historical_cursor_backfill_activities import (
        claim_next_pending_sharesansar_url_activity,
        fetch_and_classify_sharesansar_url_activity,
        fetch_cursor_listing_page_activity,
        get_cursor_state_activity,
        save_cursor_state_activity,
    )
    from activities.historical_sitemap_backfill_activities import (
        upsert_backfill_progress_activity,
    )
    from activities.news_activities import write_articles_activity

_DEFAULT_RETRY_POLICY = RetryPolicy(maximum_attempts=3)
_SOURCE = "sharesansar"

# Gap between consecutive actions WITHIN a single batched tick, so a higher
# batch_size still makes one request at a time rather than bursting -- see
# HistoricalSitemapBackfillTickWorkflow's matching constant/rationale.
_BATCH_ITEM_PAUSE_SECONDS = 3


@workflow.defn
class HistoricalCursorBackfillTickWorkflow:
    """Fired on a fixed cadence by its own independent Temporal Schedule
    (see register_schedules.py's _BACKFILL_TICK_INTERVAL), for
    sharesansar.com's cursor-paginated backfill -- this schedule runs in
    parallel with the sitemap portals' schedules, each independently
    paced. Unlike the sitemap portals, discovery here can't be
    front-loaded (the cursor only reveals the next page after fetching the
    current one), so each of up to `batch_size` actions per tick does ONE
    of:

      1. If there's a queued (but not yet fetched) article from an earlier
         listing-page fetch, process it (fetch its body, classify by the
         date already known from the listing page, write if in range).
      2. Otherwise, if the cursor chain isn't exhausted, fetch the next
         listing page (which both queues a fresh batch of dated articles
         and advances the cursor for the following action/tick).
      3. Otherwise (queue empty AND cursor exhausted): stop early --
         steady state once this source is fully backfilled.

    batch_size lets one tick do several such actions in sequence (each
    still a single, separately-paced request) rather than raising
    throughput by shortening the schedule interval itself.
    """

    @workflow.run
    async def run(self, timeout: int = 20, batch_size: int = 1) -> dict[str, Any]:
        actions = 0
        inserted_total = 0
        listing_pages_fetched = 0
        articles_processed = 0
        exhausted = False

        for i in range(batch_size):
            if i > 0:
                await workflow.sleep(timedelta(seconds=_BATCH_ITEM_PAUSE_SECONDS))

            claimed = await workflow.execute_activity(
                claim_next_pending_sharesansar_url_activity,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

            if claimed is not None:
                result = await self._process_claimed_article(claimed, timeout)
                inserted_total += result["inserted"]
                articles_processed += 1
                actions += 1
                continue

            state = await workflow.execute_activity(
                get_cursor_state_activity,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

            if state["exhausted"]:
                exhausted = True
                break

            fetch_result = await workflow.execute_activity(
                fetch_cursor_listing_page_activity,
                args=[state["cursor"], timeout],
                start_to_close_timeout=timedelta(seconds=45),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

            await workflow.execute_activity(
                save_cursor_state_activity,
                args=[fetch_result["next_cursor"]],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

            listing_pages_fetched += 1
            actions += 1

        if actions == 0:
            return {"status": "idle", "message": "queue empty and cursor exhausted"}

        return {
            "status": "batch_complete",
            "actions": actions,
            "articles_processed": articles_processed,
            "inserted": inserted_total,
            "listing_pages_fetched": listing_pages_fetched,
            "cursor_exhausted": exhausted,
        }

    async def _process_claimed_article(
        self, claimed: dict[str, Any], timeout: int
    ) -> dict[str, Any]:
        outcome = await workflow.execute_activity(
            fetch_and_classify_sharesansar_url_activity,
            args=[claimed["id"], claimed["url"], claimed["published_at_iso"], timeout],
            start_to_close_timeout=timedelta(seconds=45),
            retry_policy=_DEFAULT_RETRY_POLICY,
        )

        inserted = 0
        if outcome["status"] == "inserted" and outcome["article"] is not None:
            inserted = await workflow.execute_activity(
                write_articles_activity,
                args=[[outcome["article"]]],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

            target_date_iso = outcome["article"]["published_at"][:10]
            await workflow.execute_activity(
                upsert_backfill_progress_activity,
                args=[_SOURCE, target_date_iso, 1, inserted],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

        return {
            "status": outcome["status"],
            "url": claimed["url"],
            "inserted": inserted,
        }
