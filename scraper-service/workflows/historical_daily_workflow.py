from __future__ import annotations

from datetime import timedelta, timezone
from typing import Any

import pytz
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from nepse_common.config import load_app_config

    from activities.historical_activities import scrape_historical_day_activity
    from activities.news_activities import write_articles_activity
    from activities.pipeline_log_activities import write_pipeline_run_log_activity

_DEFAULT_RETRY_POLICY = RetryPolicy(maximum_attempts=3)
_HISTORICAL_QUEUE = "historical-gdelt-queue"
_NST = pytz.timezone("Asia/Kathmandu")


@workflow.defn
class HistoricalDailyBackfillWorkflow:
    """Scrapes one day of historical GDELT-backed news and writes it to
    nepse_news. Mirrors old scheduler.py run_historical_daily_pipeline()."""

    @workflow.run
    async def run(self, target_day_iso: str | None = None) -> dict[str, Any]:
        config = load_app_config()
        scraper_cfg = config.scraper

        if target_day_iso is None:
            # workflow.now() is deterministic/replay-safe (backed by the
            # workflow's current time, UTC). Convert to NPT the same way as
            # old _now_nst(), then take "yesterday" the same way old code did.
            now_utc = workflow.now().replace(tzinfo=timezone.utc)
            now_nst = now_utc.astimezone(_NST)
            day = now_nst.date() - timedelta(days=1)
            target_day_iso = day.isoformat()

        started_at = workflow.now()
        status = "success"
        message = "completed"
        error_text: str | None = None
        fetched = 0
        inserted = 0

        try:
            articles = await workflow.execute_activity(
                scrape_historical_day_activity,
                args=[
                    target_day_iso,
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
        except Exception as e:  # noqa: BLE001 - mirrors old broad except handling
            status = "failed"
            message = "historical daily pipeline crashed"
            error_text = str(e)

        finished_at = workflow.now()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        try:
            await workflow.execute_activity(
                write_pipeline_run_log_activity,
                args=[
                    {
                        "status": status,
                        "message": message,
                        "error_text": error_text,
                        "news_total": fetched,
                        "news_inserted": inserted,
                        "nepse_records": 0,
                        "nepse_source": "none",
                        "started_at": started_at.isoformat(),
                        "finished_at": finished_at.isoformat(),
                        "duration_ms": duration_ms,
                    }
                ],
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )
        except Exception as log_err:  # noqa: BLE001
            workflow.logger.error(f"[Historical] Failed to write run log: {log_err}")

        return {
            "day": target_day_iso,
            "fetched": fetched,
            "inserted": inserted,
        }
