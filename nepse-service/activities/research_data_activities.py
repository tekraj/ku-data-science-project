"""Activities filling the research datasets (see CLAUDE.md "Research
datasets"): security master, deep daily OHLCV for every index and equity,
intraday ticks, and the official end-of-day captures.

Everything here writes through nepse_common.db.upserts, so every activity is
idempotent and safe to retry or re-run; long walks persist their progress in
research_backfill_state and resume from it.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from temporalio import activity

from nepse_common.config import load_app_config
from nepse_common.constants.index_registry import INDEX_BY_NAME, INDEX_REGISTRY
from nepse_common.db.session import session_scope
from nepse_common.db.upserts import (
    upsert_index_daily,
    upsert_intraday_ticks,
    upsert_securities,
    upsert_stock_daily_adjusted,
    upsert_stock_daily_raw,
)
from nepse_common.models import ResearchBackfillState

from scraper.merolagani_history import NPT, fetch_daily_bars, fetch_intraday_ticks, npt_today
from scraper.nepse_market_data import fetch_company_list, fetch_index_history, fetch_today_price
from scraper.nepse_wasm_auth import fetch_auth_context

_INTRADAY_WINDOW = timedelta(days=30)
# A session's daily bar is only final once the market has closed.
_SESSION_FINAL_AFTER = dtime(15, 10)
_DAILY_REFRESH_DATASET = "daily_full_refresh"


def intraday_stock_symbols(setting: str, equities: list[dict[str, Any]]) -> list[str]:
    """INTRADAY_BACKFILL_STOCKS: "" -> none, "ALL" -> every active equity,
    otherwise a comma-separated symbol list."""
    setting = (setting or "").strip()
    if not setting:
        return []
    if setting.upper() == "ALL":
        return [e["symbol"] for e in equities if e.get("status") == "A"]
    return [s.strip().upper() for s in setting.split(",") if s.strip()]


def _now_npt_naive() -> datetime:
    return datetime.now(NPT).replace(tzinfo=None)


def _completed_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop bars without a usable close, and today's bar while the session
    is still running."""
    now = _now_npt_naive()
    today = now.date()
    keep_today = now.time() >= _SESSION_FINAL_AFTER
    return [
        b
        for b in bars
        if b.get("close") not in (None, 0)
        and (b["trade_date"] < today or (b["trade_date"] == today and keep_today))
    ]


def _load_state(session, dataset: str, symbol: str) -> ResearchBackfillState | None:
    return session.execute(
        select(ResearchBackfillState).where(
            ResearchBackfillState.dataset == dataset, ResearchBackfillState.symbol == symbol
        )
    ).scalar_one_or_none()


def _save_state(dataset: str, symbol: str, **fields: Any) -> None:
    config = load_app_config()
    table = ResearchBackfillState.__table__
    values = {"dataset": dataset, "symbol": symbol, **fields, "last_run_at": _now_npt_naive()}
    with session_scope(config.database) as session:
        stmt = pg_insert(table).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["dataset", "symbol"],
            set_={k: getattr(stmt.excluded, k) for k in values if k not in ("dataset", "symbol")},
        )
        session.execute(stmt)


@activity.defn
async def sync_security_master_activity(timeout: int) -> list[dict[str, Any]]:
    """Upserts nepalstock's full company list (incl. suspended/delisted)
    into nepse_security and returns the equities as [{symbol, status}] --
    the universe for the per-stock history backfills."""
    rows = await asyncio.to_thread(fetch_company_list, timeout)
    records = [
        {
            "security_id": r["id"],
            "symbol": r["symbol"],
            "security_name": r.get("securityName"),
            "company_name": r.get("companyName"),
            "sector_name": r.get("sectorName"),
            "instrument_type": r.get("instrumentType"),
            "status": r.get("status"),
        }
        for r in rows
        if r.get("id") is not None and r.get("symbol")
    ]
    config = load_app_config()
    with session_scope(config.database) as session:
        upsert_securities(session, records)

    # Active status wins if a symbol was re-listed under a new id.
    equities: dict[str, str] = {}
    for r in records:
        if r["instrument_type"] == "Equity" and equities.get(r["symbol"]) != "A":
            equities[r["symbol"]] = r["status"]
    activity.logger.info(f"[Research] security master: {len(records)} securities, {len(equities)} equities")
    return [{"symbol": s, "status": st} for s, st in sorted(equities.items())]


@activity.defn
async def backfill_index_daily_activity(index_name: str, timeout: int) -> int:
    """Full daily history for one index from merolagani into
    nepse_index_daily (merolagani's `v` for indices is NPR turnover)."""
    spec = INDEX_BY_NAME[index_name]
    bars = _completed_bars(await asyncio.to_thread(fetch_daily_bars, spec.merolagani_symbol, False, timeout))
    rows = [
        {
            "index_name": index_name,
            "trade_date": b["trade_date"],
            "open": b["open"],
            "high": b["high"],
            "low": b["low"],
            "close": b["close"],
            "turnover": b["volume"],
        }
        for b in bars
    ]
    config = load_app_config()
    with session_scope(config.database) as session:
        upsert_index_daily(session, rows, source="merolagani")
    activity.logger.info(f"[Research] {index_name}: {len(rows)} daily bars")
    return len(rows)


@activity.defn
async def backfill_stock_daily_activity(symbol: str, timeout: int, pause_seconds: float) -> dict[str, int]:
    """Full raw + bonus/right-adjusted daily history for one equity from
    merolagani into nepse_stock_daily."""
    raw = _completed_bars(await asyncio.to_thread(fetch_daily_bars, symbol, False, timeout))
    await asyncio.sleep(pause_seconds)
    adjusted = _completed_bars(await asyncio.to_thread(fetch_daily_bars, symbol, True, timeout))

    raw_rows = [{"symbol": symbol, **{k: b[k] for k in ("trade_date", "open", "high", "low", "close", "volume")}} for b in raw]
    adj_rows = [
        {
            "symbol": symbol,
            "trade_date": b["trade_date"],
            "adj_open": b["open"],
            "adj_high": b["high"],
            "adj_low": b["low"],
            "adj_close": b["close"],
        }
        for b in adjusted
    ]
    config = load_app_config()
    with session_scope(config.database) as session:
        upsert_stock_daily_raw(session, raw_rows, source="merolagani")
        upsert_stock_daily_adjusted(session, adj_rows)
    return {"raw": len(raw_rows), "adjusted": len(adj_rows)}


@activity.defn
async def daily_refresh_due_activity(max_age_hours: int) -> bool:
    """True if the full per-equity daily refresh hasn't completed within
    max_age_hours (so worker restarts don't re-download every history)."""
    config = load_app_config()
    with session_scope(config.database) as session:
        state = _load_state(session, _DAILY_REFRESH_DATASET, "*")
        if state is None or state.last_run_at is None:
            return True
        return _now_npt_naive() - state.last_run_at > timedelta(hours=max_age_hours)


@activity.defn
async def mark_daily_refresh_done_activity(rows_written: int) -> None:
    _save_state(_DAILY_REFRESH_DATASET, "*", rows_written=rows_written, exhausted=True, last_error=None)


@activity.defn
async def backfill_intraday_ticks_activity(
    symbol: str,
    instrument_type: str,
    source_symbol: str,
    start_date: str,
    timeout: int,
    pause_seconds: float,
    backward: bool,
) -> dict[str, Any]:
    """Intraday ticks for one symbol from merolagani into nepse_intraday_tick,
    in 30-day windows, resuming from research_backfill_state:
      1. forward: from the newest tick already covered up to now;
      2. backward (if `backward`): from the oldest covered tick back to
         start_date, then marked exhausted.
    State is saved after every window, so a retry or the next run picks up
    where this one stopped. With no state and backward=False, only the
    last 2 days are fetched (seeds the forward cursor)."""
    config = load_app_config()
    with session_scope(config.database) as session:
        state = _load_state(session, "intraday", symbol)
        oldest = state.oldest_covered if state else None
        newest = state.newest_covered if state else None
        exhausted = bool(state.exhausted) if state else False
        total = int(state.rows_written) if state else 0

    floor = datetime.combine(date.fromisoformat(start_date), dtime(0, 0))
    now = _now_npt_naive()
    written = 0
    windows = 0

    async def _window(start: datetime, end: datetime) -> int:
        nonlocal windows
        ticks = await asyncio.to_thread(
            fetch_intraday_ticks, source_symbol, start.replace(tzinfo=NPT), end.replace(tzinfo=NPT), timeout
        )
        rows = [{"symbol": symbol, "instrument_type": instrument_type, "source": "merolagani", **t} for t in ticks]
        if rows:
            with session_scope(config.database) as session:
                upsert_intraday_ticks(session, rows)
        windows += 1
        activity.heartbeat({"symbol": symbol, "window_start": start.isoformat()})
        await asyncio.sleep(pause_seconds)
        return len(rows)

    try:
        if newest is None:
            if not backward:
                seed_start = now - timedelta(days=2)
                written += await _window(seed_start, now)
                oldest, newest = seed_start, now
                _save_state("intraday", symbol, oldest_covered=oldest, newest_covered=newest, exhausted=False, rows_written=total + written, last_error=None)
            else:
                oldest = newest = now
        else:
            cursor = newest - timedelta(days=1)
            while cursor < now:
                end = min(cursor + _INTRADAY_WINDOW, now)
                written += await _window(cursor, end)
                newest = end
                # Forward progress only touches newest_covered: a concurrent
                # backward walk (weekly/startup run) owns oldest/exhausted.
                _save_state("intraday", symbol, newest_covered=newest, rows_written=total + written, last_error=None)
                cursor = end

        if backward and not exhausted:
            end = oldest
            while end > floor:
                start = max(end - _INTRADAY_WINDOW, floor)
                written += await _window(start, end)
                oldest = start
                exhausted = start <= floor
                _save_state("intraday", symbol, oldest_covered=oldest, newest_covered=newest, exhausted=exhausted, rows_written=total + written, last_error=None)
                end = start
    except Exception as e:
        _save_state("intraday", symbol, last_error=str(e)[:500])
        raise

    result = {
        "symbol": symbol,
        "rows": written,
        "windows": windows,
        "oldest": oldest.isoformat() if oldest else None,
        "newest": newest.isoformat() if newest else None,
        "exhausted": exhausted,
    }
    activity.logger.info(f"[Research] intraday {result}")
    return result


@activity.defn
async def capture_eod_stock_prices_activity(timeout: int) -> dict[str, Any]:
    """After the close: the official today-price (closePrice is only set
    once the session ends) into nepse_stock_daily for today, with turnover
    and trade counts merolagani doesn't have. Skipped when NEPSE's latest
    session isn't today (holiday)."""
    today = npt_today()
    rows = await asyncio.to_thread(fetch_today_price, timeout=timeout)
    business_date = rows[0].get("businessDate") if rows else None
    if business_date != today.isoformat():
        return {"status": "skipped", "business_date": business_date, "rows": 0}

    records = [
        {
            "symbol": r["symbol"],
            "trade_date": today,
            "security_id": r.get("securityId"),
            "open": r.get("openPrice"),
            "high": r.get("highPrice"),
            "low": r.get("lowPrice"),
            "close": r.get("closePrice") or r.get("lastUpdatedPrice"),
            "volume": r.get("totalTradedQuantity"),
            "turnover": r.get("totalTradedValue"),
            "total_trades": r.get("totalTrades"),
        }
        for r in rows
        if r.get("symbol") and r.get("businessDate") == today.isoformat()
    ]
    config = load_app_config()
    with session_scope(config.database) as session:
        upsert_stock_daily_raw(session, records, source="nepalstock")
    return {"status": "success", "business_date": business_date, "rows": len(records)}


@activity.defn
async def capture_official_index_history_activity(timeout: int, size: int) -> int:
    """The last `size` official daily bars for all 17 indices (the official
    API keeps ~1 year, ~235 sessions) into nepse_index_daily -- the only
    source with share volume and transaction counts. The still-open
    session (closingIndex == 0) is skipped."""
    auth_context = await asyncio.to_thread(fetch_auth_context, timeout)
    records: list[dict[str, Any]] = []
    for i, spec in enumerate(INDEX_REGISTRY):
        if i:
            await asyncio.sleep(0.5)
        rows = await asyncio.to_thread(fetch_index_history, spec.official_id, timeout, size, auth_context)
        for r in rows:
            close = r.get("closingIndex")
            if not close or close <= 0 or not r.get("businessDate"):
                continue
            records.append(
                {
                    "index_name": spec.name,
                    "trade_date": date.fromisoformat(r["businessDate"]),
                    "open": r.get("openIndex"),
                    "high": r.get("highIndex"),
                    "low": r.get("lowIndex"),
                    "close": close,
                    "volume": r.get("turnoverVolume"),
                    "turnover": r.get("turnoverValue"),
                    "total_transactions": r.get("totalTransaction"),
                }
            )
        activity.heartbeat(spec.name)

    config = load_app_config()
    with session_scope(config.database) as session:
        upsert_index_daily(session, records, source="nepalstock")
    activity.logger.info(f"[Research] official index history: {len(records)} bars")
    return len(records)
