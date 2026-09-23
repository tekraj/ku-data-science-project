from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client

from nepse_common.models import PipelineRunLog
from nepse_common.schemas.util import to_iso

from services.temporal_client import BACKFILL_WORKFLOW_NAME, TASK_QUEUE


class AdminBackfillService:
    """Kicks off / inspects the historical backfill Temporal workflow.

    The news-service side (the actual @workflow.defn implementation) is built
    separately; this only issues the client-side start_workflow call assuming
    that workflow name / task queue will exist there.
    """

    def __init__(self, db: Session, temporal_client: Client | None) -> None:
        self._db = db
        self._temporal_client = temporal_client

    async def request_backfill(self, start: date, end: date) -> dict[str, Any]:
        workflow_id = f"historical-backfill-{start.isoformat()}-{end.isoformat()}"

        await self._temporal_client.start_workflow(
            BACKFILL_WORKFLOW_NAME,
            args=[start.isoformat(), end.isoformat()],
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )

        return {
            "message": "Historical backfill started",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }

    def get_backfill_status(self) -> dict[str, Any]:
        """Best-effort reconstruction of the old in-memory `_historical_status` dict
        from the most recent backfill-related PipelineRunLog row.

        NOTE: `running` is always False here -- the api-service has no way to know
        live Temporal workflow state from the DB alone; a real "is it still running"
        answer would require calling handle.describe() against the Temporal server.
        """
        stmt = (
            select(PipelineRunLog)
            .where(PipelineRunLog.message.ilike("%backfill%"))
            .order_by(PipelineRunLog.started_at.desc().nulls_last(), PipelineRunLog.id.desc())
            .limit(1)
        )
        row = self._db.execute(stmt).scalars().first()

        if row is None:
            return {
                "running": False,
                "status": "idle",
                "start_date": None,
                "end_date": None,
                "started_at": None,
                "finished_at": None,
                "summary": None,
                "error": None,
            }

        return {
            "running": False,
            "status": row.status,
            "start_date": None,
            "end_date": None,
            "started_at": to_iso(row.started_at),
            "finished_at": to_iso(row.finished_at),
            "summary": row.message,
            "error": row.error_text,
        }
