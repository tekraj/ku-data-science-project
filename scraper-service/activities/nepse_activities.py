from __future__ import annotations

import asyncio
from datetime import datetime, time as dtime
from typing import Any

import pytz
from temporalio import activity

from nepse_common.config import load_app_config
from nepse_common.db.session import session_scope
from nepse_common.models import NepseIndex

from scraper.nepse_scraper import scrape_all_nepse_data

_NST = pytz.timezone("Asia/Kathmandu")


def _now_nst() -> datetime:
    return datetime.now(_NST)


@activity.defn
async def is_market_open_activity() -> bool:
    """Port of old scheduler.py _is_market_open(): True only Mon-Fri
    between 11:00 and 14:59 NPT (market hours)."""
    now = _now_nst()
    if now.weekday() > 4:  # 5=Sat, 6=Sun
        return False
    return dtime(11, 0) <= now.time() < dtime(15, 0)


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
