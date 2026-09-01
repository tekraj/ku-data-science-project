from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from temporalio import activity

from nepse_common.config import load_app_config
from nepse_common.db.session import session_scope
from nepse_common.models import NewsArticle
from nepse_common.schemas.scraped import ScrapedArticle

from scraper.scrapers import scrape_all


@activity.defn
async def scrape_news_activity(
    timeout: int, max_articles_per_portal: int
) -> list[dict[str, Any]]:
    """Run all 20 portal scrapers (unchanged business logic) and return
    validated, JSON-serializable article dicts.

    scrape_all is synchronous (blocking requests.get() across 20 portals)
    -- run it via asyncio.to_thread so it can't freeze the shared asyncio
    event loop other workflows/activities in this process depend on (see
    the matching note on scrape_historical_day_activity, where this exact
    pattern was confirmed to cause a multi-minute worker-wide stall)."""
    raw_articles = await asyncio.to_thread(
        scrape_all,
        timeout=timeout,
        max_articles_per_portal=max_articles_per_portal,
    )

    validated: list[dict[str, Any]] = []
    for raw in raw_articles:
        article = ScrapedArticle.model_validate(raw)
        # mode="json" ensures datetimes serialize to ISO strings so the
        # result crosses the Temporal data-converter boundary cleanly.
        validated.append(article.model_dump(mode="json"))

    return validated


@activity.defn
async def write_articles_activity(articles: list[dict[str, Any]]) -> int:
    """Insert articles into nepse_news, deduplicating by url via
    ON CONFLICT DO NOTHING (matches old db/writer.py write_articles()
    semantics). Returns the count of NEWLY inserted rows only, obtained via
    a RETURNING clause since plain rowcount is unreliable with
    on_conflict_do_nothing."""
    if not articles:
        return 0

    config = load_app_config()

    records = [
        {
            "source": a["source"],
            "portal_tier": a.get("portal_tier", "general"),
            "url": a["url"],
            "title": a.get("title"),
            "body": a.get("body"),
            "category": a.get("category"),
            "published_at": a.get("published_at"),
        }
        for a in articles
    ]

    with session_scope(config.database) as session:
        stmt = (
            pg_insert(NewsArticle)
            .values(records)
            .on_conflict_do_nothing(index_elements=["url"])
            .returning(NewsArticle.id)
        )
        result = session.execute(stmt)
        inserted = len(result.fetchall())

    activity.logger.info(f"[DB] Inserted {inserted} new articles.")
    return inserted
