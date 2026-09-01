from __future__ import annotations

from datetime import datetime

from sqlalchemy import Text, func
from sqlalchemy.orm import Mapped, mapped_column

from nepse_common.db.base import Base


class HistoricalCursorState(Base):
    """Resume point for a cursor-paginated (as opposed to sitemap-based)
    historical backfill source -- currently only sharesansar.com, whose
    listing page paginates via an opaque cursor with no way to jump
    directly to a date. One row per source; `cursor` is None once the
    chain is exhausted (no more older pages)."""

    __tablename__ = "historical_cursor_state"

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    exhausted: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    updated_at: Mapped[datetime | None] = mapped_column(server_default=func.now(), onupdate=func.now())
