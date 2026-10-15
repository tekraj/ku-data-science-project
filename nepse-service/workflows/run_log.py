"""pipeline_run_logs helper for the research/EOD workflows (each run writes
one row, surfaced on the dashboard's Logs page, same as every other
workflow in this service). Workflow-side code: only schedules an activity."""
from __future__ import annotations

from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities.pipeline_log_activities import write_pipeline_run_log_activity


async def write_run_log(
    started_at: datetime,
    *,
    status: str,
    message: str,
    error_text: str | None,
    records: int,
    source: str,
) -> None:
    finished_at = workflow.now()
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
                    "nepse_source": source,
                    "started_at": started_at.isoformat(),
                    "finished_at": finished_at.isoformat(),
                    "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
                }
            ],
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
    except Exception as log_err:  # noqa: BLE001
        workflow.logger.error(f"[{source}] Failed to write run log: {log_err}")
