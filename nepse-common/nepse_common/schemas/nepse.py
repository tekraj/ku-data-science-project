from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class IndexPointOut(BaseModel):
    """Matches the index point shape shared by /nepse-index, /dashboard/nepse-history,
    /dashboard/sector-history, and the nepse/sector_snapshot portions of /dashboard/overview."""

    model_config = ConfigDict(from_attributes=True)

    index: str
    value: float | None = None
    change: float | None = None
    percent_change: float | None = None
    scraped_at: str | None = None


class NepseIndexResponse(BaseModel):
    """Matches the /nepse-index response shape."""

    window_hours: int
    nepse_main: list[IndexPointOut]
    sector_indices: list[IndexPointOut]


class NepseHistoryResponse(BaseModel):
    """Matches the /dashboard/nepse-history response shape."""

    window_hours: int
    points: list[IndexPointOut]


class SectorHistoryResponse(BaseModel):
    """Matches the /dashboard/sector-history response shape."""

    window_hours: int
    series: dict[str, list[IndexPointOut]]


class OverviewStats(BaseModel):
    """Matches the "stats" block of /dashboard/overview."""

    total_articles: int
    total_sources: int
    finance_count: int
    general_count: int
    last_scraped_at: str | None = None


class OverviewTopSource(BaseModel):
    """Matches entries in the "top_sources" list of /dashboard/overview."""

    source: str
    item_count: int


class OverviewResponse(BaseModel):
    """Matches the /dashboard/overview response shape."""

    window_hours: int
    stats: OverviewStats
    nepse: IndexPointOut
    sector_snapshot: list[IndexPointOut]
    top_sources: list[OverviewTopSource]


class IndicatorPoint(BaseModel):
    """One row of the /dashboard/indicators time series (Recharts-ready)."""

    date: str
    close: float | None = None
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    rsi_14: float | None = None
    bollinger_upper: float | None = None
    bollinger_middle: float | None = None
    bollinger_lower: float | None = None


class IndicatorSeriesResponse(BaseModel):
    """Matches the /dashboard/indicators response shape."""

    index_name: str
    days_requested: int
    days_available: int
    points: list[IndicatorPoint]


class IndexOption(BaseModel):
    """One selectable index_name entry, for populating an index picker."""

    index_name: str
    distinct_days: int
    latest_value: float | None = None


class IndexOptionsResponse(BaseModel):
    """Matches the /dashboard/indices response shape."""

    indices: list[IndexOption]
