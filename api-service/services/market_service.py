"""Official index history (nepse_index_daily + the research_index_drawdown
view), intraday index paths (live nepse_index ticks, older sessions from
nepse_intraday_tick) and order-book snapshots (nepse_market_depth)."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from nepse_common.constants.index_registry import INDEX_REGISTRY
from nepse_common.schemas.util import to_iso

_REGISTRY_ORDER = {spec.name: i for i, spec in enumerate(INDEX_REGISTRY)}

# Annualisation factor for realised volatility: NEPSE has held ~230-240
# sessions a year (the trading week changed in 2026, so no fixed weekday
# count applies).
_SESSIONS_PER_YEAR = 240
_VOL_WINDOW = 20

# A live tick only counts as an intraday path once a session has this many.
_MIN_LIVE_TICKS = 10


def _num(value: Any) -> float | None:
    return float(value) if value is not None else None


def _pct(change: float | None, base: float | None) -> float | None:
    if change is None or not base:
        return None
    return change / base * 100.0


def drawdown_episodes(rows: list[tuple[date, float]], threshold: float) -> list[dict[str, Any]]:
    """Peak-to-trough falls deeper than `threshold` (0.2 = 20%): an episode
    opens at a running peak, bottoms at its trough and closes when the close
    regains the peak. Same rule as nepse-service `manage_data.py
    crash-events`, which produces the thesis' crash labels."""
    episodes: list[dict[str, Any]] = []
    if not rows:
        return episodes
    peak_date, peak = rows[0]
    trough_date, trough = peak_date, peak

    def _close(recovery: date | None) -> None:
        episodes.append(
            {
                "peak_date": peak_date.isoformat(),
                "peak": peak,
                "trough_date": trough_date.isoformat(),
                "trough": trough,
                "drawdown_pct": (trough / peak - 1) * 100.0,
                "days_to_trough": (trough_date - peak_date).days,
                "recovery_date": recovery.isoformat() if recovery else None,
            }
        )

    for day, close in rows[1:]:
        if close >= peak:
            if trough / peak - 1 <= -threshold:
                _close(day)
            peak_date, peak = day, close
            trough_date, trough = day, close
        elif close < trough:
            trough_date, trough = day, close
    if trough / peak - 1 <= -threshold:
        _close(None)
    return episodes


class MarketService:
    def __init__(self, db: Session) -> None:
        self._db = db

    # -- indices -----------------------------------------------------------

    def list_indices(self) -> list[dict[str, Any]]:
        """Every index with its history span and latest value. During a
        session (before the 15:40 end-of-day job writes today's bar) the
        latest value is the newest live tick, compared with the last daily
        close; otherwise the last daily close vs the one before it."""
        daily = self._db.execute(
            text(
                """
                WITH ranked AS (
                    SELECT index_name, trade_date, close,
                           row_number() OVER (PARTITION BY index_name ORDER BY trade_date DESC) AS rn,
                           count(*) OVER (PARTITION BY index_name) AS sessions,
                           min(trade_date) OVER (PARTITION BY index_name) AS first_date
                    FROM nepse_index_daily
                )
                SELECT l.index_name, l.first_date, l.trade_date AS last_date, l.sessions,
                       l.close, p.close AS prev_close
                FROM ranked l
                LEFT JOIN ranked p ON p.index_name = l.index_name AND p.rn = 2
                WHERE l.rn = 1
                """
            )
        ).all()
        live = {
            r.index_name: r
            for r in self._db.execute(
                text(
                    """
                    SELECT DISTINCT ON (index_name) index_name, value, scraped_at
                    FROM nepse_index
                    WHERE scraped_at >= now() - interval '4 days'
                    ORDER BY index_name, scraped_at DESC
                    """
                )
            ).all()
        }

        out = []
        for r in daily:
            tick = live.get(r.index_name)
            if tick is not None and tick.value and tick.scraped_at.date() > r.last_date:
                value, prev, as_of, is_live = tick.value, r.close, to_iso(tick.scraped_at), True
            else:
                value, prev, as_of, is_live = r.close, r.prev_close, r.last_date.isoformat(), False
            change = value - prev if value is not None and prev is not None else None
            out.append(
                {
                    "index_name": r.index_name,
                    "first_date": r.first_date.isoformat(),
                    "last_date": r.last_date.isoformat(),
                    "sessions": int(r.sessions),
                    "value": _num(value),
                    "change": _num(change),
                    "percent_change": _pct(change, prev),
                    "as_of": as_of,
                    "live": is_live,
                }
            )
        out.sort(key=lambda o: _REGISTRY_ORDER.get(o["index_name"], 99))
        return out

    def index_daily(self, index_name: str, days: int, threshold: float) -> dict[str, Any]:
        """Daily OHLC + turnover with drawdown from the running all-time
        peak, 20-session realised volatility and the drawdown episodes deeper
        than `threshold`. days=0 returns the full history. Drawdown and
        volatility are computed over the full history, so the first point of
        a short window isn't a fresh peak."""
        rows = self._db.execute(
            text(
                """
                SELECT d.trade_date, d.open, d.high, d.low, d.close, d.turnover, d.volume,
                       d.total_transactions, d.source, v.log_return, v.running_peak, v.drawdown
                FROM nepse_index_daily d
                JOIN research_index_drawdown v
                  ON v.index_name = d.index_name AND v.trade_date = d.trade_date
                WHERE d.index_name = :name
                ORDER BY d.trade_date
                """
            ),
            {"name": index_name},
        ).all()

        returns: list[float] = []
        points: list[dict[str, Any]] = []
        for r in rows:
            if r.log_return is not None:
                returns.append(r.log_return)
            window = returns[-_VOL_WINDOW:]
            vol = None
            if len(window) == _VOL_WINDOW:
                mean = sum(window) / len(window)
                var = sum((x - mean) ** 2 for x in window) / (len(window) - 1)
                vol = math.sqrt(var) * math.sqrt(_SESSIONS_PER_YEAR) * 100.0
            points.append(
                {
                    "date": r.trade_date.isoformat(),
                    "open": _num(r.open),
                    "high": _num(r.high),
                    "low": _num(r.low),
                    "close": _num(r.close),
                    "turnover": _num(r.turnover),
                    "volume": _num(r.volume),
                    "transactions": r.total_transactions,
                    "source": r.source,
                    "log_return_pct": r.log_return * 100.0 if r.log_return is not None else None,
                    "drawdown_pct": r.drawdown * 100.0 if r.drawdown is not None else None,
                    "running_peak": _num(r.running_peak),
                    "vol_20": vol,
                }
            )

        episodes = drawdown_episodes([(r.trade_date, r.close) for r in rows], threshold)
        if days > 0 and points:
            start = (date.fromisoformat(points[-1]["date"]) - timedelta(days=days)).isoformat()
            points = [p for p in points if p["date"] >= start]
            episodes = [e for e in episodes if (e["recovery_date"] or "9999") >= start]

        return {
            "index_name": index_name,
            "days": days,
            "threshold_pct": threshold * 100.0,
            "points": points,
            "episodes": episodes,
        }

    def _session_neighbours(self, day: date) -> tuple[str | None, str | None]:
        prev_day, next_day = self._db.execute(
            text(
                """
                SELECT
                  (SELECT max(trade_date) FROM nepse_index_daily WHERE index_name = 'NEPSE' AND trade_date < :d),
                  (SELECT min(trade_date) FROM nepse_index_daily WHERE index_name = 'NEPSE' AND trade_date > :d)
                """
            ),
            {"d": day},
        ).one()
        return (prev_day.isoformat() if prev_day else None, next_day.isoformat() if next_day else None)

    def index_intraday(self, index_name: str, day: date | None) -> dict[str, Any]:
        """One session's intraday path of an index: the live 1-minute
        official ticks (nepse_index, since 2026-09) when that session was
        scraped live, otherwise merolagani's ticks (nepse_intraday_tick, back
        to 2018). Defaults to the latest session with any ticks."""
        if day is None:
            latest = self._db.execute(
                text(
                    """
                    SELECT greatest(
                      (SELECT max(scraped_at)::date FROM nepse_index WHERE index_name = :name),
                      (SELECT max(tick_time)::date FROM nepse_intraday_tick WHERE symbol = :name))
                    """
                ),
                {"name": index_name},
            ).scalar()
            day = latest or date.today()

        start = datetime.combine(day, datetime.min.time())
        end = start + timedelta(days=1)
        rows = self._db.execute(
            text(
                """
                SELECT scraped_at AS ts, value FROM nepse_index
                WHERE index_name = :name AND scraped_at >= :start AND scraped_at < :end AND value > 0
                ORDER BY scraped_at
                """
            ),
            {"name": index_name, "start": start, "end": end},
        ).all()
        source = "nepalstock_live"
        if len(rows) < _MIN_LIVE_TICKS:
            rows = self._db.execute(
                text(
                    """
                    SELECT tick_time AS ts, price AS value FROM nepse_intraday_tick
                    WHERE symbol = :name AND tick_time >= :start AND tick_time < :end AND price > 0
                    ORDER BY tick_time
                    """
                ),
                {"name": index_name, "start": start, "end": end},
            ).all()
            source = "merolagani_ticks"

        bar = self._db.execute(
            text(
                """
                SELECT open, high, low, close, turnover,
                       (SELECT close FROM nepse_index_daily p
                        WHERE p.index_name = :name AND p.trade_date < :d
                        ORDER BY p.trade_date DESC LIMIT 1) AS prev_close
                FROM (SELECT 1) one
                LEFT JOIN nepse_index_daily d ON d.index_name = :name AND d.trade_date = :d
                """
            ),
            {"name": index_name, "d": day},
        ).one()
        prev_session, next_session = self._session_neighbours(day)
        return {
            "index_name": index_name,
            "date": day.isoformat(),
            "source": source if rows else None,
            "prev_close": _num(bar.prev_close),
            "bar": {
                "open": _num(bar.open),
                "high": _num(bar.high),
                "low": _num(bar.low),
                "close": _num(bar.close),
                "turnover": _num(bar.turnover),
            },
            "prev_session": prev_session,
            "next_session": next_session,
            "points": [{"t": to_iso(r.ts), "value": float(r.value)} for r in rows],
        }

    # -- order book --------------------------------------------------------

    def depth_symbols(self) -> dict[str, Any]:
        """Symbols with order-book snapshots on the latest depth day."""
        latest = self._db.execute(text("SELECT max(scraped_at) FROM nepse_market_depth")).scalar()
        if latest is None:
            return {"date": None, "symbols": []}
        start = datetime.combine(latest.date(), datetime.min.time())
        rows = self._db.execute(
            text(
                """
                SELECT symbol, count(*) AS snapshots, max(scraped_at) AS last_at
                FROM nepse_market_depth
                WHERE scraped_at >= :start
                GROUP BY symbol ORDER BY symbol
                """
            ),
            {"start": start},
        ).all()
        return {
            "date": latest.date().isoformat(),
            "symbols": [
                {"symbol": r.symbol, "snapshots": int(r.snapshots), "last_at": to_iso(r.last_at)} for r in rows
            ],
        }

    def depth(self, symbol: str, day: date | None) -> dict[str, Any]:
        """A symbol's order book over one session: per snapshot the best
        bid/ask, spread, the 5-level and total resting quantities and the
        order-flow imbalance, the latest ladder, and the last traded price
        from the per-minute today-price snapshots."""
        if day is None:
            latest = self._db.execute(
                text("SELECT max(scraped_at) FROM nepse_market_depth WHERE symbol = :s"), {"s": symbol}
            ).scalar()
            day = latest.date() if latest else date.today()
        start = datetime.combine(day, datetime.min.time())
        end = start + timedelta(days=1)
        rows = self._db.execute(
            text(
                """
                SELECT scraped_at, total_buy_qty, total_sell_qty, buy_levels, sell_levels
                FROM nepse_market_depth
                WHERE symbol = :s AND scraped_at >= :start AND scraped_at < :end
                ORDER BY scraped_at
                """
            ),
            {"s": symbol, "start": start, "end": end},
        ).all()

        def _levels(levels: Any) -> list[dict[str, Any]]:
            out = []
            for lvl in levels or []:
                price = _num(lvl.get("orderBookOrderPrice"))
                if price is None:
                    continue
                out.append(
                    {"price": price, "quantity": int(lvl.get("quantity") or 0), "orders": int(lvl.get("orderCount") or 0)}
                )
            return out

        series = []
        latest_book = None
        for r in rows:
            bids = sorted(_levels(r.buy_levels), key=lambda x: -x["price"])
            asks = sorted(_levels(r.sell_levels), key=lambda x: x["price"])
            best_bid = bids[0]["price"] if bids else None
            best_ask = asks[0]["price"] if asks else None
            mid = (best_bid + best_ask) / 2 if best_bid and best_ask else None
            buy_total = r.total_buy_qty or 0
            sell_total = r.total_sell_qty or 0
            series.append(
                {
                    "t": to_iso(r.scraped_at),
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread_pct": (best_ask - best_bid) / mid * 100.0 if mid else None,
                    "bid_depth5": sum(x["quantity"] for x in bids),
                    "ask_depth5": sum(x["quantity"] for x in asks),
                    "total_buy_qty": buy_total,
                    "total_sell_qty": sell_total,
                    "imbalance": (buy_total - sell_total) / (buy_total + sell_total)
                    if buy_total + sell_total
                    else None,
                }
            )
            latest_book = {"t": to_iso(r.scraped_at), "bids": bids, "asks": asks}

        trades = self._db.execute(
            text(
                """
                SELECT scraped_at, ltp FROM nepse_today_price
                WHERE symbol = :s AND scraped_at >= :start AND scraped_at < :end
                  AND business_date = :d AND ltp IS NOT NULL
                ORDER BY scraped_at
                """
            ),
            {"s": symbol, "start": start, "end": end, "d": day.isoformat()},
        ).all()
        return {
            "symbol": symbol,
            "date": day.isoformat(),
            "series": series,
            "latest": latest_book,
            "ltp": [{"t": to_iso(r.scraped_at), "ltp": float(r.ltp)} for r in trades],
        }
