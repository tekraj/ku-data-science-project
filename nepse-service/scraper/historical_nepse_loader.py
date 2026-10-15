from __future__ import annotations

import csv
from datetime import datetime, time
from pathlib import Path
from typing import Any

_SYMBOL_TO_INDEX_NAME = {
    "NEPSE": "NEPSE",
    "BANKING": "Banking SubIndex",
    "DEVBANK": "Development Bank Index",
    "FINANCE": "Finance Index",
    "HOTELS": "Hotels And Tourism Index",
    "HYDROPOWER": "HydroPower Index",
    "INVESTMENT": "Investment Index",
    "LIFEINSU": "Life Insurance",
    "MANUFACTURE": "Manufacturing And Processing",
    "MICROFINANCE": "Microfinance Index",
    "NONLIFEINSU": "Non Life Insurance",
    "TRADING": "Trading Index",
    "OTHERS": "Others Index",
}


def _to_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "")
    if not text or text == "-":
        return None
    text = text.replace("%", "").strip()
    try:
        return float(text)
    except Exception:
        return None


def _symbol_to_index_name(symbol: str) -> str:
    key = (symbol or "").strip().upper()
    return _SYMBOL_TO_INDEX_NAME.get(key, key.title())


def parse_historical_nepse_csvs(data_dir: str) -> list[dict[str, Any]]:
    """Read all CSV files under data_dir and map them to nepse_index rows.

    Each row also carries the full daily bar (trade_date, open, high, low,
    close, turnover) for nepse_index_daily. The exports' "Volume" column is
    the index's NPR traded value (e.g. NEPSE ~6.4e9 in Jan 2021), so it is
    mapped to turnover; their "Turn Over" column is always "-"."""
    root = Path(data_dir)
    if not root.exists() or not root.is_dir():
        print(f"[NEPSE CSV] Data directory missing: {data_dir}")
        return []

    rows: list[dict[str, Any]] = []

    for file_path in sorted(root.glob("*.csv")):
        try:
            with file_path.open("r", encoding="utf-8-sig", newline="") as fp:
                reader = csv.DictReader(fp)
                if not reader.fieldnames:
                    continue

                for item in reader:
                    symbol = (item.get("Symbol") or "").strip()
                    date_str = (item.get("Date") or "").strip()
                    close_val = _to_float(item.get("Close"))
                    pct = _to_float(item.get("Percent Change"))

                    if not symbol or not date_str or close_val is None:
                        continue

                    try:
                        day = datetime.strptime(date_str, "%Y-%m-%d").date()
                    except Exception:
                        continue

                    change = None
                    if pct is not None:
                        change = close_val * (pct / 100.0)

                    rows.append(
                        {
                            "index_name": _symbol_to_index_name(symbol),
                            "value": close_val,
                            "change": change,
                            "percent_change": pct,
                            "scraped_at": datetime.combine(day, time(15, 0, 0)),
                            "trade_date": day,
                            "open": _to_float(item.get("Open")),
                            "high": _to_float(item.get("High")),
                            "low": _to_float(item.get("Low")),
                            "close": close_val,
                            "turnover": _to_float(item.get("Volume")),
                        }
                    )
        except Exception as e:
            print(f"[NEPSE CSV] Failed reading {file_path.name}: {e}")

    print(f"[NEPSE CSV] Parsed {len(rows)} rows from {data_dir}")
    return rows
