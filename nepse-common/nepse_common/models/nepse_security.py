from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from nepse_common.db.base import Base


class NepseSecurity(Base):
    """Security master from nepalstock.com.np's /api/nots/company/list:
    every listed, suspended and delisted security with its sector and
    instrument type. Used to map stocks to sectors (TDA point-cloud
    grouping), to pick the equity universe for history backfills, and to
    keep delisted/merged names in that universe (avoids survivorship bias
    in crash backtests).

    status: "A" active, "S" suspended, "D" delisted (as reported by NEPSE).
    """

    __tablename__ = "nepse_security"

    security_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    security_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    sector_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    instrument_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_nepse_security_symbol", "symbol"),)
