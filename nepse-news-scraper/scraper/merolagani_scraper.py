from __future__ import annotations

from datetime import datetime
from time import sleep
from typing import Any

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

_SELECTED_SECTORS = {
    "banking",
    "development bank",
    "finance",
    "hydropower",
    "insurance",
    "microfinance",
    "manufacturing",
    "investment",
    "hotel",
    "trading",
}

_NEWSLIST_URL = "https://merolagani.com/NewsList.aspx"
_LATEST_MARKET_URL = "https://merolagani.com/LatestMarket.aspx"
_INDICES_URL = "https://merolagani.com/Indices.aspx"

_SYMBOL_TO_INDEX_NAME = {
    "banking": "Banking SubIndex",
    "development bank": "Development Bank Index",
    "finance": "Finance Index",
    "hydropower": "HydroPower Index",
    "microfinance": "Microfinance Index",
    "life insurance": "Life Insurance",
    "non-life insurance": "Non Life Insurance",
    "non life insurance": "Non Life Insurance",
    "trading": "Trading Index",
    "hotels and tourism": "Hotels And Tourism Index",
    "investment": "Investment Index",
    "manufacturing and processing": "Manufacturing And Processing",
    "sensitive": "Sensitive Index",
    "sen. float": "Sensitive Float Index",
    "sen float": "Sensitive Float Index",
    "float": "Float Index",
    "nepse": "NEPSE",
}


def _to_float(text: Any) -> float | None:
    try:
        if text is None:
            return None
        if isinstance(text, (int, float)):
            return float(text)
        return float(str(text).strip().replace(",", "").replace("%", ""))
    except Exception:
        return None


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _get(url: str, timeout: int = 15) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"[Merolagani Fallback] Failed to fetch {url}: {e}")
        return None


def _get_with_wait(
    url: str,
    timeout: int = 15,
    attempts: int = 4,
    wait_seconds: float = 1.6,
) -> BeautifulSoup | None:
    """Fetch a page with short wait/retry loops for late-populated HTML sections."""
    last_soup: BeautifulSoup | None = None
    for attempt in range(1, attempts + 1):
        soup = _get(url, timeout)
        if soup is None:
            if attempt < attempts:
                sleep(wait_seconds)
            continue

        last_soup = soup
        rows = soup.select("table[data-live='index-summary'] tr")
        if rows:
            return soup

        # Wait and retry: this page frequently returns early/incomplete sidebar markup.
        if attempt < attempts:
            sleep(wait_seconds)

    return last_soup


def _extract_sidebar_rows_from_newslist(soup: BeautifulSoup) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    # Primary target: sidebar live index summary table on NewsList page.
    for tr in soup.select("table[data-live='index-summary'] tr"):
        cols = [c.get_text(" ", strip=True) for c in tr.select("td")]
        if len(cols) < 2:
            continue

        raw_name = cols[0]
        name = _normalize_name(raw_name)
        index_name = _SYMBOL_TO_INDEX_NAME.get(name) or raw_name
        value = _to_float(cols[1])

        change = _to_float(cols[2]) if len(cols) > 2 else None
        pct = _to_float(cols[3]) if len(cols) > 3 else None

        # In many cases, row has no explicit change column, only percent.
        if pct is None and len(cols) > 2:
            pct = _to_float(cols[-1])

        rows.append(
            {
                "index": index_name,
                "value": value,
                "change": change,
                "percent_change": pct,
            }
        )

    return rows


def _extract_from_newslist_sidebar(timeout: int = 15) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    soup = _get_with_wait(_NEWSLIST_URL, timeout=timeout)
    if soup is None:
        return None, []

    sidebar_rows = _extract_sidebar_rows_from_newslist(soup)
    if not sidebar_rows:
        return None, []

    main_row = None
    sectors: list[dict[str, Any]] = []
    scraped_at = datetime.now().isoformat()

    for row in sidebar_rows:
        idx_name = str(row.get("index") or "")
        idx_norm = _normalize_name(idx_name)

        payload = {
            "index": idx_name,
            "value": row.get("value"),
            "change": row.get("change"),
            "percent_change": row.get("percent_change"),
            "scraped_at": scraped_at,
        }

        if idx_norm == "nepse":
            main_row = {
                "index": "NEPSE",
                "value": payload["value"],
                "change": payload["change"],
                "percent_change": payload["percent_change"],
                "scraped_at": scraped_at,
            }
            continue

        if any(s in idx_norm for s in _SELECTED_SECTORS):
            sectors.append(payload)

    return main_row, sectors


def scrape_merolagani_main_index(timeout: int = 15) -> dict[str, Any] | None:
    main_from_sidebar, _ = _extract_from_newslist_sidebar(timeout)
    if main_from_sidebar is not None and main_from_sidebar.get("value") is not None:
        print(f"[Merolagani Fallback] Main index (NewsList sidebar): {main_from_sidebar['value']}")
        return main_from_sidebar

    soup = _get(_LATEST_MARKET_URL, timeout)
    if soup is None:
        return None

    index_tag = (
        soup.select_one("#ctl00_ContentPlaceHolder1_LiveMarket1_lblIndex")
        or soup.select_one(".nepse-index")
        or soup.select_one("[id*='lblIndex']")
    )
    change_tag = (
        soup.select_one("#ctl00_ContentPlaceHolder1_LiveMarket1_lblChange")
        or soup.select_one("[id*='lblChange']")
    )
    pct_tag = (
        soup.select_one("#ctl00_ContentPlaceHolder1_LiveMarket1_lblPercentChange")
        or soup.select_one("[id*='lblPercentChange']")
    )

    value = _to_float(index_tag.get_text()) if index_tag else None
    change = _to_float(change_tag.get_text()) if change_tag else None
    pct = _to_float(pct_tag.get_text()) if pct_tag else None

    if value is None:
        idx_soup = _get(_INDICES_URL, timeout)
        if idx_soup is not None:
            first_row = idx_soup.select_one("table tbody tr")
            if first_row:
                cols = [c.get_text(" ", strip=True) for c in first_row.select("td")]
                if len(cols) >= 5:
                    value = _to_float(cols[2])
                    change = _to_float(cols[3])
                    pct = _to_float(cols[4])

    result = {
        "index": "NEPSE",
        "value": value,
        "change": change,
        "percent_change": pct,
        "scraped_at": datetime.now().isoformat(),
    }
    print(f"[Merolagani Fallback] Main index: {result['value']}")
    return result


def scrape_merolagani_sector_indices(timeout: int = 15) -> list[dict[str, Any]]:
    _, sectors_from_sidebar = _extract_from_newslist_sidebar(timeout)
    if sectors_from_sidebar:
        print(f"[Merolagani Fallback] Sector indices (NewsList sidebar): {len(sectors_from_sidebar)} sectors scraped.")
        return sectors_from_sidebar

    soup = _get(_INDICES_URL, timeout)
    if soup is None:
        return []

    results: list[dict[str, Any]] = []
    scraped_at = datetime.now().isoformat()

    for table in soup.select("table"):
        rows = table.select("tr")
        for row in rows[1:]:
            cols = row.select("td")
            if len(cols) < 2:
                continue

            sector_name = cols[0].get_text().strip()
            if not sector_name:
                continue

            if not any(s in sector_name.lower() for s in _SELECTED_SECTORS):
                continue

            results.append(
                {
                    "index": sector_name,
                    "value": _to_float(cols[1].get_text()) if len(cols) > 1 else None,
                    "change": _to_float(cols[2].get_text()) if len(cols) > 2 else None,
                    "percent_change": _to_float(cols[3].get_text()) if len(cols) > 3 else None,
                    "scraped_at": scraped_at,
                }
            )

    print(f"[Merolagani Fallback] Sector indices: {len(results)} sectors scraped.")
    return results
