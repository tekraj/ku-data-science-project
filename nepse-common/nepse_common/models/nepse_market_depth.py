from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nepse_common.db.base import Base


class NepseMarketDepth(Base):
    """One row per (security, scrape tick) snapshot of the bid/ask order
    book ladder from nepalstock.com.np's per-security market-depth
    endpoint. Plain-insert, no dedup -- same timeseries rationale as
    nepse_index/nepse_today_price.

    The bid/ask levels themselves are stored as JSONB (buy_levels /
    sell_levels, each a list of {price, quantity, order_count} dicts) rather
    than fully normalized into a separate levels table -- consistent with
    this codebase's general preference for pragmatic, flatter schemas
    (nepse_index itself is a flat table, not normalized across index/point
    tables) and because the ladder is always read/written as a whole unit,
    never queried level-by-level."""

    __tablename__ = "nepse_market_depth"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    total_buy_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_sell_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buy_levels: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    sell_levels: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    scraped_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("idx_nepse_market_depth_scraped_at", "scraped_at"),
        Index("idx_nepse_market_depth_symbol", "symbol"),
    )
