"""Shared article-page extraction for historical backfill sources.

Given a bare article URL (from GDELT, a sitemap, or a cursor-paginated
listing page), fetches the page and pulls title/body/category/published_at
using the same generic OG-tag / JSON-LD / <time> fallback chain, regardless
of which discovery mechanism found the URL. Split out of
historical_scraper.py so the sitemap- and cursor-based discovery modules can
reuse it without duplicating the extraction logic.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from email.utils import parsedate_to_datetime

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


def parse_published_at(raw: str | None) -> datetime | None:
    value = _clean(raw)
    if not value:
        return None

    value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except Exception:
        pass

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except Exception:
            continue

    try:
        return parsedate_to_datetime(value)
    except Exception:
        return None


def _extract_json_ld_published_at(soup: BeautifulSoup) -> datetime | None:
    for script in soup.select("script[type='application/ld+json']"):
        text = script.string or script.get_text(" ", strip=True)
        if not text:
            continue

        try:
            # strict=False tolerates literal control characters (raw
            # newlines/tabs) inside string values -- confirmed present in
            # the wild on myrepublica.nagariknetwork.com's own JSON-LD
            # (an unescaped newline in the "description" field), which a
            # strict parse rejects outright even though the document is
            # otherwise well-formed.
            payload = json.loads(text, strict=False)
        except Exception:
            continue

        candidates = payload if isinstance(payload, list) else [payload]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            published = item.get("datePublished") or item.get("dateCreated")
            parsed = parse_published_at(str(published) if published else None)
            if parsed is not None:
                return parsed

    return None


def extract_article(
    url: str, timeout: int, bs_date_selector: str | None = None
) -> tuple[str, str, str, datetime | None]:
    """Fetch `url` and return (title, body, category, published_at).
    Returns ("", "", "", None) on any fetch failure.

    bs_date_selector: a CSS selector for a Nepali Bikram-Sambat calendar
    text element, used as a last-resort date source for portals with no
    machine-readable date at all (confirmed: annapurnapost.com's
    `.ap__headerDate`). Ignored if the standard machine-readable sources
    (JSON-LD, meta tags, <time datetime>) already yielded a date.
    """
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except Exception as e:
        print(f"[HistoricalExtract] Failed article fetch {url}: {e}")
        return "", "", "", None

    soup = BeautifulSoup(resp.text, "html.parser")

    title = _clean(
        (soup.select_one("meta[property='og:title']") or {}).get("content")
        if soup.select_one("meta[property='og:title']")
        else None
    )
    if not title:
        title_el = soup.select_one("h1") or soup.select_one("title")
        title = _clean(title_el.get_text(" ", strip=True) if title_el else "")

    body_selectors = (
        "article p",
        "div.entry-content p",
        "div.post-content p",
        "div.news-description p",
        "div.news-body p",
        "main p",
    )
    body_parts: list[str] = []
    for selector in body_selectors:
        nodes = soup.select(selector)
        if nodes:
            body_parts = [_clean(n.get_text(" ", strip=True)) for n in nodes]
            body_parts = [p for p in body_parts if p]
            if body_parts:
                break

    if not body_parts:
        body_parts = [_clean(p.get_text(" ", strip=True)) for p in soup.find_all("p")]
        body_parts = [p for p in body_parts if p]

    body = _clean(" ".join(body_parts))[:3000]

    category = ""
    cat_meta = soup.select_one("meta[property='article:section']")
    if cat_meta:
        category = _clean(cat_meta.get("content"))
    if not category:
        cat_el = (
            soup.select_one("a[rel='category tag']")
            or soup.select_one(".cat-links a")
            or soup.select_one(".breadcrumb a:last-child")
        )
        if cat_el:
            category = _clean(cat_el.get_text(" ", strip=True))

    # JSON-LD's datePublished and the article:published_time meta tag are
    # both schema fields specifically meant for the *original* publish date.
    # A bare <time datetime> element is checked last because some portals
    # (confirmed: myrepublica.nagariknetwork.com) repurpose it to show a
    # "last updated"/render date instead of the true publish date, while
    # still exposing the correct original date via JSON-LD on the same page.
    published_at = _extract_json_ld_published_at(soup)
    if published_at is None:
        pub_meta = (
            soup.select_one("meta[property='article:published_time']")
            or soup.select_one("meta[name='pubdate']")
            or soup.select_one("meta[name='publish_date']")
        )
        if pub_meta:
            published_at = parse_published_at(pub_meta.get("content"))
    if published_at is None:
        time_el = soup.select_one("time[datetime]")
        if time_el:
            published_at = parse_published_at(time_el.get("datetime"))
    if published_at is None and bs_date_selector:
        bs_el = soup.select_one(bs_date_selector)
        if bs_el:
            published_at = parse_bs_date_text(bs_el.get_text(" ", strip=True))

    return title, body, category, published_at
