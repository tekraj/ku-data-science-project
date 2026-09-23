from __future__ import annotations

import asyncio
import os

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.worker import Worker

from nepse_common.config import load_app_config

from register_schedules import upsert_all_schedules

from workflows.nepse_index_scrape_workflow import NepseIndexScrapeWorkflow
from workflows.historical_csv_import_workflow import HistoricalNepseCsvImportWorkflow
from workflows.nepse_today_price_workflow import NepseTodayPriceScrapeWorkflow
from workflows.nepse_sector_summary_workflow import NepseSectorSummaryScrapeWorkflow
from workflows.nepse_floor_sheet_workflow import NepseFloorSheetScrapeWorkflow
from workflows.nepse_market_depth_workflow import NepseMarketDepthScrapeWorkflow

from activities.nepse_activities import (
    is_market_open_activity,
    scrape_nepse_index_activity,
    write_nepse_index_activity,
)
from activities.csv_import_activities import (
    check_csv_import_done_activity,
    parse_and_write_csv_activity,
)
from activities.pipeline_log_activities import write_pipeline_run_log_activity
from activities.nepse_market_activities import (
    get_security_ids_activity,
    scrape_floor_sheet_activity,
    scrape_market_depth_for_security_activity,
    scrape_sector_summary_activity,
    scrape_today_price_activity,
    write_floor_sheet_activity,
    write_market_depth_activity,
    write_sector_summary_activity,
    write_today_price_activity,
)

# All NEPSE market-data workflows/activities (live index, the 4
# nepalstock.com.np endpoint scrapes, and the CSV import) share one task
# queue -- unlike news-service, none of these have a concrete concurrency
# reason to be isolated onto their own queue (contrast with news-service's
# dedicated historical-gdelt-queue, which exists specifically to rate-limit
# a module-global GDELT limiter to one in-flight call at a time). Distinct
# name from news-service's "news-scraper-queue" and from the pre-split
# "nepse-scraper-queue" (that name is retired, not reused, to avoid any
# ambiguity about which service's worker is polling which queue).
_GENERAL_QUEUE = "nepse-market-queue"

_CSV_IMPORT_WORKFLOW_ID = "historical-nepse-csv-import"

_ALL_WORKFLOWS = [
    NepseIndexScrapeWorkflow,
    HistoricalNepseCsvImportWorkflow,
    NepseTodayPriceScrapeWorkflow,
    NepseSectorSummaryScrapeWorkflow,
    NepseFloorSheetScrapeWorkflow,
    NepseMarketDepthScrapeWorkflow,
]

_ALL_ACTIVITIES = [
    is_market_open_activity,
    scrape_nepse_index_activity,
    write_nepse_index_activity,
    check_csv_import_done_activity,
    parse_and_write_csv_activity,
    write_pipeline_run_log_activity,
    get_security_ids_activity,
    scrape_floor_sheet_activity,
    scrape_market_depth_for_security_activity,
    scrape_sector_summary_activity,
    scrape_today_price_activity,
    write_floor_sheet_activity,
    write_market_depth_activity,
    write_sector_summary_activity,
    write_today_price_activity,
]


async def main() -> None:
    temporal_address = os.getenv("TEMPORAL_ADDRESS", "temporal:7233")
    client = await Client.connect(temporal_address)

    worker = Worker(
        client,
        task_queue=_GENERAL_QUEUE,
        workflows=_ALL_WORKFLOWS,
        activities=_ALL_ACTIVITIES,
    )

    await upsert_all_schedules(client)

    scraper_cfg = load_app_config().scraper

    try:
        await client.start_workflow(
            HistoricalNepseCsvImportWorkflow.run,
            scraper_cfg.historical_nepse_csv_dir,
            id=_CSV_IMPORT_WORKFLOW_ID,
            task_queue=_GENERAL_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )
    except Exception as e:
        # A failure here (e.g. workflow already running/completed under a
        # reuse policy that rejects duplicates) must not crash worker
        # startup -- the CSV import is best-effort and idempotent by design
        # (see check_csv_import_done_activity's has_successful_pipeline_message
        # check, unchanged from the pre-split scraper-service).
        print(f"[Worker] Failed to start historical CSV import workflow: {e}")

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
