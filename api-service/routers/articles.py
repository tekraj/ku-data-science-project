from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from deps import get_db
from services.news_service import NewsService
from services.nepse_service import NepseIndexService

router = APIRouter()


@router.get("/articles")
def get_articles(
    hours: int = Query(default=24, ge=1, le=720),
    tier: str = Query(default="all", description="all / finance / general"),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Returns recently scraped news articles."""
    return NewsService(db).get_recent_articles(hours=hours, tier=tier, limit=limit)


@router.get("/nepse-index")
def get_nepse_index(
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Returns NEPSE main index and sector indices for the last N hours."""
    return NepseIndexService(db).get_index_window(hours=hours)
