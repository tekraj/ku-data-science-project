from __future__ import annotations

from typing import Any

import math
from datetime import date, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from nepse_common.models import NepseIndex
from nepse_common.schemas.util import to_iso

from services import indicator_service
from services.market_service import MarketService

_NEPSE_MAIN_NAME = "NEPSE"

# Dashboard index charts: raw 1-minute ticks up to a day, ticks thinned to
# one per 10 minutes up to a week, and one official daily close per session
# beyond that. nepse_index alone mixes granularities (one CSV close per day
# before 2026-06-29, irregular ticks, then 1-minute ticks), which made long
# windows unreadable -- and "All Time" for every sub-index was a 13 MB
# response.
_TICK_MAX_HOURS = 24
_THIN_MAX_HOURS = 168
_THIN_BUCKET_MINUTES = 10


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


def _round(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None


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

    def _tick_rows(self, hours: int, main: bool) -> list[Any]:
        name_filter = NepseIndex.index_name == _NEPSE_MAIN_NAME if main else NepseIndex.index_name != _NEPSE_MAIN_NAME
        stmt = (
            select(
                NepseIndex.index_name,
                NepseIndex.value,
                NepseIndex.change,
                NepseIndex.percent_change,
                NepseIndex.scraped_at,
            )
            .where(name_filter)
            .where(NepseIndex.scraped_at >= _cutoff(hours))
            .order_by(NepseIndex.index_name.asc(), NepseIndex.scraped_at.asc())
        )
        rows = self._db.execute(stmt).all()
        if hours <= _TICK_MAX_HOURS:
            return rows
        # Keep the last tick of each 10-minute bucket.
        thinned: list[Any] = []
        last_key = None
        for r in rows:
            ts = r.scraped_at
            key = (r.index_name, ts.date(), ts.hour, ts.minute // _THIN_BUCKET_MINUTES)
            if key == last_key:
                thinned[-1] = r
            else:
                thinned.append(r)
                last_key = key
        return thinned

    def _daily_points(self, hours: int, main: bool) -> dict[str, list[dict[str, Any]]]:
        """One official close per session (nepse_index_daily) with change vs
        the previous session, plus today's latest live tick while today's
        bar isn't written yet."""
        start = date.today() - timedelta(days=math.ceil(hours / 24))
        op = "=" if main else "<>"
        rows = self._db.execute(
            text(
                f"""
                SELECT index_name, trade_date, close, change, percent_change FROM (
                    SELECT index_name, trade_date, close,
                           close - lag(close) OVER w AS change,
                           (close / nullif(lag(close) OVER w, 0) - 1) * 100 AS percent_change
                    FROM nepse_index_daily
                    WHERE index_name {op} :main AND trade_date >= :start - 14
                    WINDOW w AS (PARTITION BY index_name ORDER BY trade_date)
                ) d
                WHERE trade_date >= :start
                ORDER BY index_name, trade_date
                """
            ),
            {"main": _NEPSE_MAIN_NAME, "start": start},
        ).all()
        series: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            series.setdefault(r.index_name, []).append(
                {
                    "index": r.index_name,
                    "value": _round(r.close, 2),
                    "change": _round(r.change, 2),
                    "percent_change": _round(r.percent_change, 3),
                    "scraped_at": r.trade_date.isoformat(),
                }
            )
        for snap in MarketService(self._db).list_indices():
            points = series.get(snap["index_name"])
            if snap["live"] and points is not None and (snap["index_name"] == _NEPSE_MAIN_NAME) == main:
                points.append(
                    {
                        "index": snap["index_name"],
                        "value": snap["value"],
                        "change": snap["change"],
                        "percent_change": snap["percent_change"],
                        "scraped_at": snap["as_of"][:10],
                    }
                )
        return series

    def get_nepse_history(self, hours: int) -> dict[str, Any]:
        """NEPSE over the window; see _TICK_MAX_HOURS for the granularity."""
        if hours > _THIN_MAX_HOURS:
            return {
                "window_hours": hours,
                "granularity": "daily",
                "points": self._daily_points(hours, main=True).get(_NEPSE_MAIN_NAME, []),
            }
        return {
            "window_hours": hours,
            "granularity": "tick",
            "points": [_fmt(r) for r in self._tick_rows(hours, main=True)],
        }

    def get_sector_history(self, hours: int) -> dict[str, Any]:
        """Every other index over the window, keyed by index name."""
        if hours > _THIN_MAX_HOURS:
            return {"window_hours": hours, "granularity": "daily", "series": self._daily_points(hours, main=False)}
        by_index: dict[str, list[dict[str, Any]]] = {}
        for r in self._tick_rows(hours, main=False):
            by_index.setdefault(r.index_name, []).append(_fmt(r))
        return {"window_hours": hours, "granularity": "tick", "series": by_index}

    def _snapshots(self) -> list[dict[str, Any]]:
        return [
            {
                "index": snap["index_name"],
                "value": snap["value"],
                "change": snap["change"],
                "percent_change": snap["percent_change"],
                "scraped_at": snap["as_of"],
                "live": snap["live"],
            }
            for snap in MarketService(self._db).list_indices()
        ]

    def get_latest_nepse_snapshot(self) -> dict[str, Any]:
        """NEPSE's latest value (the live tick during a session, else the
        official close) and its change vs the previous session's official
        close (see MarketService.list_indices)."""
        for snap in self._snapshots():
            if snap["index"] == _NEPSE_MAIN_NAME:
                return snap
        return {"index": _NEPSE_MAIN_NAME, "value": None, "change": None, "percent_change": None, "scraped_at": None}

    def get_sector_snapshot(self, hours: int) -> list[dict[str, Any]]:
        """Same as get_latest_nepse_snapshot for the 16 other indices.
        `hours` is kept for the endpoint's signature; every index is
        returned (they all have daily history)."""
        return [snap for snap in self._snapshots() if snap["index"] != _NEPSE_MAIN_NAME]

    def get_daily_closes(self, index_name: str) -> list[dict]:
        """Every official daily close of `index_name` (nepse_index_daily:
        NEPSE from 2000, most sub-indices from 2014-2016), oldest first."""
        rows = self._db.execute(
            text(
                """
                SELECT trade_date, close FROM nepse_index_daily
                WHERE index_name = :name ORDER BY trade_date
                """
            ),
            {"name": index_name},
        ).all()
        return [{"date": r.trade_date.isoformat(), "value": r.close} for r in rows]

    def list_index_options(self) -> list[dict]:
        """One entry per index in nepse_index_daily: sessions of history
        (`distinct_days`) and latest value."""
        return [
            {
                "index_name": snap["index_name"],
                "distinct_days": snap["sessions"],
                "latest_value": snap["value"],
                "first_date": snap["first_date"],
            }
            for snap in MarketService(self._db).list_indices()
        ]

    def get_indicators(self, index_name: str, days: int) -> dict:
        """Daily closes plus derived technical indicators for `index_name`
        over the last `days` calendar days (0 = full history).

        The indicators are computed over the index's FULL daily history and
        then cut to the window, so SMA 200 / MACD / RSI are warmed up from
        the window's first point instead of starting blank. The series is
        sessions only (no calendar gaps), so forward-filling is a no-op
        safety net here.
        """
        closes = self.get_daily_closes(index_name)
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

        start = (date.fromisoformat(dates[-1]) - timedelta(days=days)).isoformat() if dates and days > 0 else ""
        points = [
            {
                "date": dates[i],
                "close": raw_values[i],
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
            if dates[i] >= start
        ]

        return {
            "index_name": index_name,
            "days_requested": days,
            "days_available": len(dates),
            "points": points,
        }
