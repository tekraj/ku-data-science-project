"""nepse-service data management commands.

    docker compose exec nepse-service python manage_data.py coverage
    docker compose exec nepse-service python manage_data.py cleanup-stale            # dry run
    docker compose exec nepse-service python manage_data.py cleanup-stale --apply
    docker compose exec nepse-service python manage_data.py crash-events --index NEPSE --threshold 0.2

coverage       Row counts and date ranges of every market/research dataset.

crash-events   Drawdown episodes of an index deeper than --threshold, from
               the research_index_drawdown view (nepse_index_daily): peak,
               trough, depth, days to trough and recovery date. A starting
               point for the detector's ground-truth crash labels; --csv
               writes them to stdout as CSV.

cleanup-stale  Removes market-data rows the scrapers stored on days NEPSE did
               not trade (before is_market_open_activity checked NEPSE's own
               market status, the clock-only gate let every scraper run on
               public holidays, e.g. 2026-09-21 and 2026-09-25, storing flat
               index ticks, empty order books and the previous session's
               prices re-labelled as new snapshots). A day counts as
               non-trading when nepse_index_daily has no NEPSE bar for it,
               so run this after ResearchHistoryBackfillWorkflow has filled
               nepse_index_daily. Days after the calendar's last date are
               never touched. Rows are MOVED, not dropped: --apply copies
               them into quarantine.<table>_<timestamp> first, in the same
               transaction (restore with INSERT ... SELECT, discard with
               DROP TABLE).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from sqlalchemy import text

from nepse_common.config import load_app_config
from nepse_common.db.session import get_engine

# Live scraping started 2026-06-29; everything earlier in nepse_index is the
# CSV import (one row per real trading day) and is left alone.
_LIVE_SINCE = "2026-06-29"

_NOT_A_TRADING_DAY = """
    {col}::date >= :since
    AND {col}::date <= (SELECT max(trade_date) FROM nepse_index_daily WHERE index_name = 'NEPSE')
    AND NOT EXISTS (
        SELECT 1 FROM nepse_index_daily d WHERE d.index_name = 'NEPSE' AND d.trade_date = {col}::date
    )
"""

# (table, condition, description)
_STALE_RULES = [
    (
        "nepse_index",
        _NOT_A_TRADING_DAY.format(col="scraped_at"),
        "live index ticks on non-trading days",
    ),
    (
        "nepse_today_price",
        "(business_date IS DISTINCT FROM to_char(scraped_at, 'YYYY-MM-DD')) OR (" + _NOT_A_TRADING_DAY.format(col="scraped_at") + ")",
        "price snapshots re-labelled from an earlier session, or on non-trading days",
    ),
    (
        "nepse_market_depth",
        _NOT_A_TRADING_DAY.format(col="scraped_at"),
        "order-book snapshots on non-trading days",
    ),
    (
        "nepse_sector_summary",
        _NOT_A_TRADING_DAY.format(col="scraped_at"),
        "sector summaries on non-trading days",
    ),
]

_COVERAGE_QUERIES = [
    ("nepse_index (live ticks + CSV closes)", "SELECT count(*), min(scraped_at)::date, max(scraped_at)::date, count(DISTINCT index_name) FROM nepse_index"),
    ("nepse_index_daily", "SELECT count(*), min(trade_date), max(trade_date), count(DISTINCT index_name) FROM nepse_index_daily"),
    ("nepse_stock_daily", "SELECT count(*), min(trade_date), max(trade_date), count(DISTINCT symbol) FROM nepse_stock_daily"),
    ("nepse_stock_daily (adjusted)", "SELECT count(*), min(trade_date), max(trade_date), count(DISTINCT symbol) FROM nepse_stock_daily WHERE adj_close IS NOT NULL"),
    ("nepse_intraday_tick (indices)", "SELECT count(*), min(tick_time)::date, max(tick_time)::date, count(DISTINCT symbol) FROM nepse_intraday_tick WHERE instrument_type = 'index'"),
    ("nepse_intraday_tick (equities)", "SELECT count(*), min(tick_time)::date, max(tick_time)::date, count(DISTINCT symbol) FROM nepse_intraday_tick WHERE instrument_type = 'equity'"),
    ("nepse_today_price (1-min snapshots)", "SELECT count(*), min(scraped_at)::date, max(scraped_at)::date, count(DISTINCT symbol) FROM nepse_today_price"),
    ("nepse_floorsheet (trades)", "SELECT count(*), min(business_date), max(business_date), count(DISTINCT symbol) FROM nepse_floorsheet"),
    ("nepse_floorsheet (with broker ids)", "SELECT count(*), min(business_date), max(business_date), count(DISTINCT symbol) FROM nepse_floorsheet WHERE buyer_member_id IS NOT NULL OR buyer_broker_name IS NOT NULL"),
    ("nepse_market_depth", "SELECT count(*), min(scraped_at)::date, max(scraped_at)::date, count(DISTINCT symbol) FROM nepse_market_depth"),
    ("nepse_sector_summary", "SELECT count(*), min(scraped_at)::date, max(scraped_at)::date, count(DISTINCT sector_name) FROM nepse_sector_summary"),
    ("nepse_security", "SELECT count(*), NULL, NULL, count(DISTINCT symbol) FROM nepse_security"),
]


def coverage() -> int:
    engine = get_engine(load_app_config().database)
    print(f"{'dataset':42} {'rows':>12}  {'from':>10}  {'to':>10}  {'symbols':>7}")
    with engine.connect() as conn:
        for label, sql in _COVERAGE_QUERIES:
            n, first, last, symbols = conn.execute(text(sql)).one()
            print(f"{label:42} {n:>12,}  {str(first or '-'):>10}  {str(last or '-'):>10}  {symbols:>7}")
        print()
        rows = conn.execute(
            text(
                "SELECT dataset, symbol, oldest_covered::date, newest_covered::date, exhausted, rows_written, last_error "
                "FROM research_backfill_state WHERE dataset <> 'floorsheet_history' ORDER BY dataset, symbol"
            )
        ).all()
        filled = conn.execute(
            text("SELECT count(*), min(symbol), max(symbol) FROM research_backfill_state WHERE dataset = 'floorsheet_history'")
        ).one()
        if filled[0]:
            print(f"floor-sheet history filled from merolagani: {filled[0]} sessions ({filled[1]} .. {filled[2]})")
        if rows:
            print("research_backfill_state:")
            for r in rows:
                err = f"  error: {r.last_error[:80]}" if r.last_error else ""
                print(f"  {r.dataset:20} {r.symbol:30} {r.oldest_covered} .. {r.newest_covered}  done={r.exhausted}  rows={r.rows_written:,}{err}")
    return 0


def cleanup_stale(apply: bool, since: str) -> int:
    engine = get_engine(load_app_config().database)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with engine.begin() as conn:
        calendar_days = conn.execute(text("SELECT count(*) FROM nepse_index_daily WHERE index_name = 'NEPSE'")).scalar_one()
        if calendar_days == 0:
            print("nepse_index_daily has no NEPSE bars yet -- no trading calendar to judge by. "
                  "Let ResearchHistoryBackfillWorkflow finish first.", file=sys.stderr)
            return 1

        total = 0
        for table, condition, description in _STALE_RULES:
            per_day = conn.execute(
                text(f"SELECT scraped_at::date AS day, count(*) FROM {table} WHERE {condition} GROUP BY 1 ORDER BY 1"),
                {"since": since},
            ).all()
            n = sum(c for _, c in per_day)
            total += n
            print(f"{table}: {n:,} rows -- {description}")
            for day, count in per_day:
                print(f"    {day}  {count:,}")
            if apply and n:
                target = f"quarantine.{table}_{stamp}"
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS quarantine"))
                conn.execute(text(f"CREATE TABLE {target} (LIKE public.{table})"))
                conn.execute(text(f"INSERT INTO {target} SELECT * FROM public.{table} WHERE {condition}"), {"since": since})
                conn.execute(text(f"DELETE FROM public.{table} WHERE {condition}"), {"since": since})
                print(f"    -> moved to {target}")

    if not apply:
        print(f"\nDry run: {total:,} rows would be moved. Re-run with --apply to move them into the quarantine schema.")
    else:
        print(f"\nMoved {total:,} rows into quarantine.*_{stamp}.")
    return 0


def crash_events(index_name: str, threshold: float, as_csv: bool) -> int:
    engine = get_engine(load_app_config().database)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT trade_date, close FROM research_index_drawdown WHERE index_name = :name ORDER BY trade_date"),
            {"name": index_name},
        ).all()
    if not rows:
        print(f"No daily bars for {index_name!r} in nepse_index_daily.", file=sys.stderr)
        return 1

    # Classic drawdown episodes: an episode opens at a running peak, counts
    # once the fall from that peak exceeds the threshold, bottoms at its
    # trough and closes when the close regains the peak.
    episodes = []
    peak_date, peak = rows[0]
    trough_date, trough = peak_date, peak
    for day, close in rows[1:]:
        if close >= peak:
            if trough / peak - 1 <= -threshold:
                episodes.append((peak_date, peak, trough_date, trough, day))
            peak_date, peak = day, close
            trough_date, trough = day, close
        elif close < trough:
            trough_date, trough = day, close
    if trough / peak - 1 <= -threshold:
        episodes.append((peak_date, peak, trough_date, trough, None))

    header = ["peak_date", "peak", "trough_date", "trough", "drawdown_pct", "days_to_trough", "recovery_date"]
    lines = [
        [str(pd), f"{p:.2f}", str(td), f"{t:.2f}", f"{(t / p - 1) * 100:.1f}", str((td - pd).days), str(rd) if rd else "not recovered"]
        for pd, p, td, t, rd in episodes
    ]
    if as_csv:
        print(",".join(header))
        for line in lines:
            print(",".join(line))
        return 0

    print(f"{index_name}: {len(rows):,} sessions {rows[0][0]} .. {rows[-1][0]}, "
          f"{len(episodes)} drawdowns deeper than {threshold:.0%}")
    print("  ".join(f"{h:>14}" for h in header))
    for line in lines:
        print("  ".join(f"{v:>14}" for v in line))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="nepse-service data management")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("coverage", help="row counts and date ranges of every dataset")
    cleanup = sub.add_parser("cleanup-stale", help="quarantine rows scraped on non-trading days")
    cleanup.add_argument("--apply", action="store_true", help="actually move the rows (default: dry run)")
    cleanup.add_argument("--since", default=_LIVE_SINCE, help=f"only consider rows on/after this date (default {_LIVE_SINCE})")
    crashes = sub.add_parser("crash-events", help="drawdown episodes deeper than a threshold")
    crashes.add_argument("--index", default="NEPSE", help="index name as in nepse_index_daily (default NEPSE)")
    crashes.add_argument("--threshold", type=float, default=0.2, help="minimum peak-to-trough fall, e.g. 0.2 = 20%%")
    crashes.add_argument("--csv", action="store_true", help="print CSV instead of a table")
    args = parser.parse_args()

    if args.command == "coverage":
        return coverage()
    if args.command == "crash-events":
        return crash_events(args.index, args.threshold, args.csv)
    return cleanup_stale(args.apply, args.since)


if __name__ == "__main__":
    sys.exit(main())
