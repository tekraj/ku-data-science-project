from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Double, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from nepse_common.db.base import Base


class NepseFloorsheet(Base):
    """One row per floor-sheet trade contract. Unlike nepse_today_price /
    nepse_index, floor-sheet rows have a real natural key (contract_id is
    unique per trading day on NEPSE), so writes upsert on
    (contract_id, business_date): a tick that re-fetches overlapping rows
    never inserts duplicates.

    Broker fields (buyer/seller member id + name) are NULL in every
    response NEPSE serves while the market is open -- it only publishes them
    after the 15:00 close. The 1-minute intraday scrape therefore stores
    them NULL, and NepseFloorSheetEodSweepWorkflow re-reads the whole day's
    floor sheet after the close and fills them in (and inserts any contracts
    the 500-row-per-minute intraday scrape missed). Broker ids are the
    closest thing NEPSE exposes to agent-level positions (the MFG part of
    the research)."""

    __tablename__ = "nepse_floorsheet"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    stock_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trade_book_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    buyer_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seller_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buyer_broker_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    seller_broker_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    contract_rate: Mapped[float | None] = mapped_column(Double, nullable=True)
    contract_amount: Mapped[float | None] = mapped_column(Double, nullable=True)
    business_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    trade_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    scraped_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("contract_id", "business_date", name="uq_nepse_floorsheet_contract"),
        Index("idx_nepse_floorsheet_scraped_at", "scraped_at"),
        Index("idx_nepse_floorsheet_symbol", "symbol"),
        Index("idx_nepse_floorsheet_business_date", "business_date"),
    )
