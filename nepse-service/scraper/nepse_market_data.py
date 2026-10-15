"""Scrapers for the official nepalstock.com.np market-data endpoints:
today's price for all securities, floor sheet, sector summary, per-security
market depth, market status, the official index values/history and the
company list.

Auth is handled by scraper/nepse_wasm_auth.py (see its module docstring for
the full WASM-token mechanism). Endpoint paths come from the open-source
`nepse-scraper` PyPI package's api_dict and
github.com/basic-bgnr/NepseUnofficialApi's API_ENDPOINTS.json. All of them
were verified against live nepalstock.com.np responses on 2026-10-15,
including these behaviours the scrapers depend on:
  - /api/nots/sectorwise only accepts GET (POST -> HTTP 405).
  - /api/nots/nepse-data/floorsheet pages via ?page=N&size=500 and ignores
    businessDate (always the latest session). Broker ids/names are null
    until the 15:00 close.
  - /api/nots/nepse-data/today-price only accepts a businessDate within the
    last few days ("Searched Date is not valid." otherwise), and
    /api/nots/index/history/{id} serves only the last ~1 year -- deep
    history comes from merolagani instead (scraper/merolagani_history.py).
  - /api/nots/nepse-data/market-open returns {"isOpen": "OPEN"|"CLOSE", ...}.
"""
from __future__ import annotations

from typing import Any

import requests

from scraper.nepse_wasm_auth import ROOT_URL, auth_headers, build_payload_id, fetch_auth_context

_TODAY_PRICE_PATH = "/api/nots/nepse-data/today-price"
_SECTORWISE_SUMMARY_PATH = "/api/nots/sectorwise"
_COMPANY_LIST_PATH = "/api/nots/company/list"
_FLOOR_SHEET_PATH = "/api/nots/nepse-data/floorsheet"
_MARKET_DEPTH_PATH = "/api/nots/nepse-data/marketdepth/"  # + "{security_id}/"
_MARKET_OPEN_PATH = "/api/nots/nepse-data/market-open"
_MAIN_INDICES_PATH = "/api/nots/nepse-index"  # NEPSE, Sensitive, Float, Sensitive Float
_SUB_INDICES_PATH = "/api/nots"  # the 13 sector sub-indices
_INDEX_HISTORY_PATH = "/api/nots/index/history/"  # + "{index_id}"

_PAGE_SIZE = 500


def _get_json(
    path: str,
    timeout: int,
    params: dict[str, Any] | None = None,
    auth_context: dict[str, Any] | None = None,
) -> Any:
    auth_context = auth_context or fetch_auth_context(timeout)
    resp = requests.get(
        ROOT_URL + path,
        headers=auth_headers(auth_context),
        params=params,
        timeout=timeout,
        verify=False,  # NEPSE's cert chain is incomplete -- see nepse_wasm_auth.py.
    )
    resp.raise_for_status()
    return resp.json()


def _post_json(
    path: str, timeout: int, params: dict[str, Any] | None = None, which_payload: str | None = None
) -> Any:
    auth_context = fetch_auth_context(timeout)
    payload_id = build_payload_id(auth_context, which=which_payload)
    resp = requests.post(
        ROOT_URL + path,
        headers=auth_headers(auth_context),
        params=params,
        json={"id": payload_id},
        timeout=timeout,
        verify=False,
    )
    resp.raise_for_status()
    return resp.json()


def _content(data: Any) -> list[dict[str, Any]]:
    """Unwrap a Spring pagination envelope ({"content": [...], ...})."""
    if isinstance(data, dict):
        return data.get("content", []) or []
    return data or []


def fetch_today_price(timeout: int = 15) -> list[dict[str, Any]]:
    """Today's price for all listed securities. Paginated per the
    nepse-scraper package's get_today_price (page/size/businessDate
    querystring on a POST); businessDate omitted here to always get the
    current/most-recent trading day. Returns the flat list of security
    rows (unwraps the pagination envelope's "content" key, matching the
    shape used by getCompanyPriceVolumeHistory in NepseUnofficialApi).

    closePrice is null in every row while the session is open; after the
    close it holds the official closing price (NepseEndOfDayWorkflow relies
    on that)."""
    data = _post_json(
        _TODAY_PRICE_PATH,
        timeout,
        params={"page": "0", "size": str(_PAGE_SIZE), "businessDate": None},
    )
    return _content(data)


def fetch_sector_summary(timeout: int = 15) -> list[dict[str, Any]]:
    """Sector-wise turnover/volume/transaction summary for the latest
    session: [{businessDate, sectorName, turnOverValues, turnOverVolume,
    totalTransaction}, ...]. GET only -- a POST (what this used to send)
    returns HTTP 405, which is why nepse_sector_summary stayed empty."""
    return _content(_get_json(_SECTORWISE_SUMMARY_PATH, timeout))


def fetch_market_status(timeout: int = 15) -> dict[str, Any]:
    """{"isOpen": "OPEN"|"CLOSE", "asOf": ..., "id": ...}."""
    return _get_json(_MARKET_OPEN_PATH, timeout)


def fetch_company_list(timeout: int = 15) -> list[dict[str, Any]]:
    """Every listed/suspended/delisted security: [{id, symbol,
    securityName, companyName, sectorName, instrumentType, status, ...}]."""
    return _content(_get_json(_COMPANY_LIST_PATH, timeout, params={"page": "0", "size": str(_PAGE_SIZE)}))


def fetch_security_id_map(timeout: int = 15) -> dict[str, int]:
    """symbol -> internal numeric security id, needed for the per-stock
    market-depth endpoint (e.g. nepalstock.com/marketdepth/9306). Sourced
    from /api/nots/company/list, the same source NepseUnofficialApi's
    getSecurityIDKeyMap uses."""
    return {
        str(row.get("symbol")): row.get("id")
        for row in fetch_company_list(timeout)
        if row.get("symbol") is not None and row.get("id") is not None
    }


def fetch_official_indices(timeout: int = 15) -> list[dict[str, Any]]:
    """Current value of all 17 indices: the 4 headline indices from
    /api/nots/nepse-index plus the 13 sector sub-indices from /api/nots.
    Each row has at least {id, index, currentValue, change, perChange}."""
    auth_context = fetch_auth_context(timeout)
    rows = list(_get_json(_MAIN_INDICES_PATH, timeout, auth_context=auth_context) or [])
    rows.extend(_get_json(_SUB_INDICES_PATH, timeout, auth_context=auth_context) or [])
    return rows


def fetch_index_history(
    index_id: int, timeout: int = 15, size: int = 10, auth_context: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Most recent `size` daily bars for one index, newest first:
    [{businessDate, openIndex, highIndex, lowIndex, closingIndex,
    turnoverValue, turnoverVolume, totalTransaction, ...}]. The current,
    still-open session appears with closingIndex == 0."""
    data = _get_json(
        f"{_INDEX_HISTORY_PATH}{index_id}",
        timeout,
        params={"page": "0", "size": str(size)},
        auth_context=auth_context,
    )
    return _content(data)


def fetch_floor_sheet(timeout: int = 15) -> list[dict[str, Any]]:
    """The most recent _PAGE_SIZE floor-sheet contracts for the current
    session (page 0 only -- the 1-minute intraday scrape). The full day is
    read after the close by FloorSheetPager."""
    data = _post_json(
        _FLOOR_SHEET_PATH,
        timeout,
        params={"size": str(_PAGE_SIZE), "sort": "contractId,desc"},
    )
    return _floor_sheet_rows(data)


def _floor_sheet_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        floorsheets = data.get("floorsheets")
        if isinstance(floorsheets, dict):
            return floorsheets.get("content", []) or []
        return data.get("content", []) or []
    return data or []


class FloorSheetPager:
    """Reads the latest session's floor sheet one page at a time (callers
    pace and heartbeat between pages). One auth context + payload id is
    reused across pages and re-derived once if NEPSE rejects it mid-sweep."""

    def __init__(self, timeout: int = 30) -> None:
        self._timeout = timeout
        self._auth_context, self._payload_id = self._new_auth()

    def _new_auth(self) -> tuple[dict[str, Any], int]:
        ctx = fetch_auth_context(self._timeout)
        return ctx, build_payload_id(ctx)

    def fetch(self, page: int) -> tuple[int, int, list[dict[str, Any]]]:
        """(total_pages, total_trades, rows) for one page."""
        params = {"page": str(page), "size": str(_PAGE_SIZE), "sort": "contractId,desc"}
        for attempt in range(2):
            resp = requests.post(
                ROOT_URL + _FLOOR_SHEET_PATH,
                headers=auth_headers(self._auth_context),
                params=params,
                json={"id": self._payload_id},
                timeout=self._timeout,
                verify=False,
            )
            if resp.status_code in (401, 403) and attempt == 0:
                self._auth_context, self._payload_id = self._new_auth()
                continue
            resp.raise_for_status()
            break
        data = resp.json()
        floorsheets = data.get("floorsheets") if isinstance(data, dict) else None
        total_pages = int(floorsheets.get("totalPages") or 0) if isinstance(floorsheets, dict) else 0
        total_trades = int((data.get("totalTrades") if isinstance(data, dict) else 0) or 0)
        return total_pages, total_trades, _floor_sheet_rows(data)


def fetch_market_depth(
    security_id: int, timeout: int = 15, auth_context: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Bid/ask order-book ladder for one security: {symbol, totalBuyQty,
    totalSellQty, marketDepth: {buyMarketDepthList, sellMarketDepthList}}."""
    return _get_json(f"{_MARKET_DEPTH_PATH}{security_id}/", timeout, auth_context=auth_context)
