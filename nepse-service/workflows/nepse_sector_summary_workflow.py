from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from nepse_common.config import load_app_config

    from activities.nepse_activities import is_market_open_activity
    from activities.nepse_market_activities import (
        scrape_sector_summary_activity,
        write_sector_summary_activity,
    )
    from activities.pipeline_log_activities import write_pipeline_run_log_activity

_DEFAULT_RETRY_POLICY = RetryPolicy(maximum_attempts=3)


@workflow.defn
class NepseSectorSummaryScrapeWorkflow:
    """Scrapes the sector-wise turnover/volume/transaction summary from
    nepalstock.com.np and writes to nepse_sector_summary. Gated to market
    hours (see NepseTodayPriceScrapeWorkflow for the rationale) and split
    into its own workflow/schedule for the same partial-failure-isolation
    reasons."""

    @workflow.run
    async def run(self) -> dict[str, Any]:
        scraper_cfg = load_app_config().scraper

        started_at = workflow.now()
        status = "success"
        message = "completed"
        error_text: str | None = None
        records = 0

        try:
            market_open = await workflow.execute_activity(
                is_market_open_activity,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

            if not market_open:
                message = "market closed - sector-summary skipped"
            else:
                rows = await workflow.execute_activity(
                    scrape_sector_summary_activity,
                    args=[scraper_cfg.request_timeout],
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=_DEFAULT_RETRY_POLICY,
                )
                records = await workflow.execute_activity(
                    write_sector_summary_activity,
                    args=[rows],
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=_DEFAULT_RETRY_POLICY,
                )
        except Exception as e:  # noqa: BLE001 - mirrors NepseIndexScrapeWorkflow's broad except
            status = "failed"
            message = "sector-summary pipeline crashed"
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
                        "nepse_records": records,
                        "nepse_source": "nepalstock_sector_summary",
                        "started_at": started_at.isoformat(),
                        "finished_at": finished_at.isoformat(),
                        "duration_ms": duration_ms,
                    }
                ],
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )
        except Exception as log_err:  # noqa: BLE001
            workflow.logger.error(f"[SectorSummary] Failed to write run log: {log_err}")

        return {"status": status, "message": message, "error_text": error_text, "records": records}
