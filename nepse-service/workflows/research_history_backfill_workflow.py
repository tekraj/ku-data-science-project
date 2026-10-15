from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from nepse_common.config import load_app_config
    from nepse_common.constants.index_registry import INDEX_REGISTRY

    from activities.research_data_activities import (
        backfill_index_daily_activity,
        backfill_intraday_ticks_activity,
        backfill_stock_daily_activity,
        capture_official_index_history_activity,
        daily_refresh_due_activity,
        intraday_stock_symbols,
        mark_daily_refresh_done_activity,
        sync_security_master_activity,
    )
    from workflows.run_log import write_run_log

_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30))
# Weekly schedule fires every 7 days; a startup run inside this window
# skips the ~1000-request per-equity refresh.
_DAILY_REFRESH_MAX_AGE_HOURS = 6 * 24


@workflow.defn
class ResearchHistoryBackfillWorkflow:
    """Builds (first run) and refreshes (weekly + on worker startup) the
    long-history research datasets:
      1. nepse_security            -- security master (incl. delisted).
      2. nepse_index_daily         -- full daily history of all 17 indices
                                      (merolagani, NEPSE from 2000), plus
                                      the official last ~1 year with share
                                      volume / transaction counts.
      3. nepse_stock_daily         -- full raw + bonus/right-adjusted daily
                                      history of every equity, incl.
                                      delisted ones (skipped if refreshed
                                      in the last 6 days, unless forced).
      4. nepse_intraday_tick       -- ~1-minute ticks for all indices back to
                                      INTRADAY_BACKFILL_START_DATE, plus
                                      opt-in equities (INTRADAY_BACKFILL_STOCKS).
                                      Resumable via research_backfill_state.
    Requests to merolagani are paced MEROLAGANI_REQUEST_PAUSE_SECONDS apart.
    One symbol failing is recorded and skipped, never fatal to the run."""

    @workflow.run
    async def run(self, force_daily_refresh: bool = False) -> dict[str, Any]:
        cfg = load_app_config().scraper
        started_at = workflow.now()
        pause = timedelta(seconds=cfg.merolagani_request_pause_seconds)
        counts = {"index_daily": 0, "official_index_daily": 0, "stock_daily": 0, "intraday": 0}
        failures: dict[str, list[str]] = {"index_daily": [], "stock_daily": [], "intraday": []}
        status, error_text = "success", None

        if not cfg.research_backfill_enabled:
            await write_run_log(started_at, status="success", message="research backfill disabled", error_text=None, records=0, source="research_history_backfill")
            return {"status": "skipped"}

        try:
            equities = await workflow.execute_activity(
                sync_security_master_activity,
                args=[cfg.request_timeout],
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=_RETRY,
            )

            for spec in INDEX_REGISTRY:
                try:
                    counts["index_daily"] += await workflow.execute_activity(
                        backfill_index_daily_activity,
                        args=[spec.name, 90],
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=_RETRY,
                    )
                except Exception:  # noqa: BLE001
                    failures["index_daily"].append(spec.name)
                await workflow.sleep(pause)

            try:
                counts["official_index_daily"] = await workflow.execute_activity(
                    capture_official_index_history_activity,
                    args=[cfg.request_timeout, 500],
                    start_to_close_timeout=timedelta(minutes=10),
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=_RETRY,
                )
            except Exception:  # noqa: BLE001
                failures["index_daily"].append("official index history")

            due = force_daily_refresh or await workflow.execute_activity(
                daily_refresh_due_activity,
                args=[_DAILY_REFRESH_MAX_AGE_HOURS],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_RETRY,
            )
            if due:
                for equity in equities:
                    try:
                        result = await workflow.execute_activity(
                            backfill_stock_daily_activity,
                            args=[equity["symbol"], 90, cfg.merolagani_request_pause_seconds],
                            start_to_close_timeout=timedelta(minutes=5),
                            retry_policy=_RETRY,
                        )
                        counts["stock_daily"] += result["raw"]
                    except Exception:  # noqa: BLE001
                        failures["stock_daily"].append(equity["symbol"])
                    await workflow.sleep(pause)
                await workflow.execute_activity(
                    mark_daily_refresh_done_activity,
                    args=[counts["stock_daily"]],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_RETRY,
                )

            targets = [(spec.name, "index", spec.merolagani_symbol) for spec in INDEX_REGISTRY] if cfg.intraday_backfill_indices else []
            targets += [(s, "equity", s) for s in intraday_stock_symbols(cfg.intraday_backfill_stocks, equities)]
            for symbol, kind, source_symbol in targets:
                try:
                    result = await workflow.execute_activity(
                        backfill_intraday_ticks_activity,
                        args=[symbol, kind, source_symbol, cfg.intraday_backfill_start_date, 90, cfg.merolagani_request_pause_seconds, True],
                        start_to_close_timeout=timedelta(hours=3),
                        heartbeat_timeout=timedelta(minutes=10),
                        retry_policy=_RETRY,
                    )
                    counts["intraday"] += result["rows"]
                except Exception:  # noqa: BLE001
                    failures["intraday"].append(symbol)
        except Exception as e:  # noqa: BLE001
            status, error_text = "failed", str(e)

        failed = {k: v for k, v in failures.items() if v}
        message = ", ".join(f"{k}={v}" for k, v in counts.items())
        if failed:
            message += "; failed: " + "; ".join(f"{k}: {', '.join(v[:20])}{' ...' if len(v) > 20 else ''}" for k, v in failed.items())
        await write_run_log(
            started_at,
            status=status,
            message=message,
            error_text=error_text,
            records=sum(counts.values()),
            source="research_history_backfill",
        )
        return {"status": status, "counts": counts, "failures": failed, "error_text": error_text}
