from __future__ import annotations

from typing import Any

from sqlalchemy import select
from temporalio import activity

from nepse_common.config import load_app_config
from nepse_common.db.session import session_scope
from nepse_common.models import NepseIndex, PipelineRunLog
from nepse_common.schemas.scraped import ScrapedIndexPoint

from scraper.historical_nepse_loader import parse_historical_nepse_csvs

_CSV_IMPORT_MESSAGE = "historical_nepse_csv_import"


@activity.defn
async def check_csv_import_done_activity() -> bool:
    """Replaces old db/writer.py has_successful_pipeline_message(): True if
    pipeline_run_logs already has a successful row for the CSV import."""
    config = load_app_config()

    with session_scope(config.database) as session:
        stmt = (
            select(PipelineRunLog.id)
            .where(
                PipelineRunLog.status == "success",
                PipelineRunLog.message == _CSV_IMPORT_MESSAGE,
            )
            .limit(1)
        )
        row = session.execute(stmt).first()
        return row is not None


@activity.defn
async def parse_and_write_csv_activity(csv_dir: str) -> dict[str, int]:
    """Parses historical NEPSE CSVs (unchanged business logic), validates
    each row through ScrapedIndexPoint (this is exactly where the
    index/index_name normalization in the pydantic schema matters, since
    the loader emits "index_name" already but the schema also accepts a
    bare "index" key for parity with the live-scrape payload shape), and
    inserts into nepse_index with dedup by (index_name, scraped_at).

    Dedup approach: this activity runs once as a startup import over a
    bounded, known CSV dataset (a few years of daily rows per index), so a
    single bulk pre-fetch of all existing (index_name, scraped_at) pairs
    from nepse_index -- rather than one SELECT EXISTS per row -- is simpler
    to implement correctly and cheap enough at this data volume. Rows
    already present are filtered out client-side before the bulk insert.
    """
    config = load_app_config()

    raw_rows = parse_historical_nepse_csvs(csv_dir)

    validated_rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        point = ScrapedIndexPoint.model_validate(raw)
        validated_rows.append(point.model_dump(mode="json"))

    parsed = len(validated_rows)
    if parsed == 0:
        return {"parsed": 0, "inserted": 0}

    with session_scope(config.database) as session:
        existing_pairs = set(
            session.execute(
                select(NepseIndex.index_name, NepseIndex.scraped_at)
            ).all()
        )
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

        # Also dedup within the incoming batch itself (CSV files could overlap).
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

    activity.logger.info(
        f"[NEPSE CSV] Parsed {parsed} rows from {csv_dir}, inserted {inserted}."
    )
    return {"parsed": parsed, "inserted": inserted}
