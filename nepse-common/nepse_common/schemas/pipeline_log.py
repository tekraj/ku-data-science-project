from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PipelineLogEntry(BaseModel):
    """Matches an entry in the "logs" list of /dashboard/pipeline-logs."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    message: str | None = None
    error_text: str | None = None
    news_total: int
    news_inserted: int
    nepse_records: int
    nepse_source: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int
    created_at: str | None = None


class PipelineLogSummary(BaseModel):
    """Matches the "summary" block of /dashboard/pipeline-logs."""

    success: int
    failed: int
    last_run_at: str | None = None


class PipelineLogsResponse(BaseModel):
    """Matches the /dashboard/pipeline-logs response shape."""

    total: int
    summary: PipelineLogSummary
    logs: list[PipelineLogEntry]
