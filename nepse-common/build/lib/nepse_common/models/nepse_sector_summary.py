from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Double, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from nepse_common.db.base import Base


class NepseSectorSummary(Base):
    """One row per (sector, scrape tick) snapshot from nepalstock.com.np's
    sectorwise-summary endpoint. Plain-insert, no dedup -- same timeseries
    rationale as nepse_index/nepse_today_price."""

    __tablename__ = "nepse_sector_summary"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sector_name: Mapped[str] = mapped_column(Text, nullable=False)
    total_turnover: Mapped[float | None] = mapped_column(Double, nullable=True)
    total_trade_quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_transactions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_scrips_traded: Mapped[int | None] = mapped_column(Integer, nullable=True)
    business_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    scraped_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("idx_nepse_sector_summary_scraped_at", "scraped_at"),
        Index("idx_nepse_sector_summary_name", "sector_name"),
    )
