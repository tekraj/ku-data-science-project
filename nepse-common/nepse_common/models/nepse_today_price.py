from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Double, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from nepse_common.db.base import Base


class NepseTodayPrice(Base):
    """One row per (security, scrape tick) snapshot from nepalstock.com.np's
    today-price endpoint. Plain-insert, no dedup -- like nepse_index, this
    is a timeseries where every tick is a legitimately new row, not a
    row to be upserted in place.

    close_price is NULL in every intraday snapshot (NEPSE only sets
    closePrice after the session ends); use ltp intraday, and
    nepse_stock_daily for official daily closes."""

    __tablename__ = "nepse_today_price"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    security_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    security_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    open_price: Mapped[float | None] = mapped_column(Double, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Double, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Double, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Double, nullable=True)
    previous_close: Mapped[float | None] = mapped_column(Double, nullable=True)
    ltp: Mapped[float | None] = mapped_column(Double, nullable=True)
    percent_change: Mapped[float | None] = mapped_column(Double, nullable=True)
    total_trade_quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_trade_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    total_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Volume-weighted average traded price so far today.
    average_traded_price: Mapped[float | None] = mapped_column(Double, nullable=True)
    # Time of this security's most recent trade (NEPSE lastUpdatedTime) --
    # unlike scraped_at, tells a fresh price apart from a stale one carried
    # over from an earlier minute (needed to correct non-synchronous trading
    # when estimating intraday correlations).
    last_updated_time: Mapped[datetime | None] = mapped_column(nullable=True)
    business_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    scraped_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("idx_nepse_today_price_scraped_at", "scraped_at"),
        Index("idx_nepse_today_price_symbol", "symbol"),
    )
