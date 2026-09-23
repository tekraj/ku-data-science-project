"""Scrapers for the 4 official nepalstock.com.np market-data endpoints:
today's price for all securities, floor sheet, sector summary, and
per-security market depth.

Auth is handled by scraper/nepse_wasm_auth.py (see its module docstring for
the full WASM-token mechanism). Endpoint paths below come from two
independent sources that agree with each other:
  - the open-source `nepse-scraper` PyPI package's api_dict (today-price,
    sectorwise summary, company list) -- see nepse_wasm_auth.py docstring.
  - github.com/basic-bgnr/NepseUnofficialApi's API_ENDPOINTS.json, which
    additionally covers floor sheet and market depth:
        "floor_sheet":   "/api/nots/nepse-data/floorsheet"
        "market-depth":  "/api/nots/nepse-data/marketdepth/"  (append id + "/")
        "todays_price":  "/api/nots/nepse-data/today-price"
        "company_list_url": "/api/nots/company/list"
    These two paths (floor sheet, market depth) could NOT be verified with
    a real live call against nepalstock.com.np from this environment --
    outbound connections complete a TLS handshake and open an HTTP/2 stream
    but then hang/reset before any response body arrives (same failure mode
    reported by whoever did the initial research pass here). Today-price
    and sector-summary paths match the nepse-scraper package's own api_dict
    exactly, which IS independently corroborated, so confidence there is
    higher. Treat floor-sheet and market-depth paths as UNVERIFIED until
    someone with working network access to nepalstock.com.np confirms them.
"""
from __future__ import annotations

from typing import Any

import requests

from scraper.nepse_wasm_auth import ROOT_URL, auth_headers, build_payload_id, fetch_auth_context

_TODAY_PRICE_PATH = "/api/nots/nepse-data/today-price"
_SECTORWISE_SUMMARY_PATH = "/api/nots/sectorwise"
_COMPANY_LIST_PATH = "/api/nots/company/list"

# UNVERIFIED -- see module docstring. Sourced from
# NepseUnofficialApi/nepse/data/API_ENDPOINTS.json ("floor_sheet",
# "market-depth"), corroborated by surajrimal07/NepseAPI-Unofficial's
# /Floorsheet and /MarketDepth FastAPI routes calling equivalent upstream
# paths, but not confirmed with an actual live 200 response from this
# environment.
_FLOOR_SHEET_PATH = "/api/nots/nepse-data/floorsheet"
_MARKET_DEPTH_PATH = "/api/nots/nepse-data/marketdepth/"  # + "{security_id}/"

_PAGE_SIZE = 500


def _get_json(path: str, timeout: int, params: dict[str, Any] | None = None) -> Any:
    auth_context = fetch_auth_context(timeout)
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


def fetch_today_price(timeout: int = 15) -> list[dict[str, Any]]:
    """Today's price for all listed securities. Paginated per the
    nepse-scraper package's get_today_price (page/size/businessDate
    querystring on a POST); businessDate omitted here to always get the
    current/most-recent trading day. Returns the flat list of security
    rows (unwraps the pagination envelope's "content" key, matching the
    shape used by getCompanyPriceVolumeHistory in NepseUnofficialApi)."""
    data = _post_json(
        _TODAY_PRICE_PATH,
        timeout,
        params={"page": "0", "size": str(_PAGE_SIZE), "businessDate": None},
    )
    return data.get("content", []) if isinstance(data, dict) else (data or [])


def fetch_sector_summary(timeout: int = 15) -> list[dict[str, Any]]:
    """Sector-wise turnover/volume/transaction summary."""
    data = _post_json(
        _SECTORWISE_SUMMARY_PATH,
        timeout,
        params={"page": "0", "size": str(_PAGE_SIZE), "businessDate": None},
    )
    return data.get("content", []) if isinstance(data, dict) else (data or [])


def fetch_security_id_map(timeout: int = 15) -> dict[str, int]:
    """symbol -> internal numeric security id, needed for the per-stock
    market-depth endpoint (e.g. nepalstock.com/marketdepth/9306). Sourced
    from /api/nots/company/list, the same source NepseUnofficialApi's
    getSecurityIDKeyMap uses."""
    rows = _get_json(_COMPANY_LIST_PATH, timeout, params={"page": "0", "size": str(_PAGE_SIZE)})
    rows = rows.get("content", []) if isinstance(rows, dict) else (rows or [])
    return {
        str(row.get("symbol")): row.get("id")
        for row in rows
        if row.get("symbol") is not None and row.get("id") is not None
    }


def fetch_floor_sheet(timeout: int = 15) -> list[dict[str, Any]]:
    """All floor-sheet transaction rows for the current trading session.
    UNVERIFIED endpoint path -- see module docstring."""
    data = _post_json(
        _FLOOR_SHEET_PATH,
        timeout,
        params={"size": str(_PAGE_SIZE), "sort": "contractId,desc"},
    )
    if isinstance(data, dict):
        floorsheets = data.get("floorsheets")
        if isinstance(floorsheets, dict):
            return floorsheets.get("content", [])
        return data.get("content", [])
    return data or []


def fetch_market_depth(security_id: int, timeout: int = 15) -> dict[str, Any] | None:
    """Bid/ask order-book ladder for one security. UNVERIFIED endpoint
    path -- see module docstring."""
    return _get_json(f"{_MARKET_DEPTH_PATH}{security_id}/", timeout)
