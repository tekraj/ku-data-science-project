from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, Double, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from nepse_common.db.base import Base


class NepseIndexDaily(Base):
    """One row per (index, trading day): daily OHLC + turnover for every
    NEPSE index (see nepse_common.constants.index_registry).

    Kept separate from nepse_index on purpose: nepse_index is the live
    intraday tick table the dashboard reads (value/change only, one row per
    scrape), while this is the clean, deduplicated daily bar series research
    code should use (COGARCH/jump calibration, rolling correlations, crash
    labels). Its dates also double as the NEPSE trading calendar.

    Sources (`source` column), in order of precedence -- an upsert from a
    higher-precedence source overwrites a lower one, never the reverse (see
    nepse_common.db.upserts):
      "nepalstock" -- official /api/nots/index/history/{id} (~last 1 year
                      only), captured nightly by NepseEndOfDayWorkflow;
                      the only source with total_transactions.
      "merolagani" -- merolagani.com chart handler, full history (NEPSE
                      from 2000-01-03, most sub-indices from 2014-2016).
      "csv"        -- the checked-in nepsealpha/sharesansar CSV exports.
    """

    __tablename__ = "nepse_index_daily"

    index_name: Mapped[str] = mapped_column(Text, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Double, nullable=True)
    high: Mapped[float | None] = mapped_column(Double, nullable=True)
    low: Mapped[float | None] = mapped_column(Double, nullable=True)
    close: Mapped[float | None] = mapped_column(Double, nullable=True)
    # Shares traded across the index's constituents (official source only).
    volume: Mapped[float | None] = mapped_column(Double, nullable=True)
    # Traded value in NPR.
    turnover: Mapped[float | None] = mapped_column(Double, nullable=True)
    total_transactions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_nepse_index_daily_trade_date", "trade_date"),)
