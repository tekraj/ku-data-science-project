from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nepse_common.models import PipelineRunLog
from nepse_common.schemas.util import to_iso


class PipelineLogService:
    """Pipeline run log queries against nepse_common.models.PipelineRunLog."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_recent_logs(self, limit: int) -> dict[str, Any]:
        """Matches old GET /dashboard/pipeline-logs."""
        stmt = (
            select(PipelineRunLog)
            .order_by(PipelineRunLog.started_at.desc().nulls_last(), PipelineRunLog.id.desc())
            .limit(limit)
        )
        rows = self._db.execute(stmt).scalars().all()

        logs = [
            {
                "id": r.id,
                "status": r.status,
                "message": r.message,
                "error_text": r.error_text,
                "news_total": int(r.news_total or 0),
                "news_inserted": int(r.news_inserted or 0),
                "nepse_records": int(r.nepse_records or 0),
                "nepse_source": r.nepse_source,
                "started_at": to_iso(r.started_at),
                "finished_at": to_iso(r.finished_at),
                "duration_ms": int(r.duration_ms or 0),
                "created_at": to_iso(r.created_at),
            }
            for r in rows
        ]

        success = sum(1 for item in logs if item["status"] == "success")
        failed = sum(1 for item in logs if item["status"] != "success")

        return {
            "total": len(logs),
            "summary": {
                "success": success,
                "failed": failed,
                "last_run_at": logs[0]["started_at"] if logs else None,
            },
            "logs": logs,
        }
