from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities.csv_import_activities import (
        check_csv_import_done_activity,
        parse_and_write_csv_activity,
    )
    from activities.pipeline_log_activities import write_pipeline_run_log_activity

_DEFAULT_RETRY_POLICY = RetryPolicy(maximum_attempts=3)
_CSV_IMPORT_MESSAGE = "historical_nepse_csv_import"


@workflow.defn
class HistoricalNepseCsvImportWorkflow:
    """One-shot startup import of historical NEPSE index CSVs into
    nepse_index. Mirrors old scheduler.py start_scheduler() CSV-import
    startup block exactly, including the idempotency check via
    has_successful_pipeline_message and the failed-status log-on-exception
    behavior."""

    @workflow.run
    async def run(self, csv_dir: str) -> dict[str, Any]:
        started_at = workflow.now()

        already_done = await workflow.execute_activity(
            check_csv_import_done_activity,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DEFAULT_RETRY_POLICY,
        )

        if already_done:
            return {
                "status": "skipped",
                "message": "already imported",
                "parsed": 0,
                "inserted": 0,
            }

        try:
            result = await workflow.execute_activity(
                parse_and_write_csv_activity,
                args=[csv_dir],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )
            parsed = result["parsed"]
            inserted = result["inserted"]

            finished_at = workflow.now()
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)

            await workflow.execute_activity(
                write_pipeline_run_log_activity,
                args=[
                    {
                        "status": "success",
                        "message": _CSV_IMPORT_MESSAGE,
                        "error_text": None,
                        "news_total": 0,
                        "news_inserted": 0,
                        "nepse_records": inserted,
                        "nepse_source": "csv_historical",
                        "started_at": started_at.isoformat(),
                        "finished_at": finished_at.isoformat(),
                        "duration_ms": duration_ms,
                    }
                ],
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_DEFAULT_RETRY_POLICY,
            )

            return {
                "status": "success",
                "message": _CSV_IMPORT_MESSAGE,
                "parsed": parsed,
                "inserted": inserted,
            }
        except Exception as e:  # noqa: BLE001 - mirrors old broad except handling
            error_text = str(e)
            now = workflow.now()

            try:
                await workflow.execute_activity(
                    write_pipeline_run_log_activity,
                    args=[
                        {
                            "status": "failed",
                            "message": _CSV_IMPORT_MESSAGE,
                            "error_text": error_text,
                            "news_total": 0,
                            "news_inserted": 0,
                            "nepse_records": 0,
                            "nepse_source": "csv_historical",
                            "started_at": now.isoformat(),
                            "finished_at": now.isoformat(),
                            "duration_ms": 0,
                        }
                    ],
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=_DEFAULT_RETRY_POLICY,
                )
            except Exception as log_err:  # noqa: BLE001
                workflow.logger.error(
                    f"[Scheduler] Failed to write historical import log: {log_err}"
                )

            return {
                "status": "failed",
                "message": _CSV_IMPORT_MESSAGE,
                "error_text": error_text,
                "parsed": 0,
                "inserted": 0,
            }
