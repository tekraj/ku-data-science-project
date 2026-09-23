"""
20 Nepali news portal scrapers using BeautifulSoup (as required).

TIER 1 — Finance/NEPSE focused (highest market impact):
  1.  merolagani.com
  2.  sharesansar.com
  3.  nepsealpha.com
  4.  nepsekhabar.com
  5.  nepalipaisa.com
  6.  karobardaily.com
  7.  arthikabhiyan.com
  8.  biznessnews.com (Biznews Nepal)
  9.  stocknepali.com  (Stock Nepal)
  10. nepsetrading.com

TIER 2 — General news that affects NEPSE (politics, economy, policy):
  11. onlinekhabar.com
  12. setopati.com
  13. ratopati.com
  14. ekantipur.com
  15. nagariknews.com
  16. thehimalayantimes.com
  17. myrepublica.com
  18. republica.com
  19. annapurnapost.com
  20. nepalilive.com
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from scraper.nepali_bs_date import parse_bs_date_text

# ── Shared helpers ──────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ne;q=0.8",
}


def _get(url: str, timeout: int = 15) -> BeautifulSoup | None:
    """Fetch a URL and return a BeautifulSoup object, or None on failure."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"[Scraper] Failed to fetch {url}: {e}")
        return None


def _clean(text: str | None) -> str:
    """Strip and collapse whitespace."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _extract_text(tag) -> str:
    """Extract readable text from a BeautifulSoup tag (including meta tags)."""
    if tag is None:
        return ""
    if getattr(tag, "name", "") == "meta":
        return _clean(tag.get("content", ""))
    return _clean(tag.get_text())


def _normalize_href(base_url: str, href: str) -> str | None:
    """Normalize href safely and skip non-article pseudo links."""
    raw = (href or "").strip()
    if not raw:
        return None

    lowered = raw.lower()
    if lowered.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None

    absolute = urljoin(base_url, raw).split("#", 1)[0]
    if "/cdn-cgi/" in absolute.lower():
        return None
    return absolute


def _parse_dt(tag) -> datetime | None:
    """Try to parse a <time datetime="..."> tag."""
    if tag is None:
        return None
    dt_str = tag.get("datetime", "")
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _parse_plain_date_text(text: str, fmt: str) -> datetime | None:
    """Parse a plain (non-<time>-tag) date string, e.g. merolagani's
    "Jun 29, 2026 02:05 PM" span -- confirmed during backfill research
    that this real, machine-parseable AD date exists on the page, just not
    inside a <time datetime> attribute the way time_sel expects."""
    if not text:
        return None
    try:
        return datetime.strptime(_clean(text), fmt)
    except Exception:
        return None


def _parse_url_year_month(url: str, pattern: str) -> datetime | None:
    """Fallback for portals with NO machine-readable date anywhere on the
    article page at all (confirmed: onlinekhabar.com) but whose URL itself
    encodes year/month, e.g. /YYYY/MM/<id>/<slug>. Anchors to the 1st of
    the month rather than guessing a day -- coarse but honest
    month-precision beats no date at all."""
    match = re.search(pattern, url)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), 1)
    except Exception:
        return None


def _build_article(source: str, tier: str, url: str, title: str,
                   body: str, category: str, published_at) -> dict[str, Any]:
    return {
        "source": source,
        "portal_tier": tier,
        "url": url,
        "title": title,
        "body": body[:3000],
        "category": category,
        "published_at": published_at,
    }


def _generic_scraper(
    source: str,
    tier: str,
    base_url: str,
    link_pattern: str,
    title_sel: str,
    body_sel: str,
    category_sel: str,
    time_sel: str,
    timeout: int,
    max_articles: int,
    plain_date_sel: str | None = None,
    plain_date_format: str | None = None,
    bs_date_sel: str | None = None,
    url_date_pattern: str | None = None,
) -> list[dict[str, Any]]:
    """
    Generic scraper: hits base_url, finds article links matching link_pattern,
    visits each one and extracts title/body/category/time using CSS selectors.

    Date extraction tries, in order: time_sel (a <time datetime=...> tag),
    then plain_date_sel+plain_date_format (a plain-text date/time span --
    confirmed needed for merolagani, whose real date isn't in a <time>
    tag), then bs_date_sel (a Nepali Bikram-Sambat date span, converted to
    AD -- confirmed needed for setopati), then url_date_pattern (a
    year/month regex against the article URL itself -- confirmed needed
    for onlinekhabar, which has no machine-readable date anywhere on the
    page at all). Each fallback is optional and only tried if the
    preceding ones yielded nothing.
    """
    soup = _get(base_url, timeout)
    if soup is None:
        return []

    articles: list[dict[str, Any]] = []
    seen: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        href = _normalize_href(base_url, a_tag["href"])
        if not href:
            continue
        if href in seen:
            continue
        if not re.search(link_pattern, href):
            continue
        seen.add(href)

        detail = _get(href, timeout)
        if detail is None:
            continue

        title_tag = detail.select_one(title_sel)
        body_tags = detail.select(body_sel)
        cat_tag   = detail.select_one(category_sel)
        time_tag  = detail.select_one(time_sel)

        title    = _extract_text(title_tag)
        body     = _clean(" ".join(p.get_text() for p in body_tags))
        category = _extract_text(cat_tag)
        pub_at   = _parse_dt(time_tag)

        if pub_at is None and plain_date_sel and plain_date_format:
            plain_tag = detail.select_one(plain_date_sel)
            if plain_tag is not None:
                pub_at = _parse_plain_date_text(plain_tag.get_text(" ", strip=True), plain_date_format)

        if pub_at is None and bs_date_sel:
            bs_tag = detail.select_one(bs_date_sel)
            if bs_tag is not None:
                pub_at = parse_bs_date_text(bs_tag.get_text(" ", strip=True))

        if pub_at is None and url_date_pattern:
            pub_at = _parse_url_year_month(href, url_date_pattern)

        if not title:
            continue

        articles.append(_build_article(source, tier, href, title, body, category, pub_at))

        if len(articles) >= max_articles:
            break

    print(f"[Scraper] {source}: {len(articles)} articles")
    return articles


# ══════════════════════════════════════════════════════════════════════════════
# TIER 1 — Finance / NEPSE portals
# ══════════════════════════════════════════════════════════════════════════════

def scrape_merolagani(timeout=15, max_articles=20):
    return _generic_scraper(
        source="merolagani", tier="finance",
        base_url="https://merolagani.com/NewsList.aspx",
        link_pattern=r"merolagani\.com/NewsDetail\.aspx",
        title_sel="#ctl00_ContentPlaceHolder1_newsTitle, .media-title.newsTitle, meta[property='og:title'], h1",
        body_sel="#ctl00_ContentPlaceHolder1_newsDetail p, #ctl00_ContentPlaceHolder1_newsDetail, .media-content p, .media-content",
        category_sel="#ctl00_ContentPlaceHolder1_lblCategoryName, .breadcrumb a:last-child",
        time_sel="time[datetime]",
        # Confirmed during backfill research: the real publish date lives
        # in this plain <span>, e.g. "Jun 29, 2026 02:05 PM" -- there is no
        # <time datetime> element on this site at all, so time_sel alone
        # never matched and published_at was always None.
        plain_date_sel="#ctl00_ContentPlaceHolder1_newsDate",
        plain_date_format="%b %d, %Y %I:%M %p",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_sharesansar(timeout=15, max_articles=20):
    return _generic_scraper(
        source="sharesansar", tier="finance",
        base_url="https://www.sharesansar.com",
        link_pattern=r"sharesansar\.com/newsdetail/",
        title_sel="h1.newsdetail-header, h1",
        body_sel="div.newsdetail-content p",
        category_sel=".breadcrumb li:nth-child(2) a",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_nepsealpha(timeout=15, max_articles=20):
    return _generic_scraper(
        source="nepsealpha", tier="finance",
        base_url="https://nepsealpha.com/news",
        link_pattern=r"nepsealpha\.com/nepse-news/\d+",
        title_sel="h1.news-title, h1",
        body_sel="div.news-content p",
        category_sel=".tag a, .category a",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_nepsekhabar(timeout=15, max_articles=20):
    return _generic_scraper(
        source="nepsekhabar", tier="finance",
        base_url="https://nepsekhabar.com",
        link_pattern=r"nepsekhabar\.com/\d{4}/\d{2}",
        title_sel="h1.entry-title, h1",
        body_sel="div.entry-content p",
        category_sel=".breadcrumb a:nth-child(2)",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


def _nepalipaisa_fetch_body(news_id, timeout: int) -> str:
    """The GetNewsList (list) API's own overview/descriptions fields are
    confirmed always empty -- the real article body only exists behind
    this per-article detail endpoint, found by reading nepalipaisa's own
    news-detail.js bundle (NewsDetail.getNews -> GET /api/GetNews?newsId=).
    """
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
        print(f"[Scraper] nepalipaisa GetNews failed for newsId={news_id}: {e}")
        return ""

    result = payload.get("result") or {}
    descriptions = result.get("descriptions") or []
    html_parts = [d.get("description", "") for d in descriptions if isinstance(d, dict)]
    text_parts = [
        _clean(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
        for html in html_parts
        if html
    ]
    return _clean(" ".join(p for p in text_parts if p))


def scrape_nepalipaisa(timeout=15, max_articles=20):
    headers = {
        **_HEADERS,
        "Content-Type": "application/json; charset=utf-8",
        "Origin": "https://nepalipaisa.com",
        "Referer": "https://nepalipaisa.com/news/",
    }
    payload = {
        "dateType": "",
        "dateFrom": "",
        "dateTo": "",
        "sectors": [],
        "companies": [],
        "categoryId": 0,
        "subCategoryId": 0,
        "pageNo": 1,
        "itemsPerPage": max_articles,
        "pagePerDisplay": 10,
        "newsType": "",
        "sectorGroup": "",
    }

    try:
        resp = requests.post(
            "https://nepalipaisa.com/api/GetNewsList",
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[Scraper] nepalipaisa API failed: {e}")
        return []

    grouped = ((data.get("result") or {}).get("data") or [])
    articles: list[dict[str, Any]] = []
    seen: set[str] = set()

    for group in grouped:
        for item in (group.get("newsData") or []):
            news_id = item.get("newsId")
            if not news_id:
                continue

            url = f"https://nepalipaisa.com/news-detail/{news_id}"
            if url in seen:
                continue
            seen.add(url)

            title = _clean(item.get("newsTitle"))
            if not title:
                continue

            category = _clean(item.get("category") or item.get("subCategory"))

            body = _nepalipaisa_fetch_body(news_id, timeout)

            published_at = None
            date_text = (item.get("newsDate") or "").strip()
            if date_text:
                try:
                    published_at = datetime.fromisoformat(date_text)
                except Exception:
                    published_at = None

            articles.append(
                _build_article(
                    source="nepalipaisa",
                    tier="finance",
                    url=url,
                    title=title,
                    body=body,
                    category=category,
                    published_at=published_at,
                )
            )

            if len(articles) >= max_articles:
                break
        if len(articles) >= max_articles:
            break

    print(f"[Scraper] nepalipaisa: {len(articles)} articles")
    return articles


def scrape_karobardaily(timeout=15, max_articles=20):
    return _generic_scraper(
        source="karobardaily", tier="finance",
        base_url="https://karobardaily.com",
        link_pattern=r"karobardaily\.com/news/\d+",
        title_sel="h1.single-title, h1",
        body_sel="div.single-content p",
        category_sel=".breadcrumb span:nth-child(2)",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_arthikabhiyan(timeout=15, max_articles=20):
    return _generic_scraper(
        source="arthikabhiyan", tier="finance",
        base_url="https://arthikabhiyan.com",
        link_pattern=r"arthikabhiyan\.com/\d{4}/\d{2}/.+",
        title_sel="h1.entry-title, h1",
        body_sel="div.entry-content p",
        category_sel=".cat-links a",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_biznessnews(timeout=15, max_articles=20):
    return _generic_scraper(
        source="biznessnews", tier="finance",
        base_url="https://biznessnews.com",
        link_pattern=r"biznessnews\.com/\d{4}/\d{2}/.+",
        title_sel="h1.entry-title, h1",
        body_sel="div.entry-content p",
        category_sel=".cat-links a",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_stocknepali(timeout=15, max_articles=20):
    return _generic_scraper(
        source="stocknepali", tier="finance",
        base_url="https://www.stocknepali.com",
        link_pattern=r"stocknepali\.com/\d{4}/\d{2}/.+",
        title_sel="h1.entry-title, h1",
        body_sel="div.entry-content p",
        category_sel=".cat-links a",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_nepsetrading(timeout=15, max_articles=20):
    return _generic_scraper(
        source="nepsetrading", tier="finance",
        base_url="https://news.nepsetrading.com",
        link_pattern=r"nepsetrading\.com/\d{4}/\d{2}/.+",
        title_sel="h1.entry-title, h1",
        body_sel="div.entry-content p, article p",
        category_sel=".cat-links a, .breadcrumb a",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


# ══════════════════════════════════════════════════════════════════════════════
# TIER 2 — General news portals
# ══════════════════════════════════════════════════════════════════════════════

def scrape_onlinekhabar(timeout=15, max_articles=20):
    return _generic_scraper(
        source="onlinekhabar", tier="general",
        base_url="https://www.onlinekhabar.com",
        link_pattern=r"onlinekhabar\.com/\d{4}/\d{2}/\d+",
        title_sel="h1.ok18-single-post-content-title, h1",
        # Confirmed during backfill research: the live class name is
        # "-content-wrap", not "-content-section" -- the old selector
        # never matched anything on current site markup, so body was
        # always empty for this source.
        body_sel="div.ok18-single-post-content-wrap p",
        category_sel="a.ok18-breadcrumb-link",
        time_sel="time[datetime]",
        # onlinekhabar has NO machine-readable date anywhere on the article
        # page (no <time>, no meta tag, no JSON-LD) -- confirmed directly.
        # The URL itself encodes year/month (/YYYY/MM/<id>/<slug>), used
        # here as a month-precision fallback; exact day isn't recoverable.
        url_date_pattern=r"onlinekhabar\.com/(\d{4})/(\d{2})/",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_setopati(timeout=15, max_articles=20):
    return _generic_scraper(
        source="setopati", tier="general",
        base_url="https://www.setopati.com",
        link_pattern=r"setopati\.com/.+/\d+$",
        title_sel="h1.news-title, h1",
        # Confirmed during backfill research: "div.news-description" no
        # longer exists on current site markup -- the real body container
        # is ".detail-box".
        body_sel=".detail-box p",
        category_sel="div.breadcrumb a:nth-child(2)",
        time_sel="time[datetime]",
        # setopati has no machine-readable date either -- only a Nepali BS
        # date in ".pub-date" (e.g. "प्रकाशित मिति: बिहीबार, असार १८,
        # २०८३"), converted to AD via nepali_bs_date.parse_bs_date_text.
        bs_date_sel=".pub-date",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_ratopati(timeout=15, max_articles=20):
    return _generic_scraper(
        source="ratopati", tier="general",
        base_url="https://ratopati.com",
        link_pattern=r"ratopati\.com/story/\d+",
        title_sel="h1.news-title, h1",
        body_sel="div.news-body p",
        category_sel="ul.breadcrumb li:nth-child(2) a",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_ekantipur(timeout=15, max_articles=20):
    return _generic_scraper(
        source="ekantipur", tier="general",
        base_url="https://ekantipur.com",
        link_pattern=r"ekantipur\.com/.+/news/.+",
        title_sel="h1.heading, h1",
        body_sel="div.current-news-block p",
        category_sel="ul.breadcrumb li:nth-child(2) a",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_nagariknews(timeout=15, max_articles=20):
    return _generic_scraper(
        source="nagariknews", tier="general",
        base_url="https://nagariknews.nagariknetwork.com",
        link_pattern=r"nagariknews\.nagariknetwork\.com/news/\d+",
        title_sel="h1.single-post-title, h1",
        body_sel="div.single-post-content p",
        category_sel=".breadcrumb a:last-child",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_himalayantimes(timeout=15, max_articles=20):
    return _generic_scraper(
        source="himalayantimes", tier="general",
        base_url="https://thehimalayantimes.com",
        link_pattern=r"thehimalayantimes\.com/.+/.+/$",
        title_sel="h1.entry-title, h1",
        body_sel="div.entry-content p",
        category_sel=".breadcrumb a:nth-child(2)",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_myrepublica(timeout=15, max_articles=20):
    return _generic_scraper(
        source="myrepublica", tier="general",
        base_url="https://myrepublica.nagariknetwork.com",
        link_pattern=r"myrepublica\.nagariknetwork\.com/news/\d+",
        title_sel="h1.single-post-title, h1",
        body_sel="div.single-post-content p",
        category_sel=".breadcrumb a:last-child",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_republica(timeout=15, max_articles=20):
    return _generic_scraper(
        source="republica", tier="general",
        base_url="https://myrepublica.nagariknetwork.com",
        link_pattern=r"myrepublica\.nagariknetwork\.com/news/\d+",
        title_sel="h1.single-post-title, h1",
        body_sel="div.single-post-content p",
        category_sel=".breadcrumb a:last-child",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_annapurnapost(timeout=15, max_articles=20):
    return _generic_scraper(
        source="annapurnapost", tier="general",
        base_url="https://annapurnapost.com",
        link_pattern=r"annapurnapost\.com/news/\d+",
        title_sel="h1.single-title, h1",
        body_sel="div.single-content p",
        category_sel=".breadcrumb a:nth-child(2)",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


def scrape_nepalilive(timeout=15, max_articles=20):
    return _generic_scraper(
        source="nepalilive", tier="general",
        base_url="https://www.nepallive.com",
        link_pattern=r"nepallive\.com/news/\d+",
        title_sel="h1.single-title, h1",
        body_sel="div.entry-content p",
        category_sel=".cat-links a",
        time_sel="time[datetime]",
        timeout=timeout, max_articles=max_articles,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Registry — all 20 scrapers in one list
# ══════════════════════════════════════════════════════════════════════════════

ALL_SCRAPERS = [
    # Tier 1 — Finance
    scrape_merolagani,
    scrape_sharesansar,
    scrape_nepsealpha,
    scrape_nepsekhabar,
    scrape_nepalipaisa,
    scrape_karobardaily,
    scrape_arthikabhiyan,
    scrape_biznessnews,
    scrape_stocknepali,
    scrape_nepsetrading,
    # Tier 2 — General
    scrape_onlinekhabar,
    scrape_setopati,
    scrape_ratopati,
    scrape_ekantipur,
    scrape_nagariknews,
    scrape_himalayantimes,
    scrape_myrepublica,
    scrape_republica,
    scrape_annapurnapost,
    scrape_nepalilive,
]


def scrape_all(timeout: int = 15, max_articles_per_portal: int = 20) -> list[dict[str, Any]]:
    """Run all 20 scrapers and return combined article list."""
    results: list[dict[str, Any]] = []
    for scraper_fn in ALL_SCRAPERS:
        try:
            results.extend(scraper_fn(timeout=timeout, max_articles=max_articles_per_portal))
        except Exception as e:
            print(f"[Scraper] {scraper_fn.__name__} crashed: {e}")
    print(f"[Scraper] Total collected this run: {len(results)} articles from {len(ALL_SCRAPERS)} portals")
    return results
