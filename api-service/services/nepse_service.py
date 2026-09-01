from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from nepse_common.models import NepseIndex
from nepse_common.schemas.util import to_iso

from services import indicator_service

_NEPSE_MAIN_NAME = "NEPSE"


def _cutoff(hours: int):
    """Server-side `NOW() - interval`, matching the old raw-SQL cutoff exactly.

    scraped_at is a naive TIMESTAMP populated via Postgres' NOW() in the
    session's configured timezone (PGTZ=Asia/Kathmandu). Computing the cutoff
    in Python as a tz-aware UTC datetime and comparing it against that naive
    column would trigger an implicit timestamptz->timestamp cast using the
    session timezone, shifting the effective window by the server's UTC
    offset. Doing the subtraction in SQL avoids that entirely.
    """
    return func.now() - text(f"'{hours} hours'::interval")


def _fmt(row: Any) -> dict[str, Any]:
    return {
        "index": row.index_name,
        "value": row.value,
        "change": row.change,
        "percent_change": row.percent_change,
        "scraped_at": to_iso(row.scraped_at),
    }


class NepseIndexService:
    """Index queries against nepse_common.models.NepseIndex."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_index_window(self, hours: int) -> dict[str, Any]:
        """Matches old GET /nepse-index."""
        cutoff = _cutoff(hours)

        stmt = (
            select(
                NepseIndex.index_name,
                NepseIndex.value,
                NepseIndex.change,
                NepseIndex.percent_change,
                NepseIndex.scraped_at,
            )
            .where(NepseIndex.scraped_at >= cutoff)
            .order_by(NepseIndex.scraped_at.desc())
        )
        rows = self._db.execute(stmt).all()

        main = [r for r in rows if r.index_name == _NEPSE_MAIN_NAME]
        sectors = [r for r in rows if r.index_name != _NEPSE_MAIN_NAME]

        return {
            "window_hours": hours,
            "nepse_main": [_fmt(r) for r in main],
            "sector_indices": [_fmt(r) for r in sectors],
        }

    def get_nepse_history(self, hours: int) -> dict[str, Any]:
        """Matches old GET /dashboard/nepse-history."""
        cutoff = _cutoff(hours)

        stmt = (
            select(
                NepseIndex.index_name,
                NepseIndex.value,
                NepseIndex.change,
                NepseIndex.percent_change,
                NepseIndex.scraped_at,
            )
            .where(NepseIndex.index_name == _NEPSE_MAIN_NAME)
            .where(NepseIndex.scraped_at >= cutoff)
            .order_by(NepseIndex.scraped_at.asc())
        )
        rows = self._db.execute(stmt).all()

        return {
            "window_hours": hours,
            "points": [_fmt(r) for r in rows],
        }

    def get_sector_history(self, hours: int) -> dict[str, Any]:
        """Matches old GET /dashboard/sector-history."""
        cutoff = _cutoff(hours)

        stmt = (
            select(
                NepseIndex.index_name,
                NepseIndex.value,
                NepseIndex.change,
                NepseIndex.percent_change,
                NepseIndex.scraped_at,
            )
            .where(NepseIndex.index_name != _NEPSE_MAIN_NAME)
            .where(NepseIndex.scraped_at >= cutoff)
            .order_by(NepseIndex.index_name.asc(), NepseIndex.scraped_at.asc())
        )
        rows = self._db.execute(stmt).all()

        by_index: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            by_index.setdefault(r.index_name, []).append(_fmt(r))

        return {
            "window_hours": hours,
            "series": by_index,
        }

    def _vs_previous_day(self, index_name: str) -> tuple[float | None, float | None, float | None, Any]:
        """Latest value for `index_name` plus change/percent_change computed
        against the previous *trading day's* closing value (last scrape of
        that calendar day) -- not whatever change/percent_change the scraper
        itself stored. This is independent of the source site's own "change"
        definition (which may be vs. previous tick rather than previous day,
        and was previously affected by a since-fixed scraper bug that
        inflated percent_change by ~100x -- see nepse_scraper.py).

        Returns (latest_value, change, percent_change, latest_scraped_at).
        """
        day_col = func.date(NepseIndex.scraped_at)
        stmt = (
            select(day_col.label("day"), NepseIndex.value, NepseIndex.scraped_at)
            .distinct(day_col)
            .where(NepseIndex.index_name == index_name)
            .order_by(day_col.desc(), NepseIndex.scraped_at.desc())
            .limit(2)
        )
        rows = self._db.execute(stmt).all()

        if not rows:
            return None, None, None, None

        latest_value = rows[0].value
        latest_scraped_at = rows[0].scraped_at
        previous_value = rows[1].value if len(rows) > 1 else None

        if latest_value is None or previous_value is None or previous_value == 0:
            return latest_value, None, None, latest_scraped_at

        change = latest_value - previous_value
        percent_change = (change / previous_value) * 100.0
        return latest_value, change, percent_change, latest_scraped_at

    def get_latest_nepse_snapshot(self) -> dict[str, Any]:
        """Matches the nepse portion of old /dashboard/overview.

        change/percent_change are computed vs. the previous trading day's
        close (see _vs_previous_day), not read from the stored row.
        """
        value, change, percent_change, scraped_at = self._vs_previous_day(_NEPSE_MAIN_NAME)

        return {
            "index": _NEPSE_MAIN_NAME,
            "value": value,
            "change": change,
            "percent_change": percent_change,
            "scraped_at": to_iso(scraped_at),
        }

    def get_sector_snapshot(self, hours: int) -> list[dict[str, Any]]:
        """Matches the sector_snapshot portion of old /dashboard/overview.

        Finds the set of sector index_names active within `hours` (via the
        same DISTINCT ON pattern as before), then for each one recomputes
        change/percent_change vs. the previous trading day's close rather
        than trusting the stored row (see _vs_previous_day).
        """
        cutoff = _cutoff(hours)

        active_stmt = (
            select(NepseIndex.index_name)
            .distinct(NepseIndex.index_name)
            .where(NepseIndex.index_name != _NEPSE_MAIN_NAME)
            .where(NepseIndex.scraped_at >= cutoff)
            .order_by(NepseIndex.index_name)
        )
        active_names = [r.index_name for r in self._db.execute(active_stmt).all()]

        snapshots = []
        for name in active_names:
            value, change, percent_change, scraped_at = self._vs_previous_day(name)
            snapshots.append(
                {
                    "index": name,
                    "value": value,
                    "change": change,
                    "percent_change": percent_change,
                    "scraped_at": to_iso(scraped_at),
                }
            )
        return snapshots

    def get_daily_closes(self, index_name: str, days: int) -> list[dict]:
        """One row per calendar day for `index_name`, most recent `days` days.

        Uses Postgres DISTINCT ON via SQLAlchemy's distinct(column) support,
        the same pattern as get_sector_snapshot above, but distinct on the
        scrape *date* rather than index_name -- equivalent to:
            SELECT DISTINCT ON (date(scraped_at)) date(scraped_at) AS day,
                   value, scraped_at
            FROM nepse_index
            WHERE index_name = :index_name
            ORDER BY date(scraped_at) DESC, scraped_at DESC
            LIMIT :days
        Results come back newest-first (required for DISTINCT ON to keep the
        latest scrape of each day) and are re-sorted ascending before return.
        """
        day_col = func.date(NepseIndex.scraped_at)

        stmt = (
            select(
                day_col.label("day"),
                NepseIndex.value,
                NepseIndex.scraped_at,
            )
            .distinct(day_col)
            .where(NepseIndex.index_name == index_name)
            .order_by(day_col.desc(), NepseIndex.scraped_at.desc())
            .limit(days)
        )
        rows = self._db.execute(stmt).all()

        ordered = sorted(rows, key=lambda r: r.day)
        return [
            {
                "date": r.day.isoformat() if hasattr(r.day, "isoformat") else str(r.day),
                "value": r.value,
            }
            for r in ordered
        ]

    def count_distinct_days(self, index_name: str) -> int:
        """Total number of distinct scrape calendar days for `index_name`."""
        stmt = select(func.count(func.distinct(func.date(NepseIndex.scraped_at)))).where(
            NepseIndex.index_name == index_name
        )
        return self._db.execute(stmt).scalar() or 0

    def list_index_options(self) -> list[dict]:
        """One entry per distinct index_name: distinct scrape days + latest value.

        Fetches, per index_name, its distinct-day count and its most recent
        (index_name, value) via a row_number() window function partitioned by
        index_name and ordered by scraped_at desc, then combines the two in
        Python -- there are only ~13 distinct index_name values, so a second
        lightweight query plus a Python-side merge is simplest and correct.
        """
        latest_row_num = (
            func.row_number()
            .over(
                partition_by=NepseIndex.index_name,
                order_by=NepseIndex.scraped_at.desc(),
            )
            .label("rn")
        )
        latest_subq = select(
            NepseIndex.index_name,
            NepseIndex.value,
            latest_row_num,
        ).subquery()

        latest_stmt = select(latest_subq.c.index_name, latest_subq.c.value).where(
            latest_subq.c.rn == 1
        )
        latest_by_index: dict[str, float | None] = {
            r.index_name: r.value for r in self._db.execute(latest_stmt).all()
        }

        days_stmt = select(
            NepseIndex.index_name,
            func.count(func.distinct(func.date(NepseIndex.scraped_at))).label("distinct_days"),
        ).group_by(NepseIndex.index_name)
        days_by_index: dict[str, int] = {
            r.index_name: r.distinct_days for r in self._db.execute(days_stmt).all()
        }

        options = [
            {
                "index_name": name,
                "distinct_days": days_by_index.get(name, 0),
                "latest_value": latest_by_index.get(name),
            }
            for name in days_by_index
        ]

        options.sort(key=lambda o: (o["index_name"] != _NEPSE_MAIN_NAME, o["index_name"]))
        return options

    def get_indicators(self, index_name: str, days: int) -> dict:
        """Daily closes plus derived technical indicators for `index_name`.

        Indicator math (SMA/EMA/MACD/RSI/Bollinger) is computed over a
        forward-filled copy of the close series so a missing scrape day
        doesn't create a spurious gap artifact in rolling-window math (see
        indicator_service module docstring). The `close` field returned per
        row, however, is the ORIGINAL (non-forward-filled) value, so the
        displayed price line still shows real gaps honestly rather than
        silently smoothing over missing data.
        """
        closes = self.get_daily_closes(index_name, days)
        dates = [c["date"] for c in closes]
        raw_values = [c["value"] for c in closes]

        filled_values = indicator_service.forward_fill(raw_values)

        sma_20 = indicator_service.compute_sma(filled_values, 20)
        sma_50 = indicator_service.compute_sma(filled_values, 50)
        sma_200 = indicator_service.compute_sma(filled_values, 200)
        ema_12 = indicator_service.compute_ema(filled_values, 12)
        ema_26 = indicator_service.compute_ema(filled_values, 26)
        macd = indicator_service.compute_macd(filled_values)
        rsi_14 = indicator_service.compute_rsi(filled_values, 14)
        bollinger = indicator_service.compute_bollinger_bands(filled_values, 20)

        points = [
            {
                "date": dates[i],
                "close": raw_values[i],  # original, not forward-filled -- show real gaps
                "sma_20": sma_20[i],
                "sma_50": sma_50[i],
                "sma_200": sma_200[i],
                "ema_12": ema_12[i],
                "ema_26": ema_26[i],
                "macd": macd["macd"][i],
                "macd_signal": macd["signal"][i],
                "macd_histogram": macd["histogram"][i],
                "rsi_14": rsi_14[i],
                "bollinger_upper": bollinger["upper"][i],
                "bollinger_middle": bollinger["middle"][i],
                "bollinger_lower": bollinger["lower"][i],
            }
            for i in range(len(dates))
        ]

        return {
            "index_name": index_name,
            "days_requested": days,
            "days_available": self.count_distinct_days(index_name),
            "points": points,
        }
