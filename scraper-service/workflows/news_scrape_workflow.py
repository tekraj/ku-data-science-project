from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from nepse_common.config import load_app_config

    from activities.news_activities import scrape_news_activity, write_articles_activity
    from activities.pipeline_log_activities import write_pipeline_run_log_activity

_DEFAULT_RETRY_POLICY = RetryPolicy(maximum_attempts=3)


@workflow.defn
class NewsScrapeWorkflow:
    """Scrapes all 20 news portals and writes results to nepse_news.

    Mirrors the news-only portion of the old run_pipeline() in
    scheduler.py, including the try/except/finally structure: activity
    failures are caught so a failed pipeline_run_logs row is still written,
    and the workflow returns an error summary dict instead of failing
    outright, matching the old code's resilience.
    """

    @workflow.run
    async def run(self) -> dict[str, Any]:
        config = load_app_config()
        scraper_cfg = config.scraper

        started_at = workflow.now()
        status = "success"
        message = "completed"
        error_text: str | None = None
        news_total = 0
        news_inserted = 0

        try:
            articles = await workflow.execute_activity(
                scrape_news_activity,
                args=[scraper_cfg.request_timeout, scraper_cfg.max_articles_per_portal],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )
            news_total = len(articles)

            news_inserted = await workflow.execute_activity(
                write_articles_activity,
                args=[articles],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )
        except Exception as e:  # noqa: BLE001 - mirrors old broad except in run_pipeline()
            status = "failed"
            message = "pipeline crashed"
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
                        "news_total": news_total,
                        "news_inserted": news_inserted,
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
        except Exception as log_err:  # noqa: BLE001 - matches old log_err handling
            workflow.logger.error(f"[Pipeline] Failed to write run log: {log_err}")

        return {
            "status": status,
            "message": message,
            "error_text": error_text,
            "news_total": news_total,
            "news_inserted": news_inserted,
        }
