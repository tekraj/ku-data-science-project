from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from nepse_common.db.base import Base


class HistoricalBackfillProgress(Base):
    """One row per (source, target_date) once every discovered URL for that
    portal/day has been fetched and classified. Read by the discovery/ticker
    workflows so a re-run of the backfill never re-queues or re-fetches a
    day already completed for that portal."""

    __tablename__ = "historical_backfill_progress"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    articles_found: Mapped[int] = mapped_column(Integer, server_default="0")
    articles_inserted: Mapped[int] = mapped_column(Integer, server_default="0")
    completed_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "target_date", name="uq_historical_backfill_progress_source_date"),
    )
