from __future__ import annotations

import asyncio
import os

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.worker import Worker

from nepse_common.config import load_app_config

from register_schedules import upsert_all_schedules, SITEMAP_BACKFILL_SOURCES

from workflows.news_scrape_workflow import NewsScrapeWorkflow
from workflows.historical_daily_workflow import HistoricalDailyBackfillWorkflow
from workflows.historical_backfill_workflow import HistoricalBackfillWorkflow
from workflows.historical_sitemap_backfill_workflow import (
    HistoricalSitemapBackfillTickWorkflow,
    HistoricalSitemapBackfillStatusWorkflow,
    HistoricalSitemapDiscoveryWorkflow,
    HistoricalBackfillReapWorkflow,
)
from workflows.historical_cursor_backfill_workflow import HistoricalCursorBackfillTickWorkflow
from workflows.historical_idwalk_backfill_workflow import (
    HistoricalIdWalkBackfillTickWorkflow,
    HistoricalIdWalkStatusWorkflow,
)
from workflows.nepse_news_fields_backfill_workflow import (
    NepseNewsFieldsBackfillTickWorkflow,
    NepseNewsFieldsBackfillStatusWorkflow,
)

from activities.news_activities import scrape_news_activity, write_articles_activity
from activities.historical_activities import scrape_historical_day_activity
from activities.pipeline_log_activities import write_pipeline_run_log_activity
from activities.historical_sitemap_backfill_activities import (
    claim_next_pending_url_activity,
    discover_and_enqueue_urls_activity,
    fetch_and_classify_url_activity,
    get_sitemap_backfill_progress_activity,
    mark_url_failed_activity,
    reap_stale_claims_activity,
    upsert_backfill_progress_activity,
)
from activities.historical_cursor_backfill_activities import (
    claim_next_pending_sharesansar_url_activity,
    fetch_and_classify_sharesansar_url_activity,
    fetch_cursor_listing_page_activity,
    get_cursor_state_activity,
    save_cursor_state_activity,
)
from activities.nepse_news_fields_backfill_activities import (
    apply_fields_backfill_activity,
    claim_next_fields_backfill_row_activity,
    get_fields_backfill_progress_activity,
)
from activities.historical_idwalk_backfill_activities import (
    fetch_and_classify_idwalk_id_activity,
    get_idwalk_progress_activity,
    get_next_idwalk_id_activity,
)

# Renamed from "nepse-scraper-queue" as part of the news/nepse service split
# -- this queue now carries ONLY news scraping + news historical-backfill
# workflows. NEPSE market-data workflows moved to nepse-service's own
# "nepse-market-queue" (see nepse-service/worker.py). NOTE: api-service's
# services/temporal_client.py TASK_QUEUE constant was updated to match this
# name, since it starts HistoricalBackfillWorkflow (GDELT news backfill,
# stayed here) against this queue.
_GENERAL_QUEUE = "news-scraper-queue"
_HISTORICAL_QUEUE = "historical-gdelt-queue"

_ALL_WORKFLOWS = [
    NewsScrapeWorkflow,
    HistoricalDailyBackfillWorkflow,
    HistoricalBackfillWorkflow,
    HistoricalSitemapBackfillTickWorkflow,
    HistoricalSitemapBackfillStatusWorkflow,
    HistoricalSitemapDiscoveryWorkflow,
    HistoricalBackfillReapWorkflow,
    HistoricalCursorBackfillTickWorkflow,
    HistoricalIdWalkBackfillTickWorkflow,
    HistoricalIdWalkStatusWorkflow,
    NepseNewsFieldsBackfillTickWorkflow,
    NepseNewsFieldsBackfillStatusWorkflow,
]

# All activities except the GDELT-backed historical one, which is reserved
# for the dedicated, rate-limited historical-gdelt-queue worker below.
_GENERAL_ACTIVITIES = [
    scrape_news_activity,
    write_articles_activity,
    write_pipeline_run_log_activity,
    discover_and_enqueue_urls_activity,
    claim_next_pending_url_activity,
    fetch_and_classify_url_activity,
    mark_url_failed_activity,
    reap_stale_claims_activity,
    get_sitemap_backfill_progress_activity,
    upsert_backfill_progress_activity,
    claim_next_pending_sharesansar_url_activity,
    fetch_and_classify_sharesansar_url_activity,
    fetch_cursor_listing_page_activity,
    get_cursor_state_activity,
    save_cursor_state_activity,
    apply_fields_backfill_activity,
    claim_next_fields_backfill_row_activity,
    get_fields_backfill_progress_activity,
    fetch_and_classify_idwalk_id_activity,
    get_idwalk_progress_activity,
    get_next_idwalk_id_activity,
]

_HISTORICAL_GDELT_ACTIVITIES = [
    scrape_historical_day_activity,
]


async def main() -> None:
    temporal_address = os.getenv("TEMPORAL_ADDRESS", "temporal:7233")
    client = await Client.connect(temporal_address)

    general_worker = Worker(
        client,
        task_queue=_GENERAL_QUEUE,
        workflows=_ALL_WORKFLOWS,
        activities=_GENERAL_ACTIVITIES,
    )

    # Dedicated worker for GDELT-backed historical scraping, isolated onto
    # its own task queue with max_concurrent_activities=1 so the
    # module-global GDELT rate limiter in scraper/historical_scraper.py
    # behaves correctly (one in-flight GDELT call at a time).
    historical_gdelt_worker = Worker(
        client,
        task_queue=_HISTORICAL_QUEUE,
        activities=_HISTORICAL_GDELT_ACTIVITIES,
        max_concurrent_activities=1,
    )

    await upsert_all_schedules(client)

    scraper_cfg = load_app_config().scraper

    if scraper_cfg.historical_news_backfill_enabled:
        # Seed each sitemap portal's URL queue on every startup (including
        # container restarts / `docker-compose up` reruns) rather than
        # requiring someone to trigger it by hand. Same
        # ALLOW_DUPLICATE_FAILED_ONLY + fixed-id pattern as the CSV import
        # (moved to nepse-service): a prior successful (or still-running)
        # discovery run for this portal is left alone, so this is a cheap
        # no-op on every restart after the first -- discover_and_enqueue_urls_activity
        # is itself idempotent too (ON CONFLICT DO NOTHING on source+url), so
        # even a duplicate run wouldn't corrupt anything, this just avoids
        # the redundant sitemap crawl.
        for source in SITEMAP_BACKFILL_SOURCES:
            try:
                await client.start_workflow(
                    HistoricalSitemapDiscoveryWorkflow.run,
                    args=[source, scraper_cfg.historical_request_timeout],
                    id=f"historical-sitemap-discovery-{source}",
                    task_queue=_GENERAL_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                )
            except Exception as e:
                print(f"[Worker] Failed to start historical sitemap discovery for {source}: {e}")

    await asyncio.gather(
        general_worker.run(),
        historical_gdelt_worker.run(),
    )


if __name__ == "__main__":
    asyncio.run(main())
