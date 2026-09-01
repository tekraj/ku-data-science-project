from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from nepse_common.config import load_app_config

    from activities.nepse_activities import (
        is_market_open_activity,
        scrape_nepse_index_activity,
        write_nepse_index_activity,
    )
    from activities.pipeline_log_activities import write_pipeline_run_log_activity

_DEFAULT_RETRY_POLICY = RetryPolicy(maximum_attempts=3)


@workflow.defn
class NepseIndexScrapeWorkflow:
    """Scrapes the live NEPSE index + sector indices and writes to
    nepse_index.

    NOTE: in the old monolith, run_pipeline() did news scraping AND the
    live NEPSE index scrape in a single pipeline_run_logs row per run. Here
    they are split into two separate Temporal workflows/schedules
    (NewsScrapeWorkflow and this one), so each pipeline_run_logs row
    written by THIS workflow reflects ONLY the nepse portion (news_total=0,
    news_inserted=0 always). This is an intentional, acceptable behavior
    split now that news and index scraping run independently.
    """

    @workflow.run
    async def run(self) -> dict[str, Any]:
        config = load_app_config()
        scraper_cfg = config.scraper

        started_at = workflow.now()
        status = "success"
        message = "completed"
        error_text: str | None = None
        nepse_records = 0
        nepse_source = "none"

        try:
            if not scraper_cfg.live_nepse_scrape_enabled:
                message = "live nepse scrape disabled - news only"
            else:
                market_open = await workflow.execute_activity(
                    is_market_open_activity,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_DEFAULT_RETRY_POLICY,
                )

                if not market_open:
                    message = "market closed - nepse skipped"
                else:
                    nepse_data = await workflow.execute_activity(
                        scrape_nepse_index_activity,
                        args=[scraper_cfg.request_timeout],
                        start_to_close_timeout=timedelta(minutes=3),
                        retry_policy=_DEFAULT_RETRY_POLICY,
                    )

                    nepse_records = await workflow.execute_activity(
                        write_nepse_index_activity,
                        args=[nepse_data],
                        start_to_close_timeout=timedelta(minutes=1),
                        retry_policy=_DEFAULT_RETRY_POLICY,
                    )
                    nepse_source = str(
                        nepse_data.get("source_used") or nepse_data.get("source") or "unknown"
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
                        "news_total": 0,
                        "news_inserted": 0,
                        "nepse_records": nepse_records,
                        "nepse_source": nepse_source,
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
            "nepse_records": nepse_records,
            "nepse_source": nepse_source,
        }
