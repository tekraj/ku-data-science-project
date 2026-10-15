from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, time as dtime
from typing import Any

import pytz
from sqlalchemy import select
from temporalio import activity

from nepse_common.config import load_app_config
from nepse_common.db.session import session_scope
from nepse_common.models import NepseIndex, NepseTodayPrice

from scraper.nepse_market_data import fetch_market_status
from scraper.nepse_scraper import scrape_all_nepse_data

_NST = pytz.timezone("Asia/Kathmandu")

# All five 1-minute market workflows call is_market_open_activity on the
# same tick; cache the official status briefly so that's one
# nepalstock.com.np round-trip per minute, not five.
_STATUS_CACHE_SECONDS = 20
_status_cache: tuple[float, str] | None = None


def _now_nst() -> datetime:
    return datetime.now(_NST)


def _official_market_status(timeout: int = 10) -> str:
    global _status_cache
    now = time.monotonic()
    if _status_cache is not None and now - _status_cache[0] < _STATUS_CACHE_SECONDS:
        return _status_cache[1]
    status = str(fetch_market_status(timeout).get("isOpen") or "").strip().upper()
    _status_cache = (now, status)
    return status


def _traded_today(today: date) -> bool:
    """True once any today-price snapshot for today's business date exists
    -- i.e. today really was a trading session, not a holiday."""
    config = load_app_config()
    with session_scope(config.database) as session:
        row = session.execute(
            select(NepseTodayPrice.id)
            .where(NepseTodayPrice.scraped_at >= datetime.combine(today, dtime(0, 0)))
            .where(NepseTodayPrice.business_date == today.isoformat())
            .limit(1)
        ).first()
        return row is not None


@activity.defn
async def is_market_open_activity(require_open_status: bool = False) -> bool:
    """True only Mon-Fri between 10:55 and 15:05 NPT on actual trading days.

    The window is widened from the 11:00-14:59 core session so a tick lands
    just after the close and captures the closing prints (padding only --
    it does not change when NEPSE itself opens or closes).

    Inside the window, NEPSE's own market-open status decides, so public
    holidays are skipped. A clock-only gate used to let every scraper run on
    holidays (2026-09-21 and 09-25), storing hundreds of flat index ticks and
    ~170k today-price rows that repeated the previous session. During the
    post-close padding (status already "CLOSE") the tick is allowed only if
    today's session was actually seen. If the status call itself fails, fall
    back to the clock (writers also drop rows whose businessDate isn't
    today), so an API hiccup can't silently stop collection.

    require_open_status=True drops the padding: only an "OPEN" status
    passes. Used by market depth, whose endpoint errors outside the
    continuous session (it failed every day at 10:55-10:59 and 15:00-15:04)
    and has no closing print to capture."""
    now = _now_nst()
    if now.weekday() > 4:  # 5=Sat, 6=Sun
        return False
    if not (dtime(10, 55) <= now.time() <= dtime(15, 5)):
        return False

    try:
        status = await asyncio.to_thread(_official_market_status)
    except Exception as e:  # noqa: BLE001 - degrade to the clock gate
        activity.logger.warning(f"[MarketOpen] official status unavailable, using clock gate: {e}")
        return True

    if "OPEN" in status and "CLOSE" not in status:
        return True
    if not require_open_status and now.time() >= dtime(14, 59):
        return await asyncio.to_thread(_traded_today, now.date())
    return False


@activity.defn
async def scrape_nepse_index_activity(timeout: int) -> dict[str, Any]:
    """Calls scraper.nepse_scraper.scrape_all_nepse_data() unchanged.

    The old code already returns plain dicts/strings (nepse_index and each
    sector_indices entry are plain dicts with str/float/None values, and
    scraped_at/source fields are strings), so the result is directly
    JSON-serializable as-is. We do NOT additionally validate the nested
    index dicts through ScrapedIndexPoint here -- that normalization
    (index/index_name key mismatch) is deferred to write_nepse_index_activity
    and to parse_and_write_csv_activity, which are the actual DB-insertion
    boundaries where the index_name field is required.

    scrape_all_nepse_data is synchronous (blocking requests.get()/post())
    -- run it via asyncio.to_thread so it can't freeze the shared asyncio
    event loop (see the matching note on scrape_historical_day_activity).
    """
    return await asyncio.to_thread(scrape_all_nepse_data, timeout=timeout)


@activity.defn
async def write_nepse_index_activity(index_data: dict[str, Any]) -> int:
    """Replicates old db/writer.py write_nepse_index(): a plain insert with
    no dedup, for both the main NEPSE index and sector indices. Only rows
    with a truthy value are written, matching old behavior exactly."""
    config = load_app_config()

    records: list[dict[str, Any]] = []

    main = index_data.get("nepse_index")
    if main and main.get("value"):
        records.append(
            {
                "index_name": main.get("index", "NEPSE"),
                "value": main.get("value"),
                "change": main.get("change"),
                "percent_change": main.get("percent_change"),
            }
        )

    for sector in index_data.get("sector_indices", []) or []:
        if sector.get("value"):
            records.append(
                {
                    "index_name": sector.get("index"),
                    "value": sector.get("value"),
                    "change": sector.get("change"),
                    "percent_change": sector.get("percent_change"),
                }
            )

    if not records:
        activity.logger.info("[DB] No NEPSE index data to save.")
        return 0

    with session_scope(config.database) as session:
        session.execute(NepseIndex.__table__.insert(), records)

    activity.logger.info(f"[DB] Saved {len(records)} NEPSE index records.")
    return len(records)
