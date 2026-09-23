from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from nepse_common.db.base import Base


class HistoricalIdWalkCursor(Base):
    """Resume point for a sequential-numeric-ID historical backfill source
    (setopati, merolagani, onlinekhabar -- portals with no sitemap and no
    date-archive listing reaching old content, only a guessable numeric ID
    in each article's URL; see historical_idwalk_discovery.py). One row per
    source: `next_id` is the next ID to fetch, walking forward from
    id_range_start toward id_range_end. `exhausted` is set once next_id
    passes id_range_end -- that portal's calibrated bracket is fully
    walked."""

    __tablename__ = "historical_idwalk_cursor"

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    next_id: Mapped[int] = mapped_column(Integer, nullable=False)
    exhausted: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())
