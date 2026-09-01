"""Per-source extraction strategies for backfilling missing published_at /
body on existing nepse_news rows, given only the row's own URL.

Each source needed its own fix after directly inspecting real article
pages (see the dated research notes below) -- there is no single generic
selector chain that works across all of them:

  - onlinekhabar.com : NO machine-readable date anywhere on the page (no
    <time>, no article:published_time, no JSON-LD). The URL itself encodes
    year/month though (/YYYY/MM/<id>/<slug>), so that's used as a
    month-precision fallback -- exact day is not recoverable this way.
    Body lives in `div.ok18-single-post-content-wrap p` (the live
    scraper's selector, `-content-section`, doesn't exist on the current
    markup at all -- confirmed directly, a stale-selector bug independent
    of this backfill).
  - setopati.com : a real BS (Bikram Sambat) date lives in
    `.pub-date` as "प्रकाशित मिति: <weekday>, <month> <day>, <year>" --
    needs BS->AD conversion (see nepali_bs_date.parse_bs_date_text, which
    already supports this field ordering). Body lives in `.detail-box p`
    (the live scraper's selector, `div.news-description`, doesn't exist on
    the current markup either).
  - merolagani.com : a real AD date/time lives in
    `#ctl00_ContentPlaceHolder1_newsDate` as e.g. "Jun 29, 2026 02:05 PM"
    -- the live scraper's time_sel="time[datetime]" simply never matched
    this element (it's a <span>, not a <time> tag), so this source's
    published_at was always None despite the date being present all along.
  - nepalipaisa.com : body is NOT in the server-rendered HTML at all (a
    JS-driven page) -- but its own news-detail.js reveals a real per-article
    JSON endpoint, GET /api/GetNews?newsId=<id>, whose
    result.descriptions[].description field holds the full HTML body.
  - sharesansar.com : reuses the existing generic extractor (its old rows
    predate the cursor-listing-date fix; article pages there have a
    trustworthy og:title/body but NOT a trustworthy date -- see
    historical_cursor_scraper.py's own docstring on why. A missing
    published_at for a pre-existing sharesansar row is intentionally left
    unfixed by this module for that reason -- only body is backfilled).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from scraper.nepali_bs_date import parse_bs_date_text

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ne;q=0.8",
}


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class FieldsResult:
    published_at: datetime | None
    body: str | None
    # True if the fetch/parse itself failed outright (network error, 404,
    # etc) -- distinct from "fetched fine but this field genuinely isn't
    # recoverable" (e.g. onlinekhabar's exact day), which returns
    # published_at=None without setting this.
    fetch_failed: bool = False


def _get_soup(url: str, timeout: int) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except Exception as e:
        print(f"[FieldsBackfill] Failed fetch {url}: {e}")
        return None
    return BeautifulSoup(resp.text, "html.parser")


def _generic_body(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        nodes = soup.select(selector)
        parts = [_clean(n.get_text(" ", strip=True)) for n in nodes]
        parts = [p for p in parts if p]
        if parts:
            return _clean(" ".join(parts))[:3000]
    return ""


def _onlinekhabar(url: str, timeout: int) -> FieldsResult:
    soup = _get_soup(url, timeout)
    if soup is None:
        return FieldsResult(published_at=None, body=None, fetch_failed=True)

    body = _generic_body(soup, ("div.ok18-single-post-content-wrap p",))

    # /YYYY/MM/<id>/<slug> -- confirmed via research this is the article's
    # real publish year/month (spot-checked chronological ordering across
    # a sample of stored rows). Day is not recoverable from the URL, so
    # this deliberately anchors to the 1st of the month rather than
    # guessing -- a coarse but honest month-precision date beats none.
    match = re.search(r"onlinekhabar\.com/(\d{4})/(\d{2})/", url)
    published_at = datetime(int(match.group(1)), int(match.group(2)), 1) if match else None

    return FieldsResult(published_at=published_at, body=body or None)


def _setopati(url: str, timeout: int) -> FieldsResult:
    soup = _get_soup(url, timeout)
    if soup is None:
        return FieldsResult(published_at=None, body=None, fetch_failed=True)

    body = _generic_body(soup, (".detail-box p",))

    published_at = None
    date_el = soup.select_one(".pub-date")
    if date_el:
        published_at = parse_bs_date_text(date_el.get_text(" ", strip=True))

    return FieldsResult(published_at=published_at, body=body or None)


_MEROLAGANI_DATE_FORMAT = "%b %d, %Y %I:%M %p"


def _merolagani(url: str, timeout: int) -> FieldsResult:
    soup = _get_soup(url, timeout)
    if soup is None:
        return FieldsResult(published_at=None, body=None, fetch_failed=True)

    body = _generic_body(
        soup,
        (
            "#ctl00_ContentPlaceHolder1_newsDetail p",
            "#ctl00_ContentPlaceHolder1_newsDetail",
            ".media-content p",
        ),
    )

    published_at = None
    date_el = soup.select_one("#ctl00_ContentPlaceHolder1_newsDate")
    if date_el:
        date_text = _clean(date_el.get_text(" ", strip=True))
        try:
            published_at = datetime.strptime(date_text, _MEROLAGANI_DATE_FORMAT)
        except Exception:
            published_at = None

    return FieldsResult(published_at=published_at, body=body or None)


def _strip_html(html: str) -> str:
    return _clean(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))


def _nepalipaisa(url: str, timeout: int) -> FieldsResult:
    # nepalipaisa's body is never in the server-rendered article page (a
    # JS-driven page) -- reuse the same per-article API its own
    # news-detail.js calls instead of trying to scrape HTML at all.
    match = re.search(r"/news-detail/(\d+)", urlparse(url).path)
    if not match:
        return FieldsResult(published_at=None, body=None, fetch_failed=True)
    news_id = match.group(1)

    try:
        resp = requests.get(
            "https://nepalipaisa.com/api/GetNews",
            params={"newsId": news_id},
            headers=_HEADERS,
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        print(f"[FieldsBackfill] nepalipaisa GetNews failed for {url}: {e}")
        return FieldsResult(published_at=None, body=None, fetch_failed=True)

    result = payload.get("result") or {}

    published_at = None
    published_on = result.get("publishedOn")
    if published_on:
        try:
            published_at = datetime.fromisoformat(published_on)
        except Exception:
            published_at = None

    descriptions = result.get("descriptions") or []
    body_html_parts = [d.get("description", "") for d in descriptions if isinstance(d, dict)]
    body = _clean(" ".join(_strip_html(h) for h in body_html_parts if h))[:3000]

    return FieldsResult(published_at=published_at, body=body or None)


_SHARESANSAR_DATE_FORMAT = "%a, %b %d, %Y %I:%M %p"


def _sharesansar(url: str, timeout: int) -> FieldsResult:
    # CORRECTION to this module's original research: sharesansar's
    # article:published_time meta tag and its sidebar .date spans ARE a
    # hardcoded-constant / "today" bug as found earlier, but a genuine,
    # distinct, trustworthy date DOES exist elsewhere on the page --
    # `.detail h5` (e.g. "Tue, Nov 17, 2015 5:39 AM"), confirmed different
    # across articles by direct spot-check. Body lives in
    # `#newsdetail-content` (an id, not a class -- the live scraper's
    # `div.newsdetail-content` class selector never matched it).
    soup = _get_soup(url, timeout)
    if soup is None:
        return FieldsResult(published_at=None, body=None, fetch_failed=True)

    body = _generic_body(soup, ("#newsdetail-content",))

    published_at = None
    date_el = soup.select_one(".detail h5")
    if date_el:
        # The h5 also contains trailing "on <category tags>" text after the
        # date/time -- take only the leading date/time portion.
        raw = _clean(date_el.get_text(" ", strip=True))
        match = re.match(r"^[A-Za-z]{3}, [A-Za-z]{3} \d{1,2}, \d{4} \d{1,2}:\d{2} [AP]M", raw)
        if match:
            try:
                published_at = datetime.strptime(match.group(0), _SHARESANSAR_DATE_FORMAT)
            except Exception:
                published_at = None

    return FieldsResult(published_at=published_at, body=body or None)


_STRATEGIES: dict[str, Callable[[str, int], FieldsResult]] = {
    "onlinekhabar": _onlinekhabar,
    "setopati": _setopati,
    "merolagani": _merolagani,
    "nepalipaisa": _nepalipaisa,
    "sharesansar": _sharesansar,
}

SUPPORTED_SOURCES: tuple[str, ...] = tuple(_STRATEGIES.keys())


def backfill_fields(source: str, url: str, timeout: int = 20) -> FieldsResult:
    strategy = _STRATEGIES.get(source)
    if strategy is None:
        raise ValueError(f"No fields-backfill strategy for source: {source}")
    return strategy(url, timeout)
