from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from temporalio import activity

from nepse_common.config import load_app_config
from nepse_common.db.session import session_scope
from nepse_common.models import (
    NepseFloorsheet,
    NepseIndexDaily,
    NepseMarketDepth,
    NepseSectorSummary,
    NepseStockDaily,
    NepseTodayPrice,
    ResearchBackfillState,
)

from scraper.merolagani_floorsheet import FloorSheetHistory
from scraper.merolagani_history import npt_today
from scraper.nepse_market_data import (
    FloorSheetPager,
    fetch_floor_sheet,
    fetch_market_depth,
    fetch_security_id_map,
    fetch_sector_summary,
    fetch_today_price,
)
from scraper.nepse_wasm_auth import fetch_auth_context

# Pause between consecutive per-security market-depth requests inside one
# batch, so a tick makes one request at a time against nepalstock.com.np
# rather than bursting. A batch of MARKET_DEPTH_BATCH_SIZE (config) at ~1s
# request + this pause fits inside the 1-minute tick.
MARKET_DEPTH_ITEM_PAUSE_SECONDS = 1.0

# Pause between floor-sheet pages during the post-close full sweep
# (~40-130 pages of 500 contracts per day).
FLOOR_SHEET_PAGE_PAUSE_SECONDS = 1.0

# A past session counts as complete once this share of merolagani's listed
# trades carry broker ids in nepse_floorsheet: its server-side paging
# repeats/skips a few dozen rows per day (~0.08% on 2026-10-12, which ended
# with more trades stored than NEPSE's official transaction count), so an
# exact match would re-download complete days every week.
_FLOOR_SHEET_COMPLETE_RATIO = 0.998
_FLOOR_SHEET_HISTORY_DATASET = "floorsheet_history"

# Broker names (NEPSE publishes them only in post-close sweeps) are attached
# to backfilled trades only for sessions this recent: broker numbers are
# stable, but firms rename and merge, so today's name for a number may be
# wrong for 2020. Older sessions keep the member id only.
_BROKER_NAME_MAX_AGE_DAYS = 90
_BROKER_NAME_CACHE_SECONDS = 3600
_broker_name_cache: tuple[float, dict[int, str]] | None = None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


@activity.defn
async def scrape_today_price_activity(timeout: int) -> list[dict[str, Any]]:
    """Fetches today's price for all listed securities from
    nepalstock.com.np. Blocking requests calls run via asyncio.to_thread so
    they can't freeze the shared asyncio event loop (see the matching note
    on scrape_nepse_index_activity in the old nepse_activities.py)."""
    return await asyncio.to_thread(fetch_today_price, timeout=timeout)


@activity.defn
async def write_today_price_activity(rows: list[dict[str, Any]]) -> int:
    """Plain insert, no dedup -- timeseries snapshot, same rationale as
    write_nepse_index_activity (every tick is a legitimately new row).

    Rows whose businessDate isn't today are dropped: on a market holiday
    NEPSE keeps serving the previous session's prices, which were being
    stored as if they were today's (2026-09-21 / 09-25)."""
    if not rows:
        return 0

    today = npt_today().isoformat()
    config = load_app_config()
    records = []
    stale = 0
    for r in rows:
        if not r.get("symbol"):
            continue
        if r.get("businessDate") != today:
            stale += 1
            continue

        ltp = r.get("lastUpdatedPrice")
        previous_close = r.get("previousDayClosePrice")
        percent_change = None
        if ltp is not None and previous_close not in (None, 0):
            percent_change = ((ltp - previous_close) / previous_close) * 100.0

        records.append(
            {
                "security_id": r.get("securityId"),
                "symbol": r.get("symbol"),
                "security_name": r.get("securityName"),
                "open_price": r.get("openPrice"),
                "high_price": r.get("highPrice"),
                "low_price": r.get("lowPrice"),
                "close_price": r.get("closePrice"),
                "previous_close": previous_close,
                "ltp": ltp,
                "percent_change": percent_change,
                "total_trade_quantity": r.get("totalTradedQuantity"),
                "total_trade_value": r.get("totalTradedValue"),
                "total_trades": r.get("totalTrades"),
                "average_traded_price": r.get("averageTradedPrice"),
                "last_updated_time": _parse_dt(r.get("lastUpdatedTime")),
                "business_date": r.get("businessDate"),
            }
        )
    if stale:
        activity.logger.info(f"[DB] Dropped {stale} today-price rows not dated {today}.")
    if not records:
        return 0

    with session_scope(config.database) as session:
        session.execute(NepseTodayPrice.__table__.insert(), records)

    activity.logger.info(f"[DB] Saved {len(records)} today-price records.")
    return len(records)


@activity.defn
async def scrape_sector_summary_activity(timeout: int) -> list[dict[str, Any]]:
    """Fetches the sector-wise turnover/volume/transaction summary."""
    return await asyncio.to_thread(fetch_sector_summary, timeout=timeout)


@activity.defn
async def write_sector_summary_activity(rows: list[dict[str, Any]]) -> int:
    """Plain insert, no dedup -- same timeseries rationale as today-price.
    Field names are the ones /api/nots/sectorwise actually returns
    (turnOverValues / turnOverVolume / totalTransaction); sectors with no
    session today (NEPSE pads the list with "1970-01-01" placeholders) and
    holiday responses are dropped by the businessDate check."""
    if not rows:
        return 0

    today = npt_today().isoformat()
    config = load_app_config()
    records = [
        {
            "sector_name": r.get("sectorName") or r.get("sector"),
            "total_turnover": r.get("turnOverValues", r.get("totalTurnover")),
            "total_trade_quantity": r.get("turnOverVolume", r.get("totalTradeQuantity")),
            "total_transactions": r.get("totalTransaction", r.get("totalTransactions")),
            "total_scrips_traded": r.get("totalScripsTraded"),
            "business_date": r.get("businessDate"),
        }
        for r in rows
        if (r.get("sectorName") or r.get("sector")) and r.get("businessDate") == today
    ]
    if not records:
        return 0

    with session_scope(config.database) as session:
        session.execute(NepseSectorSummary.__table__.insert(), records)

    activity.logger.info(f"[DB] Saved {len(records)} sector-summary records.")
    return len(records)


@activity.defn
async def scrape_floor_sheet_activity(timeout: int) -> list[dict[str, Any]]:
    """Fetches the latest 500 floor-sheet trade contracts for the current
    session. Failures here are caught by the calling workflow and logged
    rather than crashing the worker, same as the rest of this codebase's
    market-hours-gated scrapes."""
    return await asyncio.to_thread(fetch_floor_sheet, timeout=timeout)


def _floor_sheet_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[int, Any], dict[str, Any]] = {}
    for r in rows:
        contract_id = _to_int(r.get("contractId"))
        symbol = r.get("stockSymbol") or r.get("symbol")
        if contract_id is None or not symbol:
            continue
        by_key[(contract_id, r.get("businessDate"))] = {
            "contract_id": contract_id,
            "symbol": symbol,
            "stock_id": _to_int(r.get("stockId")),
            "trade_book_id": _to_int(r.get("tradeBookId")),
            "buyer_member_id": _to_int(r.get("buyerMemberId")),
            "seller_member_id": _to_int(r.get("sellerMemberId")),
            "buyer_broker_name": r.get("buyerBrokerName") or None,
            "seller_broker_name": r.get("sellerBrokerName") or None,
            "contract_quantity": r.get("contractQuantity"),
            "contract_rate": r.get("contractRate"),
            "contract_amount": r.get("contractAmount"),
            "business_date": r.get("businessDate"),
            "trade_time": r.get("tradeTime"),
        }
    return list(by_key.values())


def _upsert_floor_sheet(session, records: list[dict[str, Any]]) -> tuple[int, int]:
    """Insert new contracts; for contracts already stored, fill in broker
    ids/names (and stock/trade-book ids) that were NULL when the row was
    first written during the session. Rows that gain nothing are left
    untouched. Returns (inserted, updated)."""
    if not records:
        return 0, 0

    table = NepseFloorsheet.__table__
    fill_cols = ("stock_id", "trade_book_id", "buyer_member_id", "seller_member_id", "buyer_broker_name", "seller_broker_name")
    stmt = pg_insert(table).values(records)
    stmt = stmt.on_conflict_do_update(
        index_elements=["contract_id", "business_date"],
        set_={c: func.coalesce(table.c[c], getattr(stmt.excluded, c)) for c in fill_cols},
        where=or_(*[table.c[c].is_(None) & getattr(stmt.excluded, c).isnot(None) for c in fill_cols]),
    ).returning(literal_column("(xmax = 0)"))
    flags = [row[0] for row in session.execute(stmt).fetchall()]
    inserted = sum(1 for f in flags if f)
    return inserted, len(flags) - inserted


@activity.defn
async def write_floor_sheet_activity(rows: list[dict[str, Any]]) -> int:
    """Upsert on (contract_id, business_date) -- floor-sheet rows have a
    real natural key, so a tick re-fetching overlapping rows never inserts
    duplicates, and a later fetch that carries broker info fills it in.
    Returns the number of newly inserted contracts."""
    records = _floor_sheet_records(rows)
    if not records:
        return 0

    config = load_app_config()
    with session_scope(config.database) as session:
        inserted, updated = _upsert_floor_sheet(session, records)

    activity.logger.info(f"[DB] Inserted {inserted} new floor-sheet records ({updated} filled in).")
    return inserted


@activity.defn
async def sweep_floor_sheet_activity(timeout: int) -> dict[str, Any]:
    """After the close: page through the whole session's floor sheet
    (~40-130 pages), inserting every contract the 500-per-minute intraday
    scrape missed and filling in broker member ids/names, which NEPSE only
    publishes once the market has closed. Writes page by page so no large
    payload crosses the Temporal boundary. Skips (and reports) a sheet
    whose businessDate isn't today -- i.e. a holiday."""
    today = npt_today().isoformat()
    config = load_app_config()

    pager = await asyncio.to_thread(FloorSheetPager, timeout)
    page, total_pages, total_trades = 0, 1, 0
    inserted = updated = seen = with_broker = 0
    business_date = None
    while page < total_pages:
        total_pages, total_trades, rows = await asyncio.to_thread(pager.fetch, page)
        if page == 0:
            business_date = rows[0].get("businessDate") if rows else None
            if business_date != today:
                return {"status": "skipped", "business_date": business_date, "total_trades": total_trades}

        records = _floor_sheet_records([r for r in rows if r.get("businessDate") == today])
        seen += len(records)
        with_broker += sum(1 for r in records if r["buyer_member_id"] is not None or r["buyer_broker_name"])
        with session_scope(config.database) as session:
            page_inserted, page_updated = _upsert_floor_sheet(session, records)
        inserted += page_inserted
        updated += page_updated

        activity.heartbeat(page)
        page += 1
        if page < total_pages:
            await asyncio.sleep(FLOOR_SHEET_PAGE_PAUSE_SECONDS)

    with session_scope(config.database) as session:
        stored = session.execute(
            select(func.count()).select_from(NepseFloorsheet).where(NepseFloorsheet.business_date == today)
        ).scalar_one()

    result = {
        "status": "success",
        "business_date": business_date,
        "pages": total_pages,
        "total_trades": total_trades,
        "seen": seen,
        "with_broker": with_broker,
        "inserted": inserted,
        "updated": updated,
        "stored": stored,
    }
    activity.logger.info(f"[FloorSheetSweep] {result}")
    return result


@activity.defn
async def list_trading_days_activity(start_date: str, end_date: str) -> list[str]:
    """NEPSE sessions in [start_date, end_date] (ISO dates), oldest first,
    from the trading calendar in nepse_index_daily."""
    config = load_app_config()
    with session_scope(config.database) as session:
        days = session.execute(
            select(NepseIndexDaily.trade_date)
            .where(
                NepseIndexDaily.index_name == "NEPSE",
                NepseIndexDaily.trade_date >= date.fromisoformat(start_date),
                NepseIndexDaily.trade_date <= date.fromisoformat(end_date),
            )
            .order_by(NepseIndexDaily.trade_date)
        ).scalars()
        return [d.isoformat() for d in days]


def _broker_names(session) -> dict[int, str]:
    """member id -> broker name, learned from the last 30 days of post-close
    sweeps (NEPSE publishes both); merolagani's history only has the
    numbers. Cached per process -- this runs once per backfilled session."""
    global _broker_name_cache
    now = time.monotonic()
    if _broker_name_cache is not None and now - _broker_name_cache[0] < _BROKER_NAME_CACHE_SECONDS:
        return _broker_name_cache[1]

    since = (npt_today() - timedelta(days=30)).isoformat()
    names: dict[int, str] = {}
    for member_col, name_col in (
        (NepseFloorsheet.buyer_member_id, NepseFloorsheet.buyer_broker_name),
        (NepseFloorsheet.seller_member_id, NepseFloorsheet.seller_broker_name),
    ):
        rows = session.execute(
            select(member_col, name_col)
            .where(NepseFloorsheet.business_date >= since, member_col.isnot(None), name_col.isnot(None))
            .distinct()
        ).all()
        names.update({member_id: name for member_id, name in rows})
    _broker_name_cache = (now, names)
    return names


@activity.defn
async def backfill_floor_sheet_day_activity(day_iso: str, timeout: int, pause_seconds: float) -> dict[str, Any]:
    """Completes one past session in nepse_floorsheet from merolagani's
    floor-sheet history: fills buyer/seller broker ids (and, for sessions
    within _BROKER_NAME_MAX_AGE_DAYS, names known from post-close sweeps)
    on stored contracts and inserts
    the contracts the 500-per-minute intraday scrape missed (those get no
    trade_time -- merolagani doesn't publish it). merolagani lists equities
    only, so mutual-fund/debenture trades keep NULL broker ids. Skips a day
    already filled by this activity (research_backfill_state) or whose
    stored broker-id coverage is >= _FLOOR_SHEET_COMPLETE_RATIO of
    merolagani's total. Resumes from the last heartbeated page on retry."""
    day = date.fromisoformat(day_iso)
    config = load_app_config()
    with session_scope(config.database) as session:
        done = session.execute(
            select(ResearchBackfillState.exhausted).where(
                ResearchBackfillState.dataset == _FLOOR_SHEET_HISTORY_DATASET,
                ResearchBackfillState.symbol == day_iso,
            )
        ).scalar_one_or_none()
        if done:
            return {"day": day_iso, "status": "complete", "total": None}
        with_broker = session.execute(
            select(func.count())
            .select_from(NepseFloorsheet)
            .where(NepseFloorsheet.business_date == day_iso, NepseFloorsheet.buyer_member_id.isnot(None))
        ).scalar_one()
        recent = (npt_today() - day).days <= _BROKER_NAME_MAX_AGE_DAYS
        names = _broker_names(session) if recent else {}

    history = FloorSheetHistory(timeout)
    total, total_pages, rows = await asyncio.to_thread(history.open, day)
    if total == 0:
        return {"day": day_iso, "status": "no data", "total": 0}
    if with_broker >= total * _FLOOR_SHEET_COMPLETE_RATIO:
        return {"day": day_iso, "status": "complete", "total": total, "stored_with_broker": with_broker}

    details = activity.info().heartbeat_details
    page = int(details[0]) if details else 1
    if page > 1:
        _, _, rows = await asyncio.to_thread(history.page, page)

    inserted = updated = 0
    while True:
        by_contract = {
            r["contract_id"]: {
                **r,
                "stock_id": None,
                "trade_book_id": None,
                "buyer_broker_name": names.get(r["buyer_member_id"]),
                "seller_broker_name": names.get(r["seller_member_id"]),
                "business_date": day_iso,
                "trade_time": None,
            }
            for r in rows
        }
        with session_scope(config.database) as session:
            page_inserted, page_updated = _upsert_floor_sheet(session, list(by_contract.values()))
        inserted += page_inserted
        updated += page_updated
        activity.heartbeat(page + 1)

        page += 1
        if page > total_pages:
            break
        await asyncio.sleep(pause_seconds)
        _, total_pages, rows = await asyncio.to_thread(history.page, page)

    with session_scope(config.database) as session:
        stored, stored_with_broker = session.execute(
            select(func.count(), func.count(NepseFloorsheet.buyer_member_id)).where(NepseFloorsheet.business_date == day_iso)
        ).one()
        state = pg_insert(ResearchBackfillState.__table__).values(
            dataset=_FLOOR_SHEET_HISTORY_DATASET, symbol=day_iso, exhausted=True, rows_written=inserted + updated
        )
        session.execute(
            state.on_conflict_do_update(
                index_elements=["dataset", "symbol"],
                set_={"exhausted": True, "rows_written": state.excluded.rows_written, "last_run_at": func.now()},
            )
        )
    result = {
        "day": day_iso,
        "status": "filled",
        "total": total,
        "pages": total_pages,
        "inserted": inserted,
        "updated": updated,
        "stored": stored,
        "stored_with_broker": stored_with_broker,
    }
    activity.logger.info(f"[FloorSheetHistory] {result}")
    return result


def _liquid_symbols(session, top_n: int) -> list[str]:
    """Most liquid symbols by turnover on the latest session with official
    EOD data in nepse_stock_daily; before that exists, by peak intraday
    turnover over the last week of today-price snapshots."""
    latest = session.execute(
        select(func.max(NepseStockDaily.trade_date)).where(
            NepseStockDaily.source == "nepalstock", NepseStockDaily.turnover.isnot(None)
        )
    ).scalar_one_or_none()
    if latest is not None:
        return list(
            session.execute(
                select(NepseStockDaily.symbol)
                .where(NepseStockDaily.trade_date == latest, NepseStockDaily.turnover.isnot(None))
                .order_by(NepseStockDaily.turnover.desc())
                .limit(top_n)
            ).scalars()
        )

    peak = func.max(NepseTodayPrice.total_trade_value)
    return list(
        session.execute(
            select(NepseTodayPrice.symbol)
            .where(NepseTodayPrice.scraped_at >= datetime.combine(date.today() - timedelta(days=7), datetime.min.time()))
            .group_by(NepseTodayPrice.symbol)
            .order_by(peak.desc().nulls_last())
            .limit(top_n)
        ).scalars()
    )


@activity.defn
async def get_market_depth_universe_activity(timeout: int, top_n: int) -> list[dict[str, Any]]:
    """[{symbol, security_id}, ...] the market-depth rotation walks: the
    top_n most liquid securities (0 = every listed security). Walking all
    ~650 listed securities (most of them debentures, mutual funds and
    illiquid scrips with empty books) meant each one was refreshed only
    about every 26 minutes."""
    symbol_map = await asyncio.to_thread(fetch_security_id_map, timeout=timeout)
    if top_n > 0:
        config = load_app_config()
        with session_scope(config.database) as session:
            liquid = _liquid_symbols(session, top_n)
        universe = [{"symbol": s, "security_id": symbol_map[s]} for s in liquid if s in symbol_map]
        if universe:
            return universe
    return [{"symbol": symbol, "security_id": sec_id} for symbol, sec_id in symbol_map.items()]


@activity.defn
async def scrape_market_depth_batch_activity(
    securities: list[dict[str, Any]], timeout: int
) -> list[dict[str, Any]]:
    """Fetches the bid/ask ladder for each security in the batch, one at a
    time, MARKET_DEPTH_ITEM_PAUSE_SECONDS apart, reusing one auth context
    for the whole batch (the old per-security activity re-authenticated on
    every request, doubling the request count). A failure on one security
    is logged and skipped, not fatal to the batch."""
    auth_context = await asyncio.to_thread(fetch_auth_context, timeout)
    entries: list[dict[str, Any]] = []
    failures = 0
    for i, security in enumerate(securities):
        if i > 0:
            await asyncio.sleep(MARKET_DEPTH_ITEM_PAUSE_SECONDS)
        activity.heartbeat(i)
        try:
            depth = await asyncio.to_thread(fetch_market_depth, security["security_id"], timeout, auth_context)
        except Exception as e:  # noqa: BLE001 - one bad security must not sink the batch
            failures += 1
            activity.logger.warning(f"[MarketDepth] {security['symbol']}: {e}")
            continue
        if depth is not None:
            entries.append({"security_id": security["security_id"], "symbol": security["symbol"], "depth": depth})
    if failures and not entries:
        raise RuntimeError(f"market depth failed for all {failures} securities in batch")
    return entries


@activity.defn
async def write_market_depth_activity(entries: list[dict[str, Any]]) -> int:
    """Plain insert, no dedup -- same timeseries rationale as today-price.
    Each entry's `depth` is the raw nepalstock.com.np market-depth response
    ({symbol, totalBuyQty, totalSellQty, marketDepth: {buyMarketDepthList,
    sellMarketDepthList}}); buy/sell ladders are stored as JSONB as-is
    rather than normalized into a separate levels table (see
    NepseMarketDepth model docstring)."""
    if not entries:
        return 0

    config = load_app_config()
    records: list[dict[str, Any]] = []
    for entry in entries:
        depth = entry.get("depth") or {}
        market_depth = depth.get("marketDepth") or {}
        records.append(
            {
                "security_id": entry["security_id"],
                "symbol": entry["symbol"],
                "total_buy_qty": depth.get("totalBuyQty"),
                "total_sell_qty": depth.get("totalSellQty"),
                "buy_levels": market_depth.get("buyMarketDepthList"),
                "sell_levels": market_depth.get("sellMarketDepthList"),
            }
        )

    with session_scope(config.database) as session:
        session.execute(NepseMarketDepth.__table__.insert(), records)

    activity.logger.info(f"[DB] Saved {len(records)} market-depth records.")
    return len(records)
