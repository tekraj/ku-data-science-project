from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from nepse_common.db.base import Base


class ResearchBackfillState(Base):
    """Resume point per (dataset, symbol) for the research-data backfills in
    nepse-service (research_data_activities.py), so a worker restart or a
    weekly re-run continues where the last one stopped instead of
    re-downloading years of bars.

    dataset values:
      "intraday"           -- intraday ticks for `symbol`. oldest_covered /
                              newest_covered bound the window already
                              fetched; exhausted = walked back to
                              INTRADAY_BACKFILL_START_DATE.
      "daily_full_refresh" -- symbol "*": last_run_at of the last complete
                              merolagani daily-history refresh (raw +
                              adjusted) across all equities.
    """

    __tablename__ = "research_backfill_state"

    dataset: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    oldest_covered: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    newest_covered: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exhausted: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    rows_written: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())
