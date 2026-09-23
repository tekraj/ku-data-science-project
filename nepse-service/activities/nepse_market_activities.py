from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from temporalio import activity

from nepse_common.config import load_app_config
from nepse_common.db.session import session_scope
from nepse_common.models import NepseFloorsheet, NepseMarketDepth, NepseSectorSummary, NepseTodayPrice

from scraper.nepse_market_data import (
    fetch_floor_sheet,
    fetch_market_depth,
    fetch_security_id_map,
    fetch_sector_summary,
    fetch_today_price,
)

# Gap between consecutive per-security market-depth fetches within one
# batch, so a single tick still makes one request at a time against
# nepalstock.com.np rather than bursting -- same pacing pattern as
# _BATCH_ITEM_PAUSE_SECONDS in historical_sitemap_backfill_activities.py /
# historical_sitemap_backfill_workflow.py (news-service). Kept here as the
# constant the workflow sleeps by, rather than inside the activity itself,
# since Temporal workflow code (not activity code) must own any sleeping so
# it replays deterministically.
MARKET_DEPTH_BATCH_ITEM_PAUSE_SECONDS = 2

# Each market-data tick fires every minute (see register_schedules.py); a
# full run across ~250+ listed securities at 2s/request would take too long
# to safely fit in a tick, so market depth is scraped in bounded batches
# across successive ticks rather than all-at-once. This keeps each tick's
# activity duration predictable and avoids hammering nepalstock.com.np.
MARKET_DEPTH_BATCH_SIZE = 25


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
    write_nepse_index_activity (every tick is a legitimately new row)."""
    if not rows:
        return 0

    config = load_app_config()
    records = []
    for r in rows:
        if not r.get("symbol"):
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
                "business_date": r.get("businessDate"),
            }
        )
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
    """Plain insert, no dedup -- same timeseries rationale as today-price."""
    if not rows:
        return 0

    config = load_app_config()
    records = [
        {
            "sector_name": r.get("sectorName") or r.get("sector"),
            "total_turnover": r.get("turnover") or r.get("totalTurnover"),
            "total_trade_quantity": r.get("shareVolume") or r.get("totalTradeQuantity"),
            "total_transactions": r.get("totalTransactions") or r.get("transactions"),
            "total_scrips_traded": r.get("totalScripsTraded") or r.get("scripsTraded"),
            "business_date": r.get("businessDate"),
        }
        for r in rows
        if (r.get("sectorName") or r.get("sector"))
    ]
    if not records:
        return 0

    with session_scope(config.database) as session:
        session.execute(NepseSectorSummary.__table__.insert(), records)

    activity.logger.info(f"[DB] Saved {len(records)} sector-summary records.")
    return len(records)


@activity.defn
async def scrape_floor_sheet_activity(timeout: int) -> list[dict[str, Any]]:
    """Fetches all floor-sheet trade contracts for the current session.
    UNVERIFIED endpoint path -- see scraper/nepse_market_data.py module
    docstring. Failures here should be caught by the calling workflow and
    logged/skipped rather than crashing the worker, same as the rest of
    this codebase's market-hours-gated scrapes."""
    return await asyncio.to_thread(fetch_floor_sheet, timeout=timeout)


@activity.defn
async def write_floor_sheet_activity(rows: list[dict[str, Any]]) -> int:
    """Dedup by (contract_id, business_date) via ON CONFLICT DO NOTHING --
    floor-sheet rows have a real natural key (unlike today-price/market-
    depth snapshots), and a tick re-fetching overlapping rows shouldn't
    insert duplicates. Mirrors write_articles_activity's URL-dedup pattern."""
    if not rows:
        return 0

    config = load_app_config()
    records = [
        {
            "contract_id": r.get("contractId"),
            "symbol": r.get("stockSymbol") or r.get("symbol"),
            "buyer_broker_name": r.get("buyerBrokerName"),
            "seller_broker_name": r.get("sellerBrokerName"),
            "contract_quantity": r.get("contractQuantity"),
            "contract_rate": r.get("contractRate"),
            "contract_amount": r.get("contractAmount"),
            "business_date": r.get("businessDate"),
            "trade_time": r.get("tradeTime"),
        }
        for r in rows
        if r.get("contractId") is not None and (r.get("stockSymbol") or r.get("symbol"))
    ]
    if not records:
        return 0

    with session_scope(config.database) as session:
        stmt = (
            pg_insert(NepseFloorsheet)
            .values(records)
            .on_conflict_do_nothing(index_elements=["contract_id", "business_date"])
            .returning(NepseFloorsheet.id)
        )
        result = session.execute(stmt)
        inserted = len(result.fetchall())

    activity.logger.info(f"[DB] Inserted {inserted} new floor-sheet records.")
    return inserted


@activity.defn
async def get_security_ids_activity(timeout: int) -> list[dict[str, Any]]:
    """Returns [{symbol, security_id}, ...] for all listed securities, the
    ID list market-depth scraping iterates over. Sourced from
    /api/nots/company/list (see scraper/nepse_market_data.py)."""
    symbol_map = await asyncio.to_thread(fetch_security_id_map, timeout=timeout)
    return [{"symbol": symbol, "security_id": sec_id} for symbol, sec_id in symbol_map.items()]


@activity.defn
async def scrape_market_depth_for_security_activity(
    security_id: int, symbol: str, timeout: int
) -> dict[str, Any] | None:
    """Fetches the bid/ask ladder for ONE security. Split into a
    per-security activity (rather than looping inside a single activity
    call) so the calling workflow can pace consecutive calls with
    workflow.sleep between them -- activities themselves must not sleep for
    pacing purposes, only workflow code may, for deterministic replay.
    UNVERIFIED endpoint path -- see scraper/nepse_market_data.py module
    docstring."""
    depth = await asyncio.to_thread(fetch_market_depth, security_id, timeout=timeout)
    if depth is None:
        return None
    return {"security_id": security_id, "symbol": symbol, "depth": depth}


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
