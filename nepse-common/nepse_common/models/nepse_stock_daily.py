from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, Double, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from nepse_common.db.base import Base


class NepseStockDaily(Base):
    """One row per (equity, trading day): daily OHLCV for every listed (and
    delisted) equity -- the cross-asset panel the TDA correlation networks
    and per-stock jump statistics are built from.

    Two price sets, because NEPSE companies issue bonus/right shares very
    often and the resulting ex-date price drops would otherwise look like
    crashes/jumps:
      open/high/low/close/volume  -- raw traded prices.
      adj_open/.../adj_close      -- corporate-action-adjusted prices from
                                     merolagani (isAdjust=1). Adjustment
                                     factors change retroactively after each
                                     corporate action, so these are fully
                                     re-fetched by the weekly
                                     ResearchHistoryBackfillWorkflow; rows
                                     captured since the last refresh have
                                     adj_* = NULL until then.

    Sources: "nepalstock" (official today-price captured after the close by
    NepseEndOfDayWorkflow -- adds turnover/total_trades) takes precedence
    over "merolagani" for the raw columns; adj_* always come from merolagani.
    """

    __tablename__ = "nepse_stock_daily"

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    security_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open: Mapped[float | None] = mapped_column(Double, nullable=True)
    high: Mapped[float | None] = mapped_column(Double, nullable=True)
    low: Mapped[float | None] = mapped_column(Double, nullable=True)
    close: Mapped[float | None] = mapped_column(Double, nullable=True)
    volume: Mapped[float | None] = mapped_column(Double, nullable=True)
    turnover: Mapped[float | None] = mapped_column(Double, nullable=True)
    total_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adj_open: Mapped[float | None] = mapped_column(Double, nullable=True)
    adj_high: Mapped[float | None] = mapped_column(Double, nullable=True)
    adj_low: Mapped[float | None] = mapped_column(Double, nullable=True)
    adj_close: Mapped[float | None] = mapped_column(Double, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_nepse_stock_daily_trade_date", "trade_date"),)
