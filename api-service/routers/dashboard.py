from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from deps import get_current_claims, get_db
from services.floorsheet_service import FloorSheetService
from services.market_service import MarketService
from services.news_service import NewsService
from services.nepse_service import NepseIndexService
from services.pipeline_log_service import PipelineLogService

router = APIRouter(dependencies=[Depends(get_current_claims)])


@router.get("/overview")
def dashboard_overview(
    hours: int = Query(default=24, ge=1, le=87600),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    news_service = NewsService(db)
    nepse_service = NepseIndexService(db)

    overview_stats = news_service.get_overview_stats(hours=hours)
    nepse_snapshot = nepse_service.get_latest_nepse_snapshot()
    sector_snapshot = nepse_service.get_sector_snapshot(hours=hours)

    return {
        "window_hours": hours,
        "stats": overview_stats["stats"],
        "nepse": nepse_snapshot,
        "sector_snapshot": sector_snapshot,
        "top_sources": overview_stats["top_sources"],
    }


@router.get("/latest-news")
def dashboard_latest_news(
    limit: int = Query(default=15, ge=1, le=100),
    tier: str = Query(default="all", description="all / finance / general"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return NewsService(db).get_latest_news(limit=limit, tier=tier)


@router.get("/nepse-history")
def dashboard_nepse_history(
    hours: int = Query(default=24, ge=1, le=87600),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return NepseIndexService(db).get_nepse_history(hours=hours)


@router.get("/sector-history")
def dashboard_sector_history(
    hours: int = Query(default=24, ge=1, le=87600),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return NepseIndexService(db).get_sector_history(hours=hours)


@router.get("/news")
def dashboard_news(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    tier: str = Query(default="all", description="all / finance / general"),
    source: str = Query(default="", description="Filter by source name (partial match)"),
    category: str = Query(default="", description="Filter by category (partial match)"),
    search: str = Query(default="", description="Search in title"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Paginated protected news listing, ordered by date desc."""
    return NewsService(db).get_paginated_news(
        page=page,
        page_size=page_size,
        tier=tier,
        source=source,
        category=category,
        search=search,
    )


@router.get("/news/{article_id}")
def dashboard_news_detail(
    article_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Single-article lookup for the news detail page (opened instead of
    navigating straight to the external url)."""
    article = NewsService(db).get_article_by_id(article_id)
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    return article


@router.get("/pipeline-logs")
def dashboard_pipeline_logs(
    limit: int = Query(default=100, ge=1, le=1000),
    status_filter: str = Query(default="all", alias="status", description="all / success / failed"),
    source: str = Query(default="", description="exact nepse_source"),
    include_skipped: bool = Query(default=True, description="include market-closed skip rows"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = PipelineLogService(db)
    return {
        **service.get_recent_logs(
            limit=limit, status=status_filter, source=source, include_skipped=include_skipped
        ),
        "sources": service.get_sources(),
    }


@router.get("/pipeline-health")
def dashboard_pipeline_health(
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return PipelineLogService(db).get_health(hours)


@router.get("/indicators")
def dashboard_indicators(
    index_name: str = Query(default="NEPSE"),
    days: int = Query(default=400, ge=0, le=20000, description="calendar days; 0 = full history"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return NepseIndexService(db).get_indicators(index_name, days)


@router.get("/indices")
def dashboard_indices(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {"indices": NepseIndexService(db).list_index_options()}


@router.get("/market/indices")
def market_indices(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"indices": MarketService(db).list_indices()}


@router.get("/market/index-daily")
def market_index_daily(
    index_name: str = Query(default="NEPSE"),
    days: int = Query(default=365, ge=0, le=20000, description="calendar days; 0 = full history"),
    threshold: float = Query(default=0.2, gt=0, lt=1, description="drawdown episode depth, 0.2 = 20%"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return MarketService(db).index_daily(index_name, days, threshold)


@router.get("/market/index-intraday")
def market_index_intraday(
    index_name: str = Query(default="NEPSE"),
    day: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return MarketService(db).index_intraday(index_name, day)


@router.get("/market/depth-symbols")
def market_depth_symbols(db: Session = Depends(get_db)) -> dict[str, Any]:
    return MarketService(db).depth_symbols()


@router.get("/market/depth")
def market_depth(
    symbol: str = Query(...),
    day: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return MarketService(db).depth(symbol.upper(), day)


@router.get("/floorsheet/summary")
def floorsheet_summary(
    day: date | None = Query(default=None, alias="date"),
    symbol: str = Query(default=""),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return FloorSheetService(db).summary(day.isoformat() if day else None, symbol.upper() or None)


@router.get("/floorsheet/concentration")
def floorsheet_concentration(
    sessions: int = Query(default=60, ge=5, le=250),
    symbol: str = Query(default=""),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return FloorSheetService(db).concentration(sessions, symbol.upper() or None)


@router.get("/floorsheet/coverage")
def floorsheet_coverage(db: Session = Depends(get_db)) -> dict[str, Any]:
    return FloorSheetService(db).coverage()
