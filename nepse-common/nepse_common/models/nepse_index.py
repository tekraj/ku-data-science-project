from __future__ import annotations

from datetime import datetime

from sqlalchemy import Double, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from nepse_common.db.base import Base


class NepseIndex(Base):
    __tablename__ = "nepse_index"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    index_name: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float | None] = mapped_column(Double, nullable=True)
    change: Mapped[float | None] = mapped_column(Double, nullable=True)
    percent_change: Mapped[float | None] = mapped_column(Double, nullable=True)
    scraped_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("idx_nepse_index_scraped_at", "scraped_at"),
        Index("idx_nepse_index_name", "index_name"),
    )
