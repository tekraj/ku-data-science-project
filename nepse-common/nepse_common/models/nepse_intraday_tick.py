from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Double, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from nepse_common.db.base import Base


class NepseIntradayTick(Base):
    """Intraday price observations back to ~2018 -- the high-frequency
    history for realized/bipower variation, jump filtering and COGARCH
    calibration (the live nepse_index ticks only start 2026-06-29, 1-minute
    from 2026-09-15).

    Sourced from merolagani.com's chart handler, whose "1-minute" series is
    really a sequence of point observations (open == high == low == close
    on every row, verified 2026-10-15), so only one price is kept:
      - indices (instrument_type "index", symbol = canonical index name as
        in nepse_index / nepse_index_daily): the index value roughly once a
        minute (~200-240 per session); `volume` is the NPR turnover since
        the previous observation.
      - equities (instrument_type "equity", opt-in via
        INTRADAY_BACKFILL_STOCKS): one observation per minute that had
        trades; `volume` is shares.
    tick_time is the observation time (seconds included, not
    minute-aligned), naive NPT like every other timestamp in this database.
    Resample to a regular grid (e.g. last price per minute) before computing
    returns.
    """

    __tablename__ = "nepse_intraday_tick"

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    tick_time: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    instrument_type: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[float] = mapped_column(Double, nullable=False)
    volume: Mapped[float | None] = mapped_column(Double, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("idx_nepse_intraday_tick_tick_time", "tick_time"),)
