"""Floor-sheet (every trade, with buyer/seller broker ids) analytics:
broker flows and trade-size mix for a session, broker concentration across
sessions, and the dataset's coverage (how far the merolagani history
backfill has got)."""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from nepse_common.schemas.util import to_iso

# Broker names: NEPSE publishes them only in post-close sweeps of recent
# sessions (merolagani history has ids only), and firms rename/merge, so an
# id is labelled with the name it most recently traded under.
_NAME_LOOKBACK_DAYS = 45
_NAME_CACHE_SECONDS = 3600
_COVERAGE_CACHE_SECONDS = 600
# A session counts as "with broker ids" once this share of its trades has
# them (mutual-fund/debenture trades merolagani doesn't list can stay NULL).
_BROKER_COMPLETE_RATIO = 0.9
_TOP_N = 5
_MAX_CONCENTRATION_SESSIONS = 250

# (label, upper bound in NPR) -- trade-size buckets for the size mix.
_SIZE_BUCKETS = [
    ("< 10k", 1e4),
    ("10k-50k", 5e4),
    ("50k-200k", 2e5),
    ("200k-1M", 1e6),
    ("1M-5M", 5e6),
    ("> 5M", None),
]

_name_cache: tuple[float, dict[int, str]] | None = None
_coverage_cache: tuple[float, dict[str, Any]] | None = None


def _num(value: Any) -> float | None:
    return float(value) if value is not None else None


def _hhi(amounts: list[float]) -> float | None:
    total = sum(amounts)
    if not total:
        return None
    return sum((a / total) ** 2 for a in amounts)


def _top_share(amounts: list[float], n: int = _TOP_N) -> float | None:
    total = sum(amounts)
    if not total:
        return None
    return sum(sorted(amounts, reverse=True)[:n]) / total * 100.0


class FloorSheetService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def broker_names(self) -> dict[int, str]:
        global _name_cache
        now = time.monotonic()
        if _name_cache is not None and now - _name_cache[0] < _NAME_CACHE_SECONDS:
            return _name_cache[1]
        since = (date.today() - timedelta(days=_NAME_LOOKBACK_DAYS)).isoformat()
        rows = self._db.execute(
            text(
                """
                SELECT DISTINCT ON (id) id, name FROM (
                    SELECT buyer_member_id AS id, buyer_broker_name AS name, business_date
                    FROM nepse_floorsheet
                    WHERE business_date >= :since AND buyer_broker_name IS NOT NULL
                    UNION ALL
                    SELECT seller_member_id, seller_broker_name, business_date
                    FROM nepse_floorsheet
                    WHERE business_date >= :since AND seller_broker_name IS NOT NULL
                ) s
                WHERE id IS NOT NULL
                ORDER BY id, business_date DESC
                """
            ),
            {"since": since},
        ).all()
        names = {int(r.id): r.name for r in rows}
        _name_cache = (now, names)
        return names

    def sessions(self) -> dict[str, Any]:
        latest, first = self._db.execute(
            text("SELECT max(business_date), min(business_date) FROM nepse_floorsheet")
        ).one()
        return {"latest": latest, "first": first}

    def _neighbours(self, day: str) -> tuple[str | None, str | None]:
        prev_day, next_day = self._db.execute(
            text(
                """
                SELECT
                  (SELECT max(trade_date) FROM nepse_index_daily WHERE index_name = 'NEPSE' AND trade_date < CAST(:d AS date)),
                  (SELECT min(trade_date) FROM nepse_index_daily WHERE index_name = 'NEPSE' AND trade_date > CAST(:d AS date))
                """
            ),
            {"d": day},
        ).one()
        return (prev_day.isoformat() if prev_day else None, next_day.isoformat() if next_day else None)

    def summary(self, day: str | None, symbol: str | None) -> dict[str, Any]:
        """One session (optionally one symbol): totals, every broker's buy /
        sell / net amount, the most traded symbols, the trade-size mix and,
        for sessions scraped live (trade_time known), activity per minute."""
        if not day:
            day = self.sessions()["latest"]
        if not day:
            return {"date": None, "symbol": symbol, "totals": None, "brokers": [], "symbols": [], "minutes": [], "sizes": []}

        where = "business_date = :d" + (" AND symbol = :s" if symbol else "")
        params = {"d": day, "s": symbol}

        totals = self._db.execute(
            text(
                f"""
                SELECT count(*) AS trades, sum(contract_amount) AS amount, sum(contract_quantity) AS quantity,
                       count(buyer_member_id) AS with_broker, count(trade_time) AS with_time,
                       count(DISTINCT symbol) AS symbols
                FROM nepse_floorsheet WHERE {where}
                """
            ),
            params,
        ).one()

        broker_rows = self._db.execute(
            text(
                f"""
                WITH b AS (
                    SELECT buyer_member_id AS id, sum(contract_amount) AS amount,
                           sum(contract_quantity) AS quantity, count(*) AS trades
                    FROM nepse_floorsheet WHERE {where} AND buyer_member_id IS NOT NULL GROUP BY 1
                ), s AS (
                    SELECT seller_member_id AS id, sum(contract_amount) AS amount,
                           sum(contract_quantity) AS quantity, count(*) AS trades
                    FROM nepse_floorsheet WHERE {where} AND seller_member_id IS NOT NULL GROUP BY 1
                )
                SELECT coalesce(b.id, s.id) AS id,
                       coalesce(b.amount, 0) AS buy_amount, coalesce(s.amount, 0) AS sell_amount,
                       coalesce(b.quantity, 0) AS buy_qty, coalesce(s.quantity, 0) AS sell_qty,
                       coalesce(b.trades, 0) AS buy_trades, coalesce(s.trades, 0) AS sell_trades
                FROM b FULL JOIN s ON b.id = s.id
                """
            ),
            params,
        ).all()
        names = self.broker_names()
        brokers = sorted(
            (
                {
                    "id": int(r.id),
                    "name": names.get(int(r.id)),
                    "buy_amount": float(r.buy_amount),
                    "sell_amount": float(r.sell_amount),
                    "net_amount": float(r.buy_amount) - float(r.sell_amount),
                    "buy_qty": int(r.buy_qty),
                    "sell_qty": int(r.sell_qty),
                    "buy_trades": int(r.buy_trades),
                    "sell_trades": int(r.sell_trades),
                }
                for r in broker_rows
            ),
            key=lambda b: -(b["buy_amount"] + b["sell_amount"]),
        )

        symbols = []
        if not symbol:
            symbols = [
                {
                    "symbol": r.symbol,
                    "trades": int(r.trades),
                    "amount": float(r.amount or 0),
                    "quantity": int(r.quantity or 0),
                    "vwap": float(r.amount) / float(r.quantity) if r.quantity else None,
                }
                for r in self._db.execute(
                    text(
                        """
                        SELECT symbol, count(*) AS trades, sum(contract_amount) AS amount,
                               sum(contract_quantity) AS quantity
                        FROM nepse_floorsheet WHERE business_date = :d
                        GROUP BY symbol ORDER BY sum(contract_amount) DESC NULLS LAST LIMIT 15
                        """
                    ),
                    {"d": day},
                ).all()
            ]

        minutes = []
        if totals.with_time:
            minutes = [
                {
                    "t": to_iso(r.minute),
                    "trades": int(r.trades),
                    "amount": float(r.amount or 0),
                    "vwap": float(r.amount) / float(r.quantity) if r.quantity else None,
                }
                for r in self._db.execute(
                    text(
                        f"""
                        SELECT date_trunc('minute', CAST(trade_time AS timestamp)) AS minute,
                               count(*) AS trades, sum(contract_amount) AS amount,
                               sum(contract_quantity) AS quantity
                        FROM nepse_floorsheet WHERE {where} AND trade_time IS NOT NULL
                        GROUP BY 1 ORDER BY 1
                        """
                    ),
                    params,
                ).all()
            ]

        bucket_case = "CASE " + " ".join(
            f"WHEN contract_amount < {bound} THEN {i}" for i, (_, bound) in enumerate(_SIZE_BUCKETS) if bound
        ) + f" ELSE {len(_SIZE_BUCKETS) - 1} END"
        size_rows = {
            int(r.bucket): r
            for r in self._db.execute(
                text(
                    f"""
                    SELECT {bucket_case} AS bucket, count(*) AS trades, sum(contract_amount) AS amount
                    FROM nepse_floorsheet WHERE {where} AND contract_amount IS NOT NULL GROUP BY 1
                    """
                ),
                params,
            ).all()
        }
        total_amount = float(totals.amount or 0)
        total_trades = int(totals.trades or 0)
        sizes = []
        for i, (label, _) in enumerate(_SIZE_BUCKETS):
            r = size_rows.get(i)
            trades = int(r.trades) if r else 0
            amount = float(r.amount or 0) if r else 0.0
            sizes.append(
                {
                    "bucket": label,
                    "trades": trades,
                    "amount": amount,
                    "trades_pct": trades / total_trades * 100.0 if total_trades else 0.0,
                    "amount_pct": amount / total_amount * 100.0 if total_amount else 0.0,
                }
            )

        prev_session, next_session = self._neighbours(day)
        buy_amounts = [b["buy_amount"] for b in brokers]
        sell_amounts = [b["sell_amount"] for b in brokers]
        return {
            "date": day,
            "symbol": symbol,
            "prev_session": prev_session,
            "next_session": next_session,
            "totals": {
                "trades": total_trades,
                "amount": total_amount,
                "quantity": int(totals.quantity or 0),
                "symbols": int(totals.symbols or 0),
                "with_broker": int(totals.with_broker or 0),
                "with_time": int(totals.with_time or 0),
                "brokers": len(brokers),
                "top5_buy_share": _top_share(buy_amounts),
                "top5_sell_share": _top_share(sell_amounts),
                "hhi_buy": _hhi(buy_amounts),
                "hhi_sell": _hhi(sell_amounts),
            },
            "brokers": brokers,
            "symbols": symbols,
            "minutes": minutes,
            "sizes": sizes,
        }

    def concentration(self, sessions: int, symbol: str | None) -> dict[str, Any]:
        """Per session over the last `sessions` sessions with trades: trades,
        turnover, the top-5 brokers' share of buy / sell turnover, the buy
        side's Herfindahl index and the share of trades with broker ids.
        Sessions whose broker ids aren't backfilled yet show null shares."""
        sessions = max(5, min(sessions, _MAX_CONCENTRATION_SESSIONS))
        # From the trading calendar: a DISTINCT over the floor sheet's
        # business_date would walk its whole index.
        start = self._db.execute(
            text(
                """
                SELECT min(trade_date) FROM (
                    SELECT trade_date FROM nepse_index_daily WHERE index_name = 'NEPSE'
                    ORDER BY trade_date DESC LIMIT :n) d
                """
            ),
            {"n": sessions},
        ).scalar()
        if start is None:
            return {"symbol": symbol, "points": []}
        sym = " AND symbol = :s" if symbol else ""
        params = {"start": start.isoformat(), "s": symbol}

        day_rows = self._db.execute(
            text(
                f"""
                SELECT business_date, count(*) AS trades, sum(contract_amount) AS amount,
                       count(buyer_member_id) AS with_broker
                FROM nepse_floorsheet WHERE business_date >= :start{sym}
                GROUP BY 1 ORDER BY 1
                """
            ),
            params,
        ).all()
        side_rows = self._db.execute(
            text(
                f"""
                SELECT business_date, 'buy' AS side, buyer_member_id AS id, sum(contract_amount) AS amount
                FROM nepse_floorsheet WHERE business_date >= :start{sym} AND buyer_member_id IS NOT NULL
                GROUP BY 1, 3
                UNION ALL
                SELECT business_date, 'sell', seller_member_id, sum(contract_amount)
                FROM nepse_floorsheet WHERE business_date >= :start{sym} AND seller_member_id IS NOT NULL
                GROUP BY 1, 3
                """
            ),
            params,
        ).all()
        by_day: dict[tuple[str, str], list[float]] = {}
        for r in side_rows:
            by_day.setdefault((r.business_date, r.side), []).append(float(r.amount or 0))

        points = []
        for r in day_rows:
            complete = r.trades and r.with_broker >= r.trades * _BROKER_COMPLETE_RATIO
            buys = by_day.get((r.business_date, "buy"), [])
            sells = by_day.get((r.business_date, "sell"), [])
            points.append(
                {
                    "date": r.business_date,
                    "trades": int(r.trades),
                    "amount": float(r.amount or 0),
                    "broker_coverage_pct": r.with_broker / r.trades * 100.0 if r.trades else None,
                    "brokers": len(buys) if complete else None,
                    "top5_buy_share": _top_share(buys) if complete else None,
                    "top5_sell_share": _top_share(sells) if complete else None,
                    "hhi_buy": _hhi(buys) if complete else None,
                }
            )
        return {"symbol": symbol, "points": points}

    def coverage(self) -> dict[str, Any]:
        """Per month since the first floor-sheet session: trading sessions
        in the calendar, sessions with trades, sessions with broker ids and
        trades stored, plus the history backfill's latest position. A full
        scan of nepse_floorsheet (~5 s), so it's cached for 10 minutes."""
        global _coverage_cache
        now = time.monotonic()
        if _coverage_cache is not None and now - _coverage_cache[0] < _COVERAGE_CACHE_SECONDS:
            return _coverage_cache[1]

        stored = {
            r.business_date: r
            for r in self._db.execute(
                text(
                    """
                    SELECT business_date, count(*) AS trades, count(buyer_member_id) AS with_broker
                    FROM nepse_floorsheet GROUP BY 1
                    """
                )
            ).all()
        }
        first = min(stored) if stored else None
        calendar = (
            [
                d.isoformat()
                for (d,) in self._db.execute(
                    text(
                        """
                        SELECT trade_date FROM nepse_index_daily
                        WHERE index_name = 'NEPSE' AND trade_date >= CAST(:first AS date) ORDER BY 1
                        """
                    ),
                    {"first": first},
                ).all()
            ]
            if first
            else []
        )

        months: dict[str, dict[str, Any]] = {}
        totals = {"sessions": 0, "with_trades": 0, "with_brokers": 0, "trades": 0, "trades_with_broker": 0}
        for day in sorted(set(calendar) | set(stored)):
            m = months.setdefault(
                day[:7], {"month": day[:7], "sessions": 0, "with_trades": 0, "with_brokers": 0, "trades": 0}
            )
            r = stored.get(day)
            m["sessions"] += 1
            totals["sessions"] += 1
            if r is None:
                continue
            m["with_trades"] += 1
            m["trades"] += int(r.trades)
            totals["with_trades"] += 1
            totals["trades"] += int(r.trades)
            totals["trades_with_broker"] += int(r.with_broker)
            if r.with_broker >= r.trades * _BROKER_COMPLETE_RATIO:
                m["with_brokers"] += 1
                totals["with_brokers"] += 1

        backfill = self._db.execute(
            text(
                """
                SELECT symbol, last_run_at, rows_written FROM research_backfill_state
                WHERE dataset = 'floorsheet_history' ORDER BY last_run_at DESC NULLS LAST LIMIT 1
                """
            )
        ).first()
        result = {
            "first_session": first,
            "totals": totals,
            "months": list(months.values()),
            "backfill": {
                "last_session": backfill.symbol,
                "last_run_at": to_iso(backfill.last_run_at),
                "trades": int(backfill.rows_written or 0),
            }
            if backfill
            else None,
        }
        _coverage_cache = (now, result)
        return result
