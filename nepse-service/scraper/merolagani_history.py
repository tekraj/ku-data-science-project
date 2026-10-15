"""Deep price history from merolagani.com's TradingView chart handler.

    GET https://merolagani.com/handlers/TechnicalChartHandler.ashx
        ?type=get_advanced_chart&symbol=<SYM>&resolution=<R>
        &rangeStartDate=<unix>&rangeEndDate=<unix>&isAdjust=<0|1>&currencyCode=NPR

returns a TradingView UDF payload {"s": "ok"|"no_data", t, o, h, l, c, v}.
No auth, no Cloudflare. Verified against live responses on 2026-10-15:

  - resolution "1D": the whole requested range in one response. NEPSE index
    back to 2000-01-03; sub-indices from 2014-2016; equities from ~2010.
    isAdjust=1 gives bonus/right-adjusted prices (and can start later than
    the raw series). For indices `v` is NPR turnover, for equities shares.
  - resolution "1" (any intraday value behaves the same): intraday point
    observations, back to ~2018 for indices (2018-06 has data, 2017-06 does
    not). Despite the OHLC shape, o == h == l == c on every row and `t`
    carries seconds: indices get ~1 observation a minute, equities one per
    minute with trades -- so they are stored as ticks (price + volume).
  - Daily `t` values are not midnight-aligned (recent bars sit at 20:45
    UTC, old ones at 05:45 UTC), but always fall on the bar's own UTC
    calendar date -- so trade_date = the UTC date of t. Intraday `t` is a
    true epoch timestamp (converted to naive NPT here, matching the rest of
    the database).
  - Symbols: equity tickers, "NEPSE", and the index labels from
    merolagani's Indices.aspx dropdown (see
    nepse_common.constants.index_registry for all 17).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

_CHART_URL = "https://merolagani.com/handlers/TechnicalChartHandler.ashx"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://merolagani.com/",
}

NPT = timezone(timedelta(hours=5, minutes=45))
_EPOCH_START = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _fetch_udf(symbol: str, resolution: str, start: datetime, end: datetime, adjusted: bool, timeout: int) -> dict[str, Any]:
    resp = requests.get(
        _CHART_URL,
        params={
            "type": "get_advanced_chart",
            "symbol": symbol,
            "resolution": resolution,
            "rangeStartDate": int(start.timestamp()),
            "rangeEndDate": int(end.timestamp()),
            "isAdjust": 1 if adjusted else 0,
            "currencyCode": "NPR",
        },
        headers=_HEADERS,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"unexpected merolagani payload for {symbol}: {str(data)[:200]}")
    return data


def _bars(data: dict[str, Any]) -> list[tuple[int, Any, Any, Any, Any, Any]]:
    if data.get("s") != "ok":
        return []
    t = data.get("t") or []
    cols = [data.get(k) or [None] * len(t) for k in ("o", "h", "l", "c", "v")]
    return list(zip(t, *cols))


def fetch_daily_bars(
    symbol: str, adjusted: bool, timeout: int = 60, start: datetime | None = None
) -> list[dict[str, Any]]:
    """Full daily history for `symbol` (or from `start`), oldest first:
    [{trade_date, open, high, low, close, volume}]. The bar for a session
    still in progress is included; callers drop it if they need closes."""
    data = _fetch_udf(symbol, "1D", start or _EPOCH_START, datetime.now(timezone.utc) + timedelta(days=1), adjusted, timeout)
    out = []
    for t, o, h, l, c, v in _bars(data):
        out.append(
            {
                "trade_date": datetime.fromtimestamp(t, timezone.utc).date(),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
        )
    return out


def fetch_intraday_ticks(symbol: str, start: datetime, end: datetime, timeout: int = 60) -> list[dict[str, Any]]:
    """Intraday observations in [start, end] (aware datetimes), oldest
    first: [{tick_time (naive NPT), price, volume}]."""
    data = _fetch_udf(symbol, "1", start, end, True, timeout)
    return [
        {"tick_time": datetime.fromtimestamp(t, NPT).replace(tzinfo=None), "price": c, "volume": v}
        for t, _o, _h, _l, c, v in _bars(data)
        if c is not None
    ]


def npt_today() -> date:
    return datetime.now(NPT).date()
