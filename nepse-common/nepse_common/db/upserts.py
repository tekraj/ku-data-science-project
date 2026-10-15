"""Idempotent bulk upserts for the research tables (nepse_index_daily,
nepse_stock_daily, nepse_intraday_tick, nepse_security).

Shared here (rather than living in one service's activities) because both
nepse-service's Temporal activities and scripts/nepsealpha-scraper/
seed_from_csv.py write the same tables with the same precedence rules.

Source precedence for the daily tables: an incoming row only overwrites an
existing one when its source ranks at least as high -- official
nepalstock.com.np data beats merolagani, which beats the CSV exports -- so
re-running a lower-quality backfill can never clobber official values.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from nepse_common.models import (
    NepseIndexDaily,
    NepseIntradayTick,
    NepseSecurity,
    NepseStockDaily,
)

SOURCE_RANK = {"csv": 0, "merolagani": 1, "nepalstock": 2}

# Postgres caps a statement at 65535 bind parameters; 1000 rows x <=15
# columns stays well under it.
_CHUNK_ROWS = 1000


def _chunks(rows: Sequence[dict[str, Any]], size: int = _CHUNK_ROWS) -> Iterable[Sequence[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _rank(column):
    return case(SOURCE_RANK, value=column, else_=0)


def _dedupe(rows: Sequence[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """Last row wins per key -- ON CONFLICT DO UPDATE rejects a batch that
    touches the same key twice."""
    by_key: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        by_key[tuple(row[f] for f in key_fields)] = row
    return list(by_key.values())


def upsert_index_daily(session: Session, rows: Sequence[dict[str, Any]], source: str) -> int:
    """rows: dicts with index_name, trade_date, open, high, low, close and
    optionally volume, turnover, total_transactions."""
    rows = _dedupe(rows, ("index_name", "trade_date"))
    if not rows:
        return 0

    table = NepseIndexDaily.__table__
    value_cols = ("open", "high", "low", "close", "volume", "turnover", "total_transactions")
    affected = 0
    for chunk in _chunks(rows):
        records = [
            {"index_name": r["index_name"], "trade_date": r["trade_date"], "source": source, **{c: r.get(c) for c in value_cols}}
            for r in chunk
        ]
        stmt = pg_insert(table).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["index_name", "trade_date"],
            set_={
                # Keep values a lower-detail source doesn't have (e.g. merolagani
                # has no total_transactions) instead of nulling them out.
                **{c: _coalesce_excluded(stmt, table, c) for c in value_cols},
                "source": stmt.excluded.source,
                "updated_at": func.now(),
            },
            where=_rank(table.c.source) <= _rank(stmt.excluded.source),
        )
        affected += session.execute(stmt).rowcount or 0
    return affected


def upsert_stock_daily_raw(session: Session, rows: Sequence[dict[str, Any]], source: str) -> int:
    """Raw (unadjusted) daily bars. rows: dicts with symbol, trade_date,
    open, high, low, close, volume and optionally turnover, total_trades,
    security_id."""
    rows = _dedupe(rows, ("symbol", "trade_date"))
    if not rows:
        return 0

    table = NepseStockDaily.__table__
    value_cols = ("security_id", "open", "high", "low", "close", "volume", "turnover", "total_trades")
    affected = 0
    for chunk in _chunks(rows):
        records = [
            {"symbol": r["symbol"], "trade_date": r["trade_date"], "source": source, **{c: r.get(c) for c in value_cols}}
            for r in chunk
        ]
        stmt = pg_insert(table).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "trade_date"],
            set_={
                **{c: _coalesce_excluded(stmt, table, c) for c in value_cols},
                "source": stmt.excluded.source,
                "updated_at": func.now(),
            },
            where=_rank(table.c.source) <= _rank(stmt.excluded.source),
        )
        affected += session.execute(stmt).rowcount or 0
    return affected


def upsert_stock_daily_adjusted(session: Session, rows: Sequence[dict[str, Any]]) -> int:
    """Corporate-action-adjusted bars (merolagani isAdjust=1). Always
    overwrites adj_* -- adjustment factors legitimately change after every
    bonus/right issue -- and never touches the raw columns or source."""
    rows = _dedupe(rows, ("symbol", "trade_date"))
    if not rows:
        return 0

    table = NepseStockDaily.__table__
    adj_cols = ("adj_open", "adj_high", "adj_low", "adj_close")
    affected = 0
    for chunk in _chunks(rows):
        records = [
            {"symbol": r["symbol"], "trade_date": r["trade_date"], "source": "merolagani", **{c: r.get(c) for c in adj_cols}}
            for r in chunk
        ]
        stmt = pg_insert(table).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "trade_date"],
            set_={**{c: getattr(stmt.excluded, c) for c in adj_cols}, "updated_at": func.now()},
        )
        affected += session.execute(stmt).rowcount or 0
    return affected


def upsert_intraday_ticks(session: Session, rows: Sequence[dict[str, Any]]) -> int:
    """rows: dicts with symbol, tick_time, instrument_type, price, volume,
    source. Re-fetched windows overwrite existing ticks (the source can
    revise the latest ones)."""
    rows = _dedupe(rows, ("symbol", "tick_time"))
    if not rows:
        return 0

    table = NepseIntradayTick.__table__
    value_cols = ("instrument_type", "price", "volume", "source")
    affected = 0
    for chunk in _chunks(rows):
        stmt = pg_insert(table).values(list(chunk))
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "tick_time"],
            set_={c: getattr(stmt.excluded, c) for c in value_cols},
        )
        affected += session.execute(stmt).rowcount or 0
    return affected


def upsert_securities(session: Session, rows: Sequence[dict[str, Any]]) -> int:
    rows = _dedupe(rows, ("security_id",))
    if not rows:
        return 0

    table = NepseSecurity.__table__
    value_cols = ("symbol", "security_name", "company_name", "sector_name", "instrument_type", "status")
    affected = 0
    for chunk in _chunks(rows):
        stmt = pg_insert(table).values([{"security_id": r["security_id"], **{c: r.get(c) for c in value_cols}} for r in chunk])
        stmt = stmt.on_conflict_do_update(
            index_elements=["security_id"],
            set_={**{c: getattr(stmt.excluded, c) for c in value_cols}, "updated_at": func.now()},
        )
        affected += session.execute(stmt).rowcount or 0
    return affected


def _coalesce_excluded(stmt, table, column: str):
    return func.coalesce(getattr(stmt.excluded, column), table.c[column])
