"""
Seeds nepse_index from CSV files in data/sector-2021-2026/ (existing checked-in
exports plus anything newly downloaded by scrape_nepsealpha.py), using the same
parsing and dedup logic as nepse-service's startup CSV import
(nepse-service/activities/csv_import_activities.py: parse_and_write_csv_activity)
-- reused directly here rather than reimplemented, so both code paths stay in sync.

Safe to re-run: existing (index_name, scraped_at) pairs already in the table are
skipped, so this only inserts genuinely new rows.

Requirements: run with a Python environment that has nepse-common installed
(e.g. the same venv used for api-service/nepse-service development), and
nepse-service's package on the import path for historical_nepse_loader.

Usage:
    PYTHONPATH=/path/to/nepse-service python seed_from_csv.py [csv_dir]

    csv_dir defaults to data/sector-2021-2026/ relative to the repo root.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

from nepse_common.config import load_app_config
from nepse_common.db.session import session_scope
from nepse_common.models import NepseIndex
from nepse_common.schemas.scraped import ScrapedIndexPoint

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CSV_DIR = REPO_ROOT / "data" / "sector-2021-2026"

# nepse-service isn't installed as a package -- its `scraper/` module is a
# plain sibling-rooted directory, so add its parent to sys.path to import
# historical_nepse_loader without duplicating its parsing logic here. (Moved
# here from scraper-service/news-service when the NEPSE-specific scraping
# code was split into its own service.)
sys.path.insert(0, str(REPO_ROOT / "nepse-service"))
from scraper.historical_nepse_loader import parse_historical_nepse_csvs  # noqa: E402


def seed(csv_dir: str) -> dict[str, int]:
    config = load_app_config()

    raw_rows = parse_historical_nepse_csvs(csv_dir)
    if not raw_rows:
        print(f"No rows parsed from {csv_dir} -- nothing to do.")
        return {"parsed": 0, "inserted": 0}

    validated_rows: list[dict[str, Any]] = [
        ScrapedIndexPoint.model_validate(raw).model_dump(mode="json") for raw in raw_rows
    ]
    parsed = len(validated_rows)

    with session_scope(config.database) as session:
        existing_pairs = set(session.execute(select(NepseIndex.index_name, NepseIndex.scraped_at)).all())
        existing_keys = {
            (name, scraped_at.isoformat() if hasattr(scraped_at, "isoformat") else scraped_at)
            for name, scraped_at in existing_pairs
        }

        to_insert = [
            {
                "index_name": row["index_name"],
                "value": row.get("value"),
                "change": row.get("change"),
                "percent_change": row.get("percent_change"),
                "scraped_at": row["scraped_at"],
            }
            for row in validated_rows
            if (row["index_name"], row["scraped_at"]) not in existing_keys
        ]

        seen_in_batch: set[tuple[str, str]] = set()
        deduped_insert: list[dict[str, Any]] = []
        for row in to_insert:
            key = (row["index_name"], row["scraped_at"])
            if key in seen_in_batch:
                continue
            seen_in_batch.add(key)
            deduped_insert.append(row)

        inserted = 0
        if deduped_insert:
            session.execute(NepseIndex.__table__.insert(), deduped_insert)
            inserted = len(deduped_insert)

    print(f"Parsed {parsed} rows from {csv_dir}, inserted {inserted} new rows "
          f"({parsed - inserted} were already present).")
    return {"parsed": parsed, "inserted": inserted}


if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_CSV_DIR)
    seed(target_dir)
