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

# Every listed date is a real NEPSE session, so a run of "no data" answers
# means merolagani is degraded, not empty: on 2026-10-17/18 it answered
# every 2021-2022 search with an empty page for ~36 h and the walk skipped
# ~540 sessions in a row. After this many in a row, pause and retry the
# current session before moving on.
_NO_DATA_STREAK_PAUSE_AFTER = 5
_NO_DATA_PAUSE = timedelta(minutes=30)
_NO_DATA_PAUSES_PER_SESSION = 4


@workflow.defn
class FloorSheetHistoryBackfillWorkflow:
    """Completes nepse_floorsheet for past sessions from merolagani's
    floor-sheet history (see scraper/merolagani_floorsheet.py): broker ids
    on every trade plus the trades the intraday scrape missed. Covers every
    NEPSE session from `start_date` (default FLOORSHEET_BACKFILL_START_DATE)
    to yesterday -- today belongs to the post-close NEPSE sweep. Days already
    filled cost nothing. Two entry points:
      - worker startup: the full range (the deep walk; with a 2020 start it
        runs for weeks and simply resumes after a restart, since the startup
        id is reused only once the previous run has closed);
      - weekly schedule (Sunday): lookback_days=30, a safety net so a missed
        evening sweep heals within a week without starting a second deep
        walk alongside the startup one."""

    @workflow.run
    async def run(
        self, start_date: str | None = None, end_date: str | None = None, lookback_days: int | None = None
    ) -> dict[str, Any]:
        cfg = load_app_config().scraper
        started_at = workflow.now()
        yesterday = workflow.now().astimezone(NPT).date() - timedelta(days=1)
        if lookback_days:
            start_date = max(cfg.floorsheet_backfill_start_date, (yesterday - timedelta(days=lookback_days)).isoformat())
        start_date = start_date or cfg.floorsheet_backfill_start_date
        end_date = end_date or yesterday.isoformat()

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
        no_data_streak = 0
        pause_on_streak = workflow.patched("floorsheet-no-data-streak-pause")
        for i, day in enumerate(batch):
            if i:
                await workflow.sleep(timedelta(seconds=cfg.merolagani_request_pause_seconds))
            try:
                for pause in range(_NO_DATA_PAUSES_PER_SESSION + 1):
                    result = await workflow.execute_activity(
                        backfill_floor_sheet_day_activity,
                        args=[day, 120, cfg.merolagani_request_pause_seconds],
                        # Old sessions take 10-30 s per page on merolagani's side;
                        # the busiest (2021-08-18) has 377 pages. Retries resume
                        # from the last heartbeated page.
                        start_to_close_timeout=timedelta(hours=8),
                        heartbeat_timeout=timedelta(minutes=10),
                        retry_policy=_RETRY,
                    )
                    degraded = result["status"] == "no data" and no_data_streak + 1 >= _NO_DATA_STREAK_PAUSE_AFTER
                    if not (pause_on_streak and degraded) or pause == _NO_DATA_PAUSES_PER_SESSION:
                        break
                    await workflow.sleep(_NO_DATA_PAUSE)
            except Exception:  # noqa: BLE001 - one day must not sink the rest
                failed.append(day)
                continue
            no_data_streak = no_data_streak + 1 if result["status"] == "no data" else 0
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
