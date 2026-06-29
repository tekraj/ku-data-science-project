from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from time import sleep
from typing import Any

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ne;q=0.8",
}

_GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_GDELT_MIN_INTERVAL_SECONDS = 1.2
_GDELT_MAX_RETRIES = 6
_GDELT_BACKOFF_BASE_SECONDS = 2.0
_last_gdelt_call_ts = 0.0


@dataclass(frozen=True)
class PortalSpec:
    source: str
    tier: str
    domain: str


# The user-requested major portals for historical ingestion.
_PORTALS: tuple[PortalSpec, ...] = (
    PortalSpec(source="onlinekhabar", tier="general", domain="onlinekhabar.com"),
    PortalSpec(source="setopati", tier="general", domain="setopati.com"),
    PortalSpec(source="ekantipur", tier="general", domain="ekantipur.com"),
    PortalSpec(source="merolagani", tier="finance", domain="merolagani.com"),
    PortalSpec(source="biznessnews", tier="finance", domain="biznessnews.com"),
)


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _to_gdelt_ts(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S")


def _parse_published_at(raw: str | None) -> datetime | None:
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
            payload = json.loads(text)
        except Exception:
            continue

        candidates = payload if isinstance(payload, list) else [payload]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            published = item.get("datePublished") or item.get("dateCreated")
            parsed = _parse_published_at(str(published) if published else None)
            if parsed is not None:
                return parsed

    return None


def _extract_article(url: str, timeout: int) -> tuple[str, str, str, datetime | None]:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except Exception as e:
        print(f"[Historical] Failed article fetch {url}: {e}")
        return "", "", "", None

    soup = BeautifulSoup(resp.text, "html.parser")

    title = _clean(
        (soup.select_one("meta[property='og:title']") or {}).get("content")
        if soup.select_one("meta[property='og:title']")
        else None
    )
    if not title:
        title = _clean((soup.select_one("h1") or soup.select_one("title")).get_text(" ", strip=True) if (soup.select_one("h1") or soup.select_one("title")) else "")

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

    published_at = None
    time_el = soup.select_one("time[datetime]")
    if time_el:
        published_at = _parse_published_at(time_el.get("datetime"))
    if published_at is None:
        pub_meta = (
            soup.select_one("meta[property='article:published_time']")
            or soup.select_one("meta[name='pubdate']")
            or soup.select_one("meta[name='publish_date']")
        )
        if pub_meta:
            published_at = _parse_published_at(pub_meta.get("content"))
    if published_at is None:
        published_at = _extract_json_ld_published_at(soup)

    return title, body, category, published_at


def _fetch_gdelt_day_urls(
    portal: PortalSpec,
    target_day: date,
    timeout: int,
    max_records: int,
) -> list[str]:
    global _last_gdelt_call_ts

    start_dt = datetime.combine(target_day, time.min, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=1)

    query = f"site:{portal.domain}"
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "sort": "DateAsc",
        "maxrecords": max_records,
        "startdatetime": _to_gdelt_ts(start_dt),
        "enddatetime": _to_gdelt_ts(end_dt),
    }

    payload: dict[str, Any] | None = None
    last_error: Exception | None = None

    for attempt in range(1, _GDELT_MAX_RETRIES + 1):
        now_ts = datetime.now(timezone.utc).timestamp()
        elapsed = now_ts - _last_gdelt_call_ts
        if elapsed < _GDELT_MIN_INTERVAL_SECONDS:
            sleep(_GDELT_MIN_INTERVAL_SECONDS - elapsed)

        try:
            resp = requests.get(_GDELT_DOC_API, params=params, headers=_HEADERS, timeout=timeout)
            _last_gdelt_call_ts = datetime.now(timezone.utc).timestamp()

            # GDELT frequently returns 429 on burst requests.
            if resp.status_code == 429:
                raise requests.HTTPError("429 Too Many Requests", response=resp)

            resp.raise_for_status()
            payload = resp.json()
            break
        except Exception as e:
            last_error = e
            if attempt >= _GDELT_MAX_RETRIES:
                break

            backoff = _GDELT_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 0.75)
            print(
                f"[Historical] GDELT retry {attempt}/{_GDELT_MAX_RETRIES - 1} "
                f"for {portal.source} {target_day.isoformat()} in {backoff:.1f}s: {e}"
            )
            sleep(backoff)

    if payload is None:
        print(
            f"[Historical] GDELT lookup failed for {portal.source} {target_day.isoformat()}: {last_error}"
        )
        return []

    seen: set[str] = set()
    urls: list[str] = []

    for item in payload.get("articles") or []:
        url = _clean(item.get("url"))
        if not url:
            continue
        if portal.domain not in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)

    return urls


def scrape_historical_for_date(
    target_day: date,
    timeout: int = 20,
    max_records_per_portal_per_day: int = 200,
) -> list[dict[str, Any]]:
    """Collect historical articles for the requested date from selected portals."""
    collected: list[dict[str, Any]] = []

    for portal in _PORTALS:
        urls = _fetch_gdelt_day_urls(
            portal=portal,
            target_day=target_day,
            timeout=timeout,
            max_records=max_records_per_portal_per_day,
        )

        portal_count = 0
        for url in urls:
            title, body, category, published_at = _extract_article(url, timeout=timeout)
            if not title:
                continue

            collected.append(
                {
                    "source": portal.source,
                    "portal_tier": portal.tier,
                    "url": url,
                    "title": title,
                    "body": body,
                    "category": category,
                    "published_at": published_at,
                }
            )
            portal_count += 1

        print(
            f"[Historical] {portal.source} {target_day.isoformat()}: "
            f"{portal_count} articles extracted"
        )

    print(
        f"[Historical] Total for {target_day.isoformat()}: {len(collected)} articles "
        f"across {len(_PORTALS)} portals"
    )
    return collected
