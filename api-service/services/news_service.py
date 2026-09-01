from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from nepse_common.models import NewsArticle
from nepse_common.schemas.util import to_iso


def _cutoff(hours: int):
    """Server-side `NOW() - interval`, matching the old raw-SQL cutoff exactly.

    scraped_at is a naive TIMESTAMP populated via Postgres' NOW() in the
    session's configured timezone (PGTZ=Asia/Kathmandu). Computing the cutoff
    in Python as a tz-aware UTC datetime and comparing it against that naive
    column would trigger an implicit timestamptz->timestamp cast using the
    session timezone, shifting the effective window by the server's UTC
    offset. Doing the subtraction in SQL avoids that entirely.
    """
    return func.now() - text(f"'{hours} hours'::interval")


class NewsService:
    """Article/news queries against nepse_common.models.NewsArticle."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_recent_articles(self, hours: int, tier: str, limit: int) -> dict[str, Any]:
        """Matches old GET /articles."""
        cutoff = _cutoff(hours)

        stmt = select(
            NewsArticle.source,
            NewsArticle.portal_tier,
            NewsArticle.title,
            NewsArticle.category,
            NewsArticle.url,
            NewsArticle.scraped_at,
        ).where(NewsArticle.scraped_at >= cutoff)

        if tier in ("finance", "general"):
            stmt = stmt.where(NewsArticle.portal_tier == tier)

        stmt = stmt.order_by(NewsArticle.scraped_at.desc()).limit(limit)

        rows = self._db.execute(stmt).all()

        return {
            "window_hours": hours,
            "total": len(rows),
            "articles": [
                {
                    "source": r.source,
                    "portal_tier": r.portal_tier,
                    "title": r.title,
                    "category": r.category,
                    "url": r.url,
                    "scraped_at": to_iso(r.scraped_at),
                }
                for r in rows
            ],
        }

    def get_latest_news(self, limit: int, tier: str) -> dict[str, Any]:
        """Matches old GET /dashboard/latest-news."""
        stmt = select(
            NewsArticle.id,
            NewsArticle.source,
            NewsArticle.portal_tier,
            NewsArticle.title,
            NewsArticle.body,
            NewsArticle.category,
            NewsArticle.url,
            NewsArticle.published_at,
            NewsArticle.scraped_at,
        )

        if tier in ("finance", "general"):
            stmt = stmt.where(NewsArticle.portal_tier == tier)

        # Ordered by published_at (when the article actually went live),
        # not scraped_at (when our pipeline happened to fetch it) -- those
        # can differ by hours or, for historical-backfill sources, years.
        # A handful of rows still have published_at=NULL until the fields
        # backfill worker finishes catching them up; NULLS LAST keeps those
        # from drowning out genuinely recent articles at the top of the feed.
        stmt = stmt.order_by(NewsArticle.published_at.desc().nulls_last()).limit(limit)

        rows = self._db.execute(stmt).all()

        return {
            "total": len(rows),
            "news": [
                {
                    "id": r.id,
                    "source": r.source,
                    "portal_tier": r.portal_tier,
                    "title": r.title,
                    "body": r.body,
                    "category": r.category,
                    "url": r.url,
                    "published_at": to_iso(r.published_at),
                    "scraped_at": to_iso(r.scraped_at),
                }
                for r in rows
            ],
        }

    def get_paginated_news(
        self,
        page: int,
        page_size: int,
        tier: str,
        source: str,
        category: str,
        search: str,
    ) -> dict[str, Any]:
        """Matches old GET /dashboard/news."""
        conditions = []

        if tier in ("finance", "general"):
            conditions.append(NewsArticle.portal_tier == tier)
        if source.strip():
            conditions.append(NewsArticle.source.ilike(f"%{source.strip()}%"))
        if category.strip():
            conditions.append(NewsArticle.category.ilike(f"%{category.strip()}%"))
        if search.strip():
            conditions.append(NewsArticle.title.ilike(f"%{search.strip()}%"))

        count_stmt = select(func.count()).select_from(NewsArticle)
        for cond in conditions:
            count_stmt = count_stmt.where(cond)
        total = int(self._db.execute(count_stmt).scalar_one() or 0)

        total_pages = max(1, (total + page_size - 1) // page_size)
        offset = (page - 1) * page_size

        data_stmt = select(
            NewsArticle.id,
            NewsArticle.source,
            NewsArticle.portal_tier,
            NewsArticle.title,
            NewsArticle.body,
            NewsArticle.category,
            NewsArticle.url,
            NewsArticle.published_at,
            NewsArticle.scraped_at,
        )
        for cond in conditions:
            data_stmt = data_stmt.where(cond)
        # See get_latest_news's matching comment: ordered by published_at,
        # not scraped_at, with NULLS LAST for rows still awaiting the
        # fields backfill worker.
        data_stmt = (
            data_stmt.order_by(NewsArticle.published_at.desc().nulls_last())
            .limit(page_size)
            .offset(offset)
        )

        rows = self._db.execute(data_stmt).all()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "news": [
                {
                    "id": r.id,
                    "source": r.source,
                    "portal_tier": r.portal_tier,
                    "title": r.title,
                    "body": r.body,
                    "category": r.category,
                    "url": r.url,
                    "published_at": to_iso(r.published_at),
                    "scraped_at": to_iso(r.scraped_at),
                }
                for r in rows
            ],
        }

    def get_article_by_id(self, article_id: int) -> dict[str, Any] | None:
        """Single-article lookup backing GET /dashboard/news/{id}, used by
        the news detail page (opened instead of navigating straight to the
        external url) -- returns None if no row matches so the router can
        respond 404."""
        stmt = select(
            NewsArticle.id,
            NewsArticle.source,
            NewsArticle.portal_tier,
            NewsArticle.title,
            NewsArticle.body,
            NewsArticle.category,
            NewsArticle.url,
            NewsArticle.published_at,
            NewsArticle.scraped_at,
        ).where(NewsArticle.id == article_id)

        row = self._db.execute(stmt).one_or_none()
        if row is None:
            return None

        return {
            "id": row.id,
            "source": row.source,
            "portal_tier": row.portal_tier,
            "title": row.title,
            "body": row.body,
            "category": row.category,
            "url": row.url,
            "published_at": to_iso(row.published_at),
            "scraped_at": to_iso(row.scraped_at),
        }

    def get_overview_stats(self, hours: int) -> dict[str, Any]:
        """Matches the article_stats + top_sources portions of old GET /dashboard/overview."""
        cutoff = _cutoff(hours)

        stats_stmt = select(
            func.count().label("total_articles"),
            func.count(func.distinct(NewsArticle.source)).label("total_sources"),
            func.count().filter(NewsArticle.portal_tier == "finance").label("finance_count"),
            func.count().filter(NewsArticle.portal_tier == "general").label("general_count"),
            func.max(NewsArticle.scraped_at).label("last_scraped_at"),
        ).where(NewsArticle.scraped_at >= cutoff)

        article_stats = self._db.execute(stats_stmt).one_or_none()

        top_sources_stmt = (
            select(NewsArticle.source, func.count().label("item_count"))
            .where(NewsArticle.scraped_at >= cutoff)
            .group_by(NewsArticle.source)
            .order_by(func.count().desc(), NewsArticle.source.asc())
            .limit(8)
        )
        top_sources = self._db.execute(top_sources_stmt).all()

        return {
            "stats": {
                "total_articles": int(article_stats.total_articles or 0) if article_stats else 0,
                "total_sources": int(article_stats.total_sources or 0) if article_stats else 0,
                "finance_count": int(article_stats.finance_count or 0) if article_stats else 0,
                "general_count": int(article_stats.general_count or 0) if article_stats else 0,
                "last_scraped_at": to_iso(article_stats.last_scraped_at) if article_stats else None,
            },
            "top_sources": [
                {"source": r.source, "item_count": int(r.item_count or 0)} for r in top_sources
            ],
        }
