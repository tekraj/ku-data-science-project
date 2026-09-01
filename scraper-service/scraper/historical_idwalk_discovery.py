"""Sequential-numeric-ID discovery for historical news backfill.

Unlike historical_sitemap_discovery.py (which lists candidate URLs from a
sitemap up front), these portals have NO sitemap and NO date-archive
listing that reaches old content -- the only way to find an old article is
to guess its numeric ID directly and fetch it. Confirmed via a dedicated
overnight research pass (2026-08-31) across 20 portals, specifically aimed
at reaching calendar year 2014:

  - setopati.com : articles live at /social/{id} (a shared ID pool across
    category prefixes). ID~7500 = 2014-01-15, ID~22800 = 2014-12-31 (dense
    real-page calibration, ~20 sample points). Real date lives in
    `.pub-date`, but the format is NOT stable across the site's history:
    old articles (this range) render plain Gregorian text
    ("प्रकाशित मिति: 2014-01-15 14:29:18"); the live scraper's current
    articles render Nepali BS text with a weekday prefix instead
    ("प्रकाशित मिति: बिहीबार, असार १८, २०८३"). Both forms are parsed here.
  - merolagani.com : articles live at
    NewsDetail.aspx?newsID={id}. The ID space is SPARSE -- most IDs below
    ~6376 render an empty template (no title, no date) rather than a 404,
    confirmed by dense sampling across the entire 1-6375 range. ID 6376 is
    the practical floor of the site's content (2014-08-15); 2014 runs
    roughly 6376-9000ish. Real date lives in
    `#ctl00_ContentPlaceHolder1_newsDate` as plain AD text (e.g.
    "Oct 06, 2014"), same field/format the live-scraper fix already uses.
  - onlinekhabar.com : no sitemap, and the WordPress /YYYY/MM/ date-archive
    LISTING only works from 2023-08 onward (a taxonomy/index limitation,
    not a content one) -- but WordPress's own `?p={id}` canonical
    short-link redirect/canonical-tag STILL resolves any post ID directly
    to its real permalink/date regardless of age. ID~185000 = 2014-08,
    ID~195000 = 2014-10 (calibration curve from research). A fetched page
    is a real article only if `<body class="...single-post...">` appears
    (filters out attachment/custom-post-type IDs interleaved in the same
    numbering space).

Each of these returns RankedUrl-shaped output (matching
historical_sitemap_discovery.RankedUrl's shape) so the same
historical_backfill_urls queue/claim/rank machinery applies unchanged --
"rank" here is the numeric ID itself (bounded to the portal's calibrated
2014 bracket), which already IS the age signal, no separate ranking logic
needed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

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
class IdWalkResult:
    exists: bool  # False if this id has no real article at all (skip, don't count as end-of-data)
    url: str | None
    title: str | None
    body: str | None
    category: str | None
    published_at: datetime | None


@dataclass(frozen=True)
class IdWalkPortalSpec:
    source: str
    tier: str
    # Calibrated ID bracket covering (roughly) all of calendar year 2014 --
    # see module docstring for how each was derived. A little headroom is
    # included on both ends since the calibration points were samples, not
    # exact boundaries.
    id_range_start: int
    id_range_end: int
    fetch: Callable[[int, int], IdWalkResult]  # (id, timeout) -> result


# ── setopati.com ─────────────────────────────────────────────────────────

_SETOPATI_URL_TEMPLATE = "https://www.setopati.com/social/{id}"
# "प्रकाशित मिति: 2014-01-15 14:29:18" -- plain Gregorian, used by old articles.
_SETOPATI_GREGORIAN_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})")


def _setopati_fetch(article_id: int, timeout: int) -> IdWalkResult:
    url = _SETOPATI_URL_TEMPLATE.format(id=article_id)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    except Exception as e:
        print(f"[IdWalk] setopati id={article_id} fetch error: {e}")
        return IdWalkResult(False, None, None, None, None, None)

    if resp.status_code == 404:
        return IdWalkResult(False, None, None, None, None, None)
    resp.raise_for_status()
    resp.encoding = "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")

    # setopati's page template has changed over the years: current articles
    # have a real <h1> and .detail-box p paragraphs (see
    # nepse_news_fields_backfill.py's _setopati), but articles from this
    # portal's 2014-era archive use an older template where the only <h1>
    # is a nav/footer "सम्पर्क" (Contact) link and .detail-box's real text
    # sits directly in the container with no <p> children at all --
    # confirmed directly against a live 2014 article. og:title and the
    # container's own get_text() work correctly on BOTH templates, so use
    # those instead of assuming either template's specific structure.
    og_title_el = soup.select_one("meta[property='og:title']")
    title = _clean(og_title_el.get("content")) if og_title_el else ""
    if not title:
        title_el = soup.select_one("title")
        title = _clean(title_el.get_text(strip=True)) if title_el else ""
    if not title:
        return IdWalkResult(False, None, None, None, None, None)

    detail_el = soup.select_one(".detail-box")
    body = _clean(detail_el.get_text(" ", strip=True))[:3000] if detail_el else ""

    published_at = None
    date_el = soup.select_one(".pub-date")
    if date_el is not None:
        date_text = date_el.get_text(" ", strip=True)
        greg_match = _SETOPATI_GREGORIAN_RE.search(date_text)
        if greg_match:
            try:
                published_at = datetime.strptime(
                    f"{greg_match.group(1)} {greg_match.group(2)}", "%Y-%m-%d %H:%M:%S"
                )
            except Exception:
                published_at = None
        if published_at is None:
            published_at = parse_bs_date_text(date_text)

    return IdWalkResult(True, url, title, body or None, "", published_at)


# ── merolagani.com ───────────────────────────────────────────────────────

_MEROLAGANI_URL_TEMPLATE = "https://merolagani.com/NewsDetail.aspx?newsID={id}"
_MEROLAGANI_DATE_FORMAT = "%b %d, %Y"


def _merolagani_fetch(article_id: int, timeout: int) -> IdWalkResult:
    url = _MEROLAGANI_URL_TEMPLATE.format(id=article_id)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except Exception as e:
        print(f"[IdWalk] merolagani id={article_id} fetch error: {e}")
        return IdWalkResult(False, None, None, None, None, None)

    soup = BeautifulSoup(resp.text, "html.parser")

    # The ID space is sparse: most low IDs render a real 200 page with an
    # EMPTY template (no title, no date) rather than a 404 -- confirmed by
    # research across the entire 1-6375 range. Treat empty-title as
    # not-a-real-article, not as an error or end-of-data.
    title_el = soup.select_one("#ctl00_ContentPlaceHolder1_newsTitle")
    title = _clean(title_el.get_text(" ", strip=True)) if title_el else ""
    if not title:
        return IdWalkResult(False, None, None, None, None, None)

    # Same template-drift issue as setopati (see its matching comment):
    # 2014-era merolagani article pages have no <p> children inside the
    # detail container at all -- the body text sits directly in it.
    # Prefer <p> children when present (today's articles have them, and
    # they give cleaner paragraph-separated text), fall back to the
    # container's own text otherwise.
    detail_el = soup.select_one("#ctl00_ContentPlaceHolder1_newsDetail")
    body_parts = [_clean(p.get_text(" ", strip=True)) for p in (detail_el.select("p") if detail_el else [])]
    body_parts = [p for p in body_parts if p]
    body = _clean(" ".join(body_parts)) if body_parts else (_clean(detail_el.get_text(" ", strip=True)) if detail_el else "")
    body = body[:3000]

    published_at = None
    date_el = soup.select_one("#ctl00_ContentPlaceHolder1_newsDate")
    if date_el is not None:
        date_text = _clean(date_el.get_text(" ", strip=True))
        # Old articles show a bare date with no time ("Oct 06, 2014"); the
        # live scraper's own format includes a time ("Jun 29, 2026 02:05
        # PM") -- try the with-time format first, then fall back to
        # date-only, rather than assuming either.
        for fmt in (f"{_MEROLAGANI_DATE_FORMAT} %I:%M %p", _MEROLAGANI_DATE_FORMAT):
            try:
                published_at = datetime.strptime(date_text, fmt)
                break
            except Exception:
                continue

    category_el = soup.select_one("#ctl00_ContentPlaceHolder1_lblCategoryName")
    category = _clean(category_el.get_text(" ", strip=True)) if category_el else ""

    return IdWalkResult(True, url, title, body or None, category, published_at)


# ── onlinekhabar.com ─────────────────────────────────────────────────────

_ONLINEKHABAR_SHORTLINK_TEMPLATE = "https://www.onlinekhabar.com/?p={id}"


def _onlinekhabar_fetch(article_id: int, timeout: int) -> IdWalkResult:
    shortlink = _ONLINEKHABAR_SHORTLINK_TEMPLATE.format(id=article_id)
    try:
        resp = requests.get(shortlink, headers=_HEADERS, timeout=timeout, allow_redirects=True)
    except Exception as e:
        print(f"[IdWalk] onlinekhabar id={article_id} fetch error: {e}")
        return IdWalkResult(False, None, None, None, None, None)

    if resp.status_code == 404:
        return IdWalkResult(False, None, None, None, None, None)
    resp.raise_for_status()
    resp.encoding = "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")

    # Confirmed via research: the id-number space interleaves real articles
    # with attachment/custom-post-type pages. `single-post` in <body class>
    # is present only on genuine articles.
    body_tag = soup.select_one("body")
    body_classes = body_tag.get("class", []) if body_tag else []
    if "single-post" not in body_classes:
        return IdWalkResult(False, None, None, None, None, None)

    canonical_el = soup.select_one("link[rel='canonical']")
    real_url = canonical_el.get("href") if canonical_el else resp.url

    title_el = soup.select_one("h1.ok18-single-post-content-title") or soup.select_one("h1")
    title = _clean(title_el.get_text(" ", strip=True)) if title_el else ""
    if not title:
        return IdWalkResult(False, None, None, None, None, None)

    body_parts = [
        _clean(p.get_text(" ", strip=True))
        for p in soup.select("div.ok18-single-post-content-wrap p")
    ]
    body = _clean(" ".join(p for p in body_parts if p))[:3000]

    category_el = soup.select_one("a.ok18-breadcrumb-link")
    category = _clean(category_el.get_text(" ", strip=True)) if category_el else ""

    # The real URL's own /YYYY/MM/ segment is the date signal here (same
    # mechanism the live-scraper fix already uses for this portal) -- month
    # precision, exact day isn't recoverable, but this ID-walk is already
    # targeting a specific calibrated month bracket so the imprecision is
    # bounded and acceptable.
    published_at = None
    match = re.search(r"onlinekhabar\.com/(\d{4})/(\d{2})/", real_url or "")
    if match:
        published_at = datetime(int(match.group(1)), int(match.group(2)), 1)

    return IdWalkResult(True, real_url, title, body or None, category, published_at)


PORTALS: tuple[IdWalkPortalSpec, ...] = (
    IdWalkPortalSpec(
        source="setopati",
        tier="general",
        id_range_start=7000,
        id_range_end=23200,
        fetch=_setopati_fetch,
    ),
    IdWalkPortalSpec(
        source="merolagani",
        tier="finance",
        id_range_start=6300,
        id_range_end=9200,
        fetch=_merolagani_fetch,
    ),
    IdWalkPortalSpec(
        source="onlinekhabar",
        tier="general",
        id_range_start=152000,
        id_range_end=218000,
        fetch=_onlinekhabar_fetch,
    ),
)

PORTALS_BY_SOURCE: dict[str, IdWalkPortalSpec] = {p.source: p for p in PORTALS}
