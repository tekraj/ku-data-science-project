from __future__ import annotations

from datetime import datetime
from typing import Any

from temporalio import activity

from nepse_common.config import load_app_config
from nepse_common.db.session import session_scope
from nepse_common.models import PipelineRunLog


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


@activity.defn
async def write_pipeline_run_log_activity(log_data: dict[str, Any]) -> None:
    """Insert a pipeline_run_logs row, mirroring old write_pipeline_run_log().

    started_at/finished_at arrive as ISO strings (or None) since activity
    arguments must be JSON-serializable; they are parsed back to datetime
    here before insertion.
    """
    config = load_app_config()

    with session_scope(config.database) as session:
        row = PipelineRunLog(
            status=log_data.get("status", "failed"),
            message=log_data.get("message"),
            error_text=log_data.get("error_text"),
            news_total=int(log_data.get("news_total", 0) or 0),
            news_inserted=int(log_data.get("news_inserted", 0) or 0),
            nepse_records=int(log_data.get("nepse_records", 0) or 0),
            nepse_source=log_data.get("nepse_source"),
            started_at=_parse_dt(log_data.get("started_at")),
            finished_at=_parse_dt(log_data.get("finished_at")),
            duration_ms=int(log_data.get("duration_ms", 0) or 0),
        )
        session.add(row)

    activity.logger.info("[DB] Saved pipeline run log.")
