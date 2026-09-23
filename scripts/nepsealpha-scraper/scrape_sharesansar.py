"""
Downloads missing/gapped historical daily index data from sharesansar.com's
server-side DataTables endpoint (no Cloudflare, no browser needed -- plain
HTTP) and writes CSVs matching the existing repo convention:

    data/sector-2021-2026/nepsealpha_export_price_<SYMBOL>_<START>_<END>_unadjusted.csv

(Kept the nepsealpha_export_price_ filename prefix so the existing seed_from_csv.py
/ historical_nepse_loader.py pipeline picks these up without any changes --
the source site differs but the on-disk format matches what that loader expects:
Symbol,Date,Open,High,Low,Close,Percent Change,Volume,Turn Over columns.)

How the endpoint was found: sharesansar.com/index-history-data renders a
DataTable initialized with `serverSide: true` against
`GET /index-history-data?index_id=<id>&from=<date>&to=<date>&draw=&start=&length=`
-- a plain server-rendered page's inline <script> block, no login/CSRF
required for this GET endpoint, and the site has no Cloudflare challenge
(unlike nepsealpha.com, which is why this script was written as a plain-
requests replacement for the abandoned Playwright approach).

IMPORTANT gotcha found during development: the endpoint only accepts page
sizes ("length" param) matching the real UI's own dropdown options (10, 20,
50) -- anything else (e.g. 100) silently returns HTTP 202 with
recordsTotal=0/empty data, every single time, which looks exactly like
rate-limiting or flakiness until you compare against a request using a
valid page size side-by-side. This script uses length=50.

Usage:
    python3 -m venv venv
    ./venv/bin/pip install -r requirements.txt
    ./venv/bin/python scrape_sharesansar.py
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sector-2021-2026"

_BASE_URL = "https://www.sharesansar.com/index-history-data"

# IMPORTANT: the server only accepts page sizes matching the real UI's own
# lengthMenu ([10, 20, 50] in the page's DataTables init) -- confirmed
# directly: length=100 (or any value outside that set) silently returns
# HTTP 202 with recordsTotal=0/empty data every time, indistinguishable from
# a rate limit or transient failure unless compared against a working
# request side-by-side (this cost significant debugging time -- do not
# change this back to a larger "more efficient" page size without retesting
# against the live endpoint first). length=50 (the max legitimate option)
# always works.
_PAGE_LENGTH = 50

_SLEEP_BETWEEN_REQUESTS = 3.0  # seconds -- polite pacing between requests

# Kept as a defensive retry for genuine transient failures (network blips,
# etc). Not expected to trigger often now that _PAGE_LENGTH is a value the
# server actually accepts.
_EMPTY_RESPONSE_RETRY_DELAY = 10.0  # seconds

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.sharesansar.com/index-history-data",
}


@dataclass(frozen=True)
class ScrapeJob:
    symbol: str  # matches the existing CSV naming convention / historical_nepse_loader.py mapping
    index_id: int  # sharesansar's own numeric id for this index
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD


# index_id values read directly from the <select name="index"> options on
# https://www.sharesansar.com/index-history-data. Symbol codes match
# nepse-service/scraper/historical_nepse_loader.py's _SYMBOL_TO_INDEX_NAME
# (moved here from scraper-service/news-service when the NEPSE-specific
# scraping code was split into its own service) so the existing seeding
# pipeline maps them to the same nepse_index rows.
JOBS: list[ScrapeJob] = [
    # Mid-history gap: CSV coverage ends ~2026-01-14, live scraping starts 2026-06-29.
    ScrapeJob("BANKING", 1, "2026-01-14", "2026-06-29"),
    ScrapeJob("HYDROPOWER", 6, "2026-01-14", "2026-06-29"),
    ScrapeJob("MANUFACTURE", 9, "2026-01-14", "2026-06-29"),
    ScrapeJob("MICROFINANCE", 10, "2026-01-14", "2026-06-29"),
    ScrapeJob("NONLIFEINSU", 13, "2026-01-14", "2026-06-29"),
    # OTHERS has no live scraper at all -- gap runs to today.
    ScrapeJob("OTHERS", 14, "2026-01-14", "2026-08-21"),
    # No deep history at all yet -- full range needed.
    ScrapeJob("NEPSE", 12, "2021-01-16", "2026-06-29"),
    ScrapeJob("DEVBANK", 2, "2021-01-16", "2026-06-29"),
    ScrapeJob("FINANCE", 3, "2021-01-16", "2026-06-29"),
    ScrapeJob("HOTELS", 5, "2021-01-16", "2026-06-29"),
    ScrapeJob("INVESTMENT", 18, "2021-01-16", "2026-06-29"),
    ScrapeJob("LIFEINSU", 8, "2021-01-16", "2026-06-29"),
    ScrapeJob("TRADING", 17, "2021-01-16", "2026-06-29"),
]


def _output_path(job: ScrapeJob) -> Path:
    return OUTPUT_DIR / f"nepsealpha_export_price_{job.symbol}_{job.start_date}_{job.end_date}_unadjusted.csv"


_MAX_RETRIES_PER_PAGE = 3


def _fetch_page(session: requests.Session, job: ScrapeJob, start: int, draw: int) -> dict[str, Any]:
    params = {
        "index_id": job.index_id,
        "from": job.start_date,
        "to": job.end_date,
        "draw": draw,
        "start": start,
        "length": _PAGE_LENGTH,
    }
    resp = session.get(_BASE_URL, params=params, headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    if "data" not in payload:
        raise RuntimeError(f"Unexpected response shape (no 'data' key): {payload!r}")
    return payload


def _fetch_page_with_retries(session: requests.Session, job: ScrapeJob, start: int, draw: int) -> dict[str, Any]:
    """The endpoint occasionally returns recordsTotal=0/empty data on a
    request that should have rows -- see the module-level note on
    _EMPTY_RESPONSE_RETRY_DELAY for what was and wasn't confirmed about the
    trigger. This retries several times with a moderate delay, using a fresh
    requests.Session() per retry (cheap, and rules out any session/cookie
    state as a contributing factor) before giving up on this page.
    Especially important on the very first page (start=0), since a
    false-empty there would otherwise make the caller think the whole range
    has zero rows and stop immediately.
    """
    for attempt in range(1, _MAX_RETRIES_PER_PAGE + 1):
        attempt_session = session if attempt == 1 else requests.Session()
        payload = _fetch_page(attempt_session, job, start, draw)
        if payload.get("data"):
            return payload

        if attempt < _MAX_RETRIES_PER_PAGE:
            print(f"    empty response on attempt {attempt}/{_MAX_RETRIES_PER_PAGE} (start={start}) -- retrying in {_EMPTY_RESPONSE_RETRY_DELAY:.0f}s")
            time.sleep(_EMPTY_RESPONSE_RETRY_DELAY)

    return {"recordsTotal": 0, "data": []}


def _fetch_all_rows(session: requests.Session, job: ScrapeJob) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 0
    draw = 1
    total: int | None = None

    while total is None or start < total:
        payload = _fetch_page_with_retries(session, job, start, draw)
        total = payload.get("recordsTotal", 0)
        batch = payload.get("data", [])

        if not batch:
            if total and start < total:
                print(f"    still empty after retries at start={start} (recordsTotal={total}) -- stopping early for {job.symbol} at {len(rows)} rows")
            break

        rows.extend(batch)
        start += len(batch)
        draw += 1
        print(f"    fetched {len(rows)}/{total} rows")

        if start < total:
            time.sleep(_SLEEP_BETWEEN_REQUESTS)

    return rows


def _row_to_csv_line(symbol: str, row: dict[str, Any]) -> str:
    """Matches historical_nepse_loader.py's expected columns:
    Symbol,Date,Open,High,Low,Close,Percent Change,Volume,Turn Over
    (loader only reads Symbol/Date/Close/Percent Change -- Open/High/Low/
    Volume/Turn Over are passed through best-effort for completeness/parity
    with the existing nepsealpha-sourced CSVs, using sharesansar's turnover
    figure in the Volume column since it has no separate share-count field.)
    """
    date_str = row.get("published_date", "")
    open_ = row.get("open", "")
    high = row.get("high", "")
    low = row.get("low", "")
    close = row.get("current", "")
    pct = row.get("per_change", "")
    turnover = row.get("turnover", "-")

    pct_field = f"{pct} %" if pct not in (None, "") else ""

    def q(value: Any) -> str:
        return f'"{value}"'

    return ",".join(
        [
            q(symbol),
            q(date_str),
            q(open_),
            q(high),
            q(low),
            q(close),
            q(pct_field),
            q(turnover),
            q("-"),
        ]
    )


def _write_csv(job: ScrapeJob, rows: list[dict[str, Any]]) -> Path:
    out_path = _output_path(job)

    # historical_nepse_loader.py reads oldest-vs-newest order-independently
    # (it just parses every row), but sort ascending for human readability
    # and to match how the existing checked-in CSVs are ordered.
    def _sort_key(r: dict[str, Any]) -> date:
        try:
            return datetime.strptime(r.get("published_date", ""), "%Y-%m-%d").date()
        except Exception:
            return date.min

    rows_sorted = sorted(rows, key=_sort_key)

    with out_path.open("w", encoding="utf-8", newline="\n") as fp:
        fp.write('"Symbol","Date","Open","High","Low","Close","Percent Change","Volume","Turn Over"\n')
        for row in rows_sorted:
            fp.write(_row_to_csv_line(job.symbol, row) + "\n")

    return out_path


def run() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    remaining = [job for job in JOBS if not _output_path(job).exists()]
    if not remaining:
        print("Nothing to do -- all job output files already exist.")
        return 0

    print(f"{len(remaining)} of {len(JOBS)} jobs remaining (others already downloaded).")

    session = requests.Session()

    for i, job in enumerate(remaining):
        print(f"\n[{i + 1}/{len(remaining)}] {job.symbol} (index_id={job.index_id}): {job.start_date} -> {job.end_date}")

        try:
            rows = _fetch_all_rows(session, job)
        except Exception as e:
            print(f"  FAILED: {e}")
            print("  Skipping this job -- rerun the script later to retry (already-downloaded jobs are skipped).")
            continue

        if not rows:
            print("  No rows returned -- skipping (nothing to write).")
            continue

        out_path = _write_csv(job, rows)
        print(f"  Saved {len(rows)} rows -> {out_path}")

        time.sleep(_SLEEP_BETWEEN_REQUESTS)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
