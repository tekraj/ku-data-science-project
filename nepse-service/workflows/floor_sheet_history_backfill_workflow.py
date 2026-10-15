from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from nepse_common.config import load_app_config

    from activities.nepse_market_activities import (
        backfill_floor_sheet_day_activity,
        list_trading_days_activity,
    )
    from scraper.merolagani_history import NPT
    from workflows.run_log import write_run_log

_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(minutes=1))
# Sessions per execution before continue-as-new keeps the event history
# small (a deep backfill from 2020 is ~1,500 sessions).
_DAYS_PER_RUN = 100


@workflow.defn
class FloorSheetHistoryBackfillWorkflow:
    """Completes nepse_floorsheet for past sessions from merolagani's
    floor-sheet history (see scraper/merolagani_floorsheet.py): broker ids
    on every trade plus the trades the intraday scrape missed. Covers every
    NEPSE session from `start_date` (default FLOORSHEET_BACKFILL_START_DATE)
    to yesterday -- today belongs to the post-close NEPSE sweep. Days that
    are already complete cost one request. Runs weekly (Sunday) and on worker
    startup, so a missed evening sweep heals itself within a week."""

    @workflow.run
    async def run(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        cfg = load_app_config().scraper
        started_at = workflow.now()
        start_date = start_date or cfg.floorsheet_backfill_start_date
        end_date = end_date or (workflow.now().astimezone(NPT).date() - timedelta(days=1)).isoformat()

        days = await workflow.execute_activity(
            list_trading_days_activity,
            args=[start_date, end_date],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_RETRY,
        )
        batch, rest = days[:_DAYS_PER_RUN], days[_DAYS_PER_RUN:]

        counts = {"filled": 0, "complete": 0, "no data": 0}
        inserted = updated = 0
        failed: list[str] = []
        for i, day in enumerate(batch):
            if i:
                await workflow.sleep(timedelta(seconds=cfg.merolagani_request_pause_seconds))
            try:
                result = await workflow.execute_activity(
                    backfill_floor_sheet_day_activity,
                    args=[day, 60, cfg.merolagani_request_pause_seconds],
                    start_to_close_timeout=timedelta(hours=2),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=_RETRY,
                )
            except Exception:  # noqa: BLE001 - one day must not sink the rest
                failed.append(day)
                continue
            counts[result["status"]] = counts.get(result["status"], 0) + 1
            inserted += int(result.get("inserted", 0) or 0)
            updated += int(result.get("updated", 0) or 0)

        span = f"{batch[0]}..{batch[-1]}" if batch else f"{start_date}..{end_date} (no sessions)"
        message = (
            f"{span}: {counts['filled']} days filled, {counts['complete']} already complete, "
            f"{counts['no data']} without data; {inserted} trades inserted, {updated} given broker ids"
        )
        if failed:
            message += f"; failed: {', '.join(failed)}"
        await write_run_log(
            started_at,
            status="failed" if failed and not (counts["filled"] or counts["complete"]) else "success",
            message=message,
            error_text=None,
            records=inserted + updated,
            source="merolagani_floor_sheet_history",
        )

        if rest:
            workflow.continue_as_new(args=[rest[0], end_date])
        return {"message": message, "failed": failed}
