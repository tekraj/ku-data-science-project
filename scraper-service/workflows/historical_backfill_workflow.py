from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from nepse_common.config import load_app_config

    from activities.historical_activities import scrape_historical_day_activity
    from activities.news_activities import write_articles_activity

_DEFAULT_RETRY_POLICY = RetryPolicy(maximum_attempts=3)
_HISTORICAL_QUEUE = "historical-gdelt-queue"


@workflow.defn
class HistoricalBackfillWorkflow:
    """Backfills historical news over an inclusive date range, day by day.

    This is the workflow triggered by api-service POST
    /admin/historical/backfill. Mirrors old scheduler.py
    run_historical_backfill(), but reuses the day-scraping/write activities
    directly (rather than invoking HistoricalDailyBackfillWorkflow as a
    child workflow) to keep this workflow simple.
    """

    @workflow.run
    async def run(self, start_date_iso: str, end_date_iso: str) -> dict[str, Any]:
        start_date = datetime.strptime(start_date_iso, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_iso, "%Y-%m-%d").date()

        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")

        config = load_app_config()
        scraper_cfg = config.scraper

        total_days = 0
        total_fetched = 0
        total_inserted = 0

        current = start_date
        while current <= end_date:
            day_iso = current.isoformat()

            articles = await workflow.execute_activity(
                scrape_historical_day_activity,
                args=[
                    day_iso,
                    scraper_cfg.historical_request_timeout,
                    scraper_cfg.historical_max_records_per_portal_per_day,
                ],
                task_queue=_HISTORICAL_QUEUE,
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )
            fetched = len(articles)

            inserted = await workflow.execute_activity(
                write_articles_activity,
                args=[articles],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

            total_days += 1
            total_fetched += fetched
            total_inserted += inserted

            # Deterministic, pure Python date arithmetic -- safe for replay.
            current += timedelta(days=1)

        return {
            "start_date": start_date_iso,
            "end_date": end_date_iso,
            "days": total_days,
            "fetched": total_fetched,
            "inserted": total_inserted,
        }
