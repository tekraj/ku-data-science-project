from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from nepse_common.config import load_app_config
    from nepse_common.constants.index_registry import INDEX_REGISTRY

    from activities.research_data_activities import (
        backfill_intraday_ticks_activity,
        capture_eod_stock_prices_activity,
        capture_official_index_history_activity,
        intraday_stock_symbols,
        sync_security_master_activity,
    )
    from workflows.run_log import write_run_log

_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30))


@workflow.defn
class NepseEndOfDayWorkflow:
    """After the close (Mon-Fri, see register_schedules.py), extend the
    research datasets by today's session:
      1. official daily bar for every traded equity -> nepse_stock_daily
         (skips the rest on a holiday);
      2. official daily bars for all 17 indices (last 10 sessions, so a
         missed evening self-heals) -> nepse_index_daily;
      3. today's intraday ticks -> nepse_intraday_tick (forward fill only;
         deep history is the weekly ResearchHistoryBackfillWorkflow's job).
    """

    @workflow.run
    async def run(self) -> dict[str, Any]:
        cfg = load_app_config().scraper
        started_at = workflow.now()
        status, error_text, records = "success", None, 0
        failures: list[str] = []
        try:
            eod = await workflow.execute_activity(
                capture_eod_stock_prices_activity,
                args=[cfg.request_timeout],
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=_RETRY,
            )
            if eod["status"] == "skipped":
                message = f"no session today (latest business date {eod.get('business_date')})"
            else:
                records += eod["rows"]
                records += await workflow.execute_activity(
                    capture_official_index_history_activity,
                    args=[cfg.request_timeout, 10],
                    start_to_close_timeout=timedelta(minutes=5),
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=_RETRY,
                )

                targets = [(spec.name, "index", spec.merolagani_symbol) for spec in INDEX_REGISTRY] if cfg.intraday_backfill_indices else []
                equities: list[dict[str, Any]] = []
                if cfg.intraday_backfill_stocks.strip().upper() == "ALL":
                    equities = await workflow.execute_activity(
                        sync_security_master_activity,
                        args=[cfg.request_timeout],
                        start_to_close_timeout=timedelta(minutes=3),
                        retry_policy=_RETRY,
                    )
                targets += [(s, "equity", s) for s in intraday_stock_symbols(cfg.intraday_backfill_stocks, equities)]
                for symbol, kind, source_symbol in targets:
                    try:
                        result = await workflow.execute_activity(
                            backfill_intraday_ticks_activity,
                            args=[symbol, kind, source_symbol, cfg.intraday_backfill_start_date, 60, cfg.merolagani_request_pause_seconds, False],
                            start_to_close_timeout=timedelta(minutes=20),
                            heartbeat_timeout=timedelta(minutes=5),
                            retry_policy=_RETRY,
                        )
                        records += result["rows"]
                    except Exception:  # noqa: BLE001 - one symbol must not sink the rest
                        failures.append(symbol)

                message = f"EOD captured: {eod['rows']} stock bars, {records} rows total"
                if failures:
                    message += f"; intraday failed for {', '.join(failures)}"
        except Exception as e:  # noqa: BLE001
            status, message, error_text = "failed", "end-of-day capture crashed", str(e)

        await write_run_log(started_at, status=status, message=message, error_text=error_text, records=records, source="research_end_of_day")
        return {"status": status, "message": message, "error_text": error_text, "records": records}
