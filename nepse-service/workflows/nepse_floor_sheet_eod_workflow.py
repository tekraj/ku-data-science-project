from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from nepse_common.config import load_app_config

    from activities.nepse_market_activities import sweep_floor_sheet_activity
    from workflows.run_log import write_run_log


@workflow.defn
class NepseFloorSheetEodSweepWorkflow:
    """After the close (Mon-Fri, see register_schedules.py): read the whole
    session's floor sheet page by page and upsert it, so nepse_floorsheet
    ends every day complete (the 500-contracts-per-minute intraday scrape
    captured only 69-100% of contracts per day) and with broker member
    ids/names, which NEPSE publishes only after 15:00. Runs more than once
    per evening as a safety net; re-runs only touch rows still missing
    something."""

    @workflow.run
    async def run(self) -> dict[str, Any]:
        scraper_cfg = load_app_config().scraper
        started_at = workflow.now()
        status, error_text, result = "success", None, {}
        try:
            result = await workflow.execute_activity(
                sweep_floor_sheet_activity,
                args=[max(scraper_cfg.request_timeout, 30)],
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30)),
            )
            if result.get("status") == "skipped":
                message = f"no session today (latest floor sheet is {result.get('business_date')})"
            else:
                message = (
                    f"swept {result['pages']} pages: {result['stored']}/{result['total_trades']} contracts stored, "
                    f"{result['inserted']} inserted, {result['updated']} filled, {result['with_broker']} with broker ids"
                )
        except Exception as e:  # noqa: BLE001
            status, message, error_text = "failed", "floor-sheet EOD sweep crashed", str(e)

        await write_run_log(
            started_at,
            status=status,
            message=message,
            error_text=error_text,
            records=int(result.get("inserted", 0) or 0) + int(result.get("updated", 0) or 0),
            source="nepalstock_floor_sheet_eod",
        )
        return {"status": status, "message": message, "error_text": error_text, **result}
