"""
NEPSE index scraper.

Source order:
  1) nepalstock.com.np official API (primary): all 17 indices -- NEPSE,
     Sensitive, Float, Sensitive Float and the 13 sector sub-indices
     (incl. Others and Mutual Fund, which nepsetrading doesn't list).
  2) nepsetrading.com/market/sectors (fallback, NEPSE + 11 sectors)
  3) merolagani.com (last-resort fallback)
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import requests

from nepse_common.constants.index_registry import INDEX_BY_OFFICIAL_ID

from scraper.merolagani_scraper import (
    scrape_merolagani_main_index,
    scrape_merolagani_sector_indices,
)
from scraper.nepse_market_data import fetch_official_indices

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_NEPS_TRADING_SECTORS_URL = "https://nepsetrading.com/market/sectors"

_SYMBOL_TO_INDEX_NAME = {
    "BANKING": "Banking SubIndex",
    "DEVBANK": "Development Bank Index",
    "FINANCE": "Finance Index",
    "HOTELS": "Hotels And Tourism Index",
    "HYDROPOWER": "HydroPower Index",
    "INVESTMENT": "Investment Index",
    "LIFEINSU": "Life Insurance",
    "MANUFACTURE": "Manufacturing And Processing",
    "MICROFINANCE": "Microfinance Index",
    "NONLIFEINSU": "Non Life Insurance",
    "TRADING": "Trading Index",
}


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return float(str(value).strip().replace(",", "").replace("%", ""))
    except Exception:
        return None


def _extract_market_rows_from_html(html: str) -> list[dict[str, Any]]:
    # nepsetrading embeds market arrays inside escaped Next.js script payload.
    decoded = html.encode("utf-8").decode("unicode_escape")
    marker = '[{"symbol"'
    start = decoded.find(marker)
    if start == -1:
        return []

    end = decoded.find("}]", start)
    if end == -1:
        return []

    try:
        rows = json.loads(decoded[start : end + 2])
    except Exception:
        return []

    if isinstance(rows, list):
        return [r for r in rows if isinstance(r, dict)]
    return []


def _fetch_nepsetrading_rows(timeout: int = 15) -> list[dict[str, Any]]:
    try:
        resp = requests.get(_NEPS_TRADING_SECTORS_URL, timeout=timeout, headers=_HEADERS)
        resp.raise_for_status()
    except Exception as e:
        print(f"[NEPSE Scraper] nepsetrading fetch failed: {e}")
        return []

    rows = _extract_market_rows_from_html(resp.text)
    if not rows:
        print("[NEPSE Scraper] nepsetrading rows missing/empty in page payload.")
        return []

    print(f"[NEPSE Scraper] nepsetrading rows fetched: {len(rows)}")
    return rows


def _build_main_from_nepsetrading(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        if str(row.get("symbol", "")).strip().upper() != "NEPSE":
            continue

        previous = _to_float(row.get("previous_close"))
        current = _to_float(row.get("ltp"))
        change = _to_float(row.get("point_change"))
        pct = _to_float(row.get("percentage_change"))

        # If point_change is missing but current and previous exist, derive it.
        if change is None and current is not None and previous is not None:
            change = current - previous

        # Prefer deriving percent_change from change/previous directly --
        # mathematically unambiguous, unlike guessing whether the source's
        # own percentage_change field is already a whole-number percent or a
        # fraction that still needs *100 (that heuristic previously inflated
        # every real percent_change by ~100x whenever a genuine daily move
        # happened to fall under 1%, which is most trading days).
        if previous not in (None, 0) and change is not None:
            pct = (change / previous) * 100.0

        return {
            "index": "NEPSE",
            "value": current,
            "change": change,
            "percent_change": pct,
            "scraped_at": datetime.now().isoformat(),
        }
    return None


def _build_sectors_from_nepsetrading(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scraped_at = datetime.now().isoformat()
    out: list[dict[str, Any]] = []

    for row in rows:
        symbol = str(row.get("symbol", "")).strip().upper()
        if symbol not in _SYMBOL_TO_INDEX_NAME:
            continue

        current = _to_float(row.get("ltp"))
        previous = _to_float(row.get("previous_close"))
        change = _to_float(row.get("point_change"))
        pct = _to_float(row.get("percentage_change"))

        if change is None and current is not None and previous is not None:
            change = current - previous

        # See _build_main_from_nepsetrading for why this is derived directly
        # rather than guessing at the source field's scale.
        if previous not in (None, 0) and change is not None:
            pct = (change / previous) * 100.0

        out.append(
            {
                "index": _SYMBOL_TO_INDEX_NAME[symbol],
                "value": current,
                "change": change,
                "percent_change": pct,
                "scraped_at": scraped_at,
            }
        )

    return out


def scrape_nepse_main_index(timeout: int = 15) -> dict[str, Any] | None:
    """Main NEPSE index from nepsetrading primary, merolagani fallback."""
    rows = _fetch_nepsetrading_rows(timeout)
    if rows:
        main = _build_main_from_nepsetrading(rows)
        if main is not None:
            return main

    print("[NEPSE Scraper] Main index fallback to Merolagani.")
    return scrape_merolagani_main_index(timeout)


def scrape_sector_indices(timeout: int = 15) -> list[dict[str, Any]]:
    """Sector indices from nepsetrading primary, merolagani fallback."""
    rows = _fetch_nepsetrading_rows(timeout)
    if rows:
        sectors = _build_sectors_from_nepsetrading(rows)
        if sectors:
            return sectors

    print("[NEPSE Scraper] Sector indices fallback to Merolagani.")
    return scrape_merolagani_sector_indices(timeout)


def _scrape_official_indices(timeout: int = 15) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """(main NEPSE point, other 16 index points) from nepalstock.com.np, in
    the same point shape the nepsetrading/merolagani builders return."""
    try:
        rows = fetch_official_indices(timeout)
    except Exception as e:
        print(f"[NEPSE Scraper] nepalstock official index fetch failed: {e}")
        return None, []

    scraped_at = datetime.now().isoformat()
    main: dict[str, Any] | None = None
    others: list[dict[str, Any]] = []
    for row in rows:
        spec = INDEX_BY_OFFICIAL_ID.get(row.get("id"))
        current = _to_float(row.get("currentValue"))
        if spec is None or current is None:
            continue

        change = _to_float(row.get("change"))
        previous = _to_float(row.get("previousClose"))
        if previous is None and change is not None:
            previous = current - change
        # Derived from change/previous for the same reason as the
        # nepsetrading builders below; perChange is rounded to 2 dp.
        pct = (change / previous) * 100.0 if previous not in (None, 0) and change is not None else _to_float(row.get("perChange"))

        point = {
            "index": spec.name,
            "value": current,
            "change": change,
            "percent_change": pct,
            "scraped_at": scraped_at,
        }
        if spec.name == "NEPSE":
            main = point
        else:
            others.append(point)
    return main, others


def scrape_all_nepse_data(timeout: int = 15) -> dict[str, Any]:
    """Scrape the NEPSE main index and the other indices: official API
    first, the nepsetrading/merolagani chain if it fails."""
    main_index, sector_indices = _scrape_official_indices(timeout)
    if main_index is not None and sector_indices:
        return {
            "scraped_at": datetime.now().isoformat(),
            "source": "nepalstock",
            "source_used": "nepalstock_official",
            "nepse_index": main_index,
            "sector_indices": sector_indices,
        }

    source_used = "nepsetrading_primary"

    rows = _fetch_nepsetrading_rows(timeout)
    main_index = _build_main_from_nepsetrading(rows) if rows else None
    sector_indices = _build_sectors_from_nepsetrading(rows) if rows else []

    if main_index is None:
        main_index = scrape_merolagani_main_index(timeout)
        source_used = "nepsetrading_primary_merolagani_main_fallback"

    if not sector_indices:
        sector_indices = scrape_merolagani_sector_indices(timeout)
        if source_used == "nepsetrading_primary_merolagani_main_fallback":
            source_used = "nepsetrading_primary_merolagani_full_fallback"
        else:
            source_used = "nepsetrading_primary_merolagani_sector_fallback"

    if main_index is None and sector_indices:
        source_used = f"{source_used}_sector_only"
    elif main_index is not None and not sector_indices:
        source_used = f"{source_used}_main_only"
    elif main_index is None and not sector_indices:
        source_used = f"{source_used}_empty"

    return {
        "scraped_at": datetime.now().isoformat(),
        "source": "nepsetrading",
        "source_used": source_used,
        "nepse_index": main_index,
        "sector_indices": sector_indices,
    }
