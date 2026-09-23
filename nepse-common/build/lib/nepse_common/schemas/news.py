from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ArticleOut(BaseModel):
    """Matches the /articles endpoint's article shape."""

    model_config = ConfigDict(from_attributes=True)

    source: str
    portal_tier: str
    title: str | None = None
    category: str | None = None
    url: str
    scraped_at: str | None = None


class ArticlesResponse(BaseModel):
    """Matches the /articles endpoint's response shape."""

    window_hours: int
    total: int
    articles: list[ArticleOut]


class NewsItemOut(BaseModel):
    """Matches the news item shape used by /dashboard/latest-news and /dashboard/news."""

    model_config = ConfigDict(from_attributes=True)

    source: str
    portal_tier: str
    title: str | None = None
    body: str | None = None
    category: str | None = None
    url: str
    scraped_at: str | None = None


class LatestNewsResponse(BaseModel):
    """Matches the /dashboard/latest-news response shape."""

    total: int
    news: list[NewsItemOut]


class PaginatedNewsResponse(BaseModel):
    """Matches the /dashboard/news response shape."""

    total: int
    page: int
    page_size: int
    total_pages: int
    news: list[NewsItemOut]
