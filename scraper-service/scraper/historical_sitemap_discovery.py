"""Sitemap-based candidate-URL discovery for historical news backfill.

Each of these portals exposes a real, crawlable sitemap that -- unlike a
portal's live listing page -- still lists articles going back several
years. The sitemap `<lastmod>` values are NOT trusted as real publish dates
(confirmed during research: nepsekhabar's and myrepublica's are batch/
generation timestamps, annapurnapost's only covers back to ~2023-02 and its
own sitemap doesn't reach 2021). Discovery therefore only extracts the
candidate article URLs; the real published_at is read from each article
page individually later (see historical_article_extractor.extract_article),
same as the GDELT-based path.

Only portals confirmed, by directly fetching real article pages (not just
checking sitemap/pagination structure), to expose a genuine, trustworthy
per-article publish date are wired up here:
  - karobardaily.com : sitemap_index.xml -> ~400 post-sitemapN.xml files,
    confirmed to reach back to 2020-09; article pages carry a real, distinct
    article:published_time / JSON-LD datePublished per article.
  - myrepublica.nagariknetwork.com : sitemap.xml -> sitemap_1..6.xml bulk
    files (no dates, ~50k urls each) plus monthly sitemap_YYYYMM.xml files;
    article pages' JSON-LD datePublished is real and distinct per article
    (the <time datetime> element is NOT reliable here -- confirmed it
    reflects a "last rendered" date instead, which is why
    historical_article_extractor prioritizes JSON-LD over <time>).
  - thehimalayantimes.com : robots.txt -> /sitemaps/sitemap_0.xml (a
    sitemap index) -> one sub-sitemap per YEAR/MONTH at
    /sitemaps/{year}/{month}/sitemap_0.xml?v=1.1 (confirmed via 2026-08-31
    research: the index lists ~225 year/month combos back to 2002; months
    with zero articles return HTTP 200 with an empty <urlset></urlset>
    rather than 404 -- NOT an error, just genuinely zero articles that
    month, skip and continue). Confirmed real, trustworthy per-article
    dates: the sub-sitemap's own <lastmod> matched the fetched article
    page's article:published_time/JSON-LD/on-page date across 3
    independently sampled 2014 articles (unlike karobardaily/myrepublica,
    this portal's sitemap lastmod is NOT a fake/batch timestamp).

Two other portals were investigated and explicitly rejected after
per-article verification, despite having seemingly-usable sitemaps:
  - nepsekhabar.com : every article's article:published_time meta tag
    returns the current server time regardless of the article's actual
    age (confirmed on multiple distinct articles/URLs) -- a template bug
    on their end with no other machine-readable date available. No
    reliable date source exists for this portal.
  - annapurnapost.com : same class of bug -- every article's Nepali
    Bikram-Sambat date text (`.ap__headerDate`, its only date field at all)
    renders as today's date regardless of the article's real content or
    story ID (confirmed across 5+ distinct story IDs). No reliable date
    source exists for this portal either.

sharesansar.com is NOT discovered via sitemap (see
historical_cursor_scraper.py instead) -- its own article pages have the
exact same "fake date" bug (a hardcoded constant on every article), but its
*listing* page carries a real, distinct, trustworthy per-article date next
to each headline, which that module uses instead.

nepsealpha.com, ratopati.com, ekantipur.com are known Cloudflare-gated from
this environment and are intentionally NOT included -- see
scripts/nepsealpha-scraper/README.md and this backfill's own design notes
for why headless-browser handling was deferred rather than attempted here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable
from xml.etree import ElementTree

import requests


@dataclass(frozen=True)
class RankedUrl:
    url: str
    # Higher = likely older. 0 when the portal has no reliable per-URL age
    # signal at discovery time (see HistoricalBackfillUrl.discovery_rank).
    rank: int = 0

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ne;q=0.8",
}

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _fetch_xml(url: str, timeout: int) -> ElementTree.Element | None:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return ElementTree.fromstring(resp.content)
    except Exception as e:
        print(f"[SitemapDiscovery] Failed to fetch/parse {url}: {e}")
        return None


def _locs(root: ElementTree.Element) -> list[str]:
    return [el.text.strip() for el in root.findall(".//sm:loc", _SITEMAP_NS) if el.text]


@dataclass(frozen=True)
class SitemapPortalSpec:
    source: str
    tier: str
    # Returns every candidate article URL for this portal, each tagged with
    # its discovery rank (see RankedUrl). Takes a request timeout; does its
    # own pagination/sub-sitemap walking internally. This is a bulk,
    # cheap-per-request (small XML files) operation -- NOT rate limited the
    # way per-article fetches are, since it never touches the article pages
    # themselves.
    discover_urls: Callable[[int], list[RankedUrl]]
    # Cheap substring/prefix filter applied to sitemap <loc> entries to keep
    # only real article URLs (drop tag/category/author/static pages).
    url_looks_like_article: Callable[[str], bool]


def _karobardaily_discover(timeout: int) -> list[RankedUrl]:
    index_root = _fetch_xml("https://www.karobardaily.com/sitemap_index.xml", timeout)
    if index_root is None:
        return []

    sub_sitemaps = [
        loc for loc in _locs(index_root) if "/post-sitemap" in loc
    ]

    # post-sitemapN.xml is reliably numbered newest (N=1) to oldest (higher
    # N) -- confirmed during research, N~408 reaches back to 2020-09. Rank
    # each URL by its sub-sitemap's own N so the claim queue can process
    # probably-older sub-sitemaps first.
    ranked: list[RankedUrl] = []
    for sub_url in sub_sitemaps:
        match = re.search(r"post-sitemap(\d+)\.xml", sub_url)
        rank = int(match.group(1)) if match else 0

        sub_root = _fetch_xml(sub_url, timeout)
        if sub_root is None:
            continue
        ranked.extend(RankedUrl(url=u, rank=rank) for u in _locs(sub_root))

    print(f"[SitemapDiscovery] karobardaily: {len(sub_sitemaps)} sub-sitemaps, {len(ranked)} candidate urls")
    return ranked


def _karobardaily_is_article(url: str) -> bool:
    return "/news/" in url


def _myrepublica_discover(timeout: int) -> list[RankedUrl]:
    index_root = _fetch_xml(
        "https://myrepublica.nagariknetwork.com/sitemap.xml", timeout
    )
    if index_root is None:
        return []

    sub_sitemaps = _locs(index_root)

    # No reliable per-sub-sitemap age ordering here (unlike karobardaily) --
    # the bulk sitemap_1..6.xml files aren't cleanly date-ordered among
    # themselves (confirmed: sitemap_1.xml contained a mix including very
    # old content when sampled during research). Every URL gets the default
    # rank=0, so myrepublica keeps its current discovery-order processing.
    ranked: list[RankedUrl] = []
    for sub_url in sub_sitemaps:
        sub_root = _fetch_xml(sub_url, timeout)
        if sub_root is None:
            continue
        ranked.extend(RankedUrl(url=u) for u in _locs(sub_root))

    print(f"[SitemapDiscovery] myrepublica: {len(sub_sitemaps)} sub-sitemaps, {len(ranked)} candidate urls")
    return ranked


def _myrepublica_is_article(url: str) -> bool:
    return "/news/" in url or "/amp/news/" in url


def _himalayantimes_discover(timeout: int) -> list[RankedUrl]:
    index_root = _fetch_xml("https://thehimalayantimes.com/sitemaps/sitemap_0.xml", timeout)
    if index_root is None:
        return []

    # The index emits a double-slash ("https://thehimalayantimes.com//sitemaps/...")
    # which is harmless -- most HTTP clients normalize it -- but fix it up
    # explicitly to avoid depending on that behavior.
    year_month_sitemaps = [loc.replace(".com//sitemaps/", ".com/sitemaps/") for loc in _locs(index_root)]

    # Rank by how far in the past the year/month is (higher rank = older),
    # parsed straight from the URL path, so the claim queue processes
    # oldest months first -- same "oldest first" principle as
    # karobardaily's post-sitemap ranking, just derived from the URL
    # instead of a chunk number.
    ranked: list[RankedUrl] = []
    for sub_url in year_month_sitemaps:
        match = re.search(r"/sitemaps/(\d{4})/(\d{1,2})/", sub_url)
        if match:
            year, month = int(match.group(1)), int(match.group(2))
            rank = (9999 - year) * 12 + (12 - month)
        else:
            rank = 0

        sub_root = _fetch_xml(sub_url, timeout)
        if sub_root is None:
            continue
        # Confirmed via research: a month with zero articles returns a
        # real HTTP 200 with an empty <urlset></urlset>, not a 404 -- this
        # naturally yields zero URLs from _locs() and the loop just moves
        # on, no special-casing needed.
        ranked.extend(RankedUrl(url=u, rank=rank) for u in _locs(sub_root))

    print(
        f"[SitemapDiscovery] himalayantimes: {len(year_month_sitemaps)} year/month sub-sitemaps, "
        f"{len(ranked)} candidate urls"
    )
    return ranked


def _himalayantimes_is_article(url: str) -> bool:
    # Article URLs are /<category>/<slug> (e.g. /nepal/fruitless-war-...).
    # Exclude the sitemap/static asset paths that could theoretically
    # appear in a urlset by mistake.
    return "thehimalayantimes.com/" in url and "/sitemaps/" not in url


PORTALS: tuple[SitemapPortalSpec, ...] = (
    SitemapPortalSpec(
        source="karobardaily",
        tier="finance",
        discover_urls=_karobardaily_discover,
        url_looks_like_article=_karobardaily_is_article,
    ),
    SitemapPortalSpec(
        source="myrepublica",
        tier="general",
        discover_urls=_myrepublica_discover,
        url_looks_like_article=_myrepublica_is_article,
    ),
    SitemapPortalSpec(
        source="himalayantimes",
        tier="general",
        discover_urls=_himalayantimes_discover,
        url_looks_like_article=_himalayantimes_is_article,
    ),
)

PORTALS_BY_SOURCE: dict[str, SitemapPortalSpec] = {p.source: p for p in PORTALS}


def discover_portal_urls(source: str, timeout: int = 20) -> list[RankedUrl]:
    """Discover + filter candidate article URLs for one portal, each
    tagged with its discovery rank (see RankedUrl)."""
    spec = PORTALS_BY_SOURCE.get(source)
    if spec is None:
        raise ValueError(f"Unknown sitemap-discovery portal: {source}")

    all_ranked = spec.discover_urls(timeout)
    filtered = [r for r in all_ranked if spec.url_looks_like_article(r.url)]

    # Dedup while preserving order (sitemaps can legitimately repeat a url
    # across sub-sitemaps, e.g. if a post was updated and re-indexed) --
    # keep the FIRST occurrence's rank, matching prior dedup semantics.
    seen: set[str] = set()
    deduped: list[RankedUrl] = []
    for r in filtered:
        if r.url in seen:
            continue
        seen.add(r.url)
        deduped.append(r)

    print(
        f"[SitemapDiscovery] {source}: {len(all_ranked)} raw -> "
        f"{len(filtered)} article-like -> {len(deduped)} deduped"
    )
    return deduped
