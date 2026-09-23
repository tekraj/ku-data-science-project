"""Cursor-paginated historical discovery for sharesansar.com.

sharesansar.com's /category/latest listing has no date-range query param
and its own ?page=N is ignored -- it instead paginates via an opaque,
base64-encoded cursor query param that decodes to
{"published_date": "...", "_pointsToNextItems": true/false}. Following the
cursor chain walks strictly backward in time, one page (~10-20 articles) per
request, with no way to jump directly to an arbitrary date. Confirmed
directly during research: the cursor on the first /category/latest page
decodes to the newest article's published_date, and following it lands on
the next-older batch.

IMPORTANT: sharesansar's own article detail pages do NOT carry a usable
published date -- confirmed directly: every article's
`article:published_time` meta tag (and JSON-LD datePublished) returns the
exact same hardcoded "2016-12-15T05:55:55-05:00" regardless of the
article's real content or URL-embedded date, and the on-page ".date" spans
likewise just reflect today's date (a template bug on their end, the same
class of issue found on nepsekhabar.com and annapurnapost.com during this
backfill's research). Do NOT use historical_article_extractor's date logic
for sharesansar -- the *listing page* is the only reliable date source: each
article card includes its own `<span class="text-org">Sunday, August 23,
2026</span>` next to the headline, confirmed accurate and distinct per
article. This module therefore returns (url, published_at, title) triples
scraped from the listing page itself; only body/category still need to come
from the article page.

Because this can only walk sequentially, the per-minute ticker for this
portal fetches one *listing page* per tick (which yields a batch of dated
articles + the next cursor), not one article per tick like the sitemap
portals.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ne;q=0.8",
}

SOURCE = "sharesansar"
TIER = "finance"

_BASE_URL = "https://www.sharesansar.com/category/latest"
_ARTICLE_URL_RE = re.compile(r"sharesansar\.com/newsdetail/")
_CURSOR_RE = re.compile(r"cursor=([A-Za-z0-9+/=_-]+)")

# Matches "Sunday, August 23, 2026" as rendered in each card's
# <span class="text-org">...</span>.
_LISTING_DATE_FORMAT = "%A, %B %d, %Y"


@dataclass(frozen=True)
class ListedArticle:
    url: str
    title: str
    published_at: datetime | None


@dataclass(frozen=True)
class CursorPage:
    articles: list[ListedArticle]
    next_cursor: str | None  # None once _pointsToNextItems is false / no cursor found


def decode_cursor(cursor: str) -> dict:
    padded = cursor + "=" * (-len(cursor) % 4)
    return json.loads(base64.b64decode(padded).decode("utf-8"))


def _parse_listing_date(text: str) -> datetime | None:
    try:
        return datetime.strptime(text.strip(), _LISTING_DATE_FORMAT)
    except Exception:
        return None


def _extract_listed_articles(soup: BeautifulSoup) -> list[ListedArticle]:
    """Walks each `h4.featured-news-title` card, which the real article
    listing (as opposed to nav-menu links that incidentally match
    /newsdetail/) always renders as:
        <a href="...newsdetail/...">
            <h4 class="featured-news-title">Title</h4>
        </a>
        <p><span class="text-org">Sunday, August 23, 2026</span></p>
    """
    articles: list[ListedArticle] = []
    seen: set[str] = set()

    for heading in soup.select("h4.featured-news-title"):
        link = heading.find_parent("a", href=True)
        if link is None:
            continue

        href = urljoin(_BASE_URL, link["href"]).split("#", 1)[0]
        if not _ARTICLE_URL_RE.search(href):
            continue
        if href in seen:
            continue
        seen.add(href)

        title = heading.get_text(" ", strip=True)

        published_at = None
        # The date <p> is a sibling of the wrapping <a>, one level up from
        # the heading's own container.
        card = link.find_parent(["div"]) or link.parent
        date_span = card.select_one(".text-org") if card else None
        if date_span is None:
            # Fall back to searching forward from the link itself.
            next_p = link.find_next("p")
            date_span = next_p.select_one(".text-org") if next_p else None
        if date_span is not None:
            published_at = _parse_listing_date(date_span.get_text(strip=True))

        articles.append(ListedArticle(url=href, title=title, published_at=published_at))

    return articles


def _extract_next_cursor(html: str) -> str | None:
    """The listing page embeds one or more cursor= links; the one worth
    following is the one whose decoded payload has _pointsToNextItems=true
    (an older-items cursor can also appear for the 'previous/newer' link,
    decoded with _pointsToNextItems=false)."""
    candidates = _CURSOR_RE.findall(html)
    for raw_cursor in candidates:
        try:
            payload = decode_cursor(raw_cursor)
        except (ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
            continue
        if payload.get("_pointsToNextItems") is True:
            return raw_cursor
    return None


def fetch_cursor_page(cursor: str | None, timeout: int = 20) -> CursorPage:
    """Fetch one /category/latest listing page. cursor=None fetches the
    first (newest) page."""
    url = _BASE_URL if cursor is None else f"{_BASE_URL}?cursor={cursor}"

    resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")
    articles = _extract_listed_articles(soup)
    next_cursor = _extract_next_cursor(resp.text)

    return CursorPage(articles=articles, next_cursor=next_cursor)
