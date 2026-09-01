from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from nepse_common.db.base import Base


class PipelineRunLog(Base):
    __tablename__ = "pipeline_run_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    news_total: Mapped[int | None] = mapped_column(Integer, server_default="0")
    news_inserted: Mapped[int | None] = mapped_column(Integer, server_default="0")
    nepse_records: Mapped[int | None] = mapped_column(Integer, server_default="0")
    nepse_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("idx_pipeline_run_logs_started_at", "started_at"),
        Index("idx_pipeline_run_logs_status", "status"),
    )
