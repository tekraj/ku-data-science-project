from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator, model_validator


class ScrapedArticle(BaseModel):
    source: str
    portal_tier: str = "general"
    url: str
    title: str | None = None
    body: str | None = None
    category: str | None = None
    published_at: datetime | None = None

    @field_validator("published_at", mode="before")
    @classmethod
    def _parse_published_at(cls, value: Any) -> Any:
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return value


class ScrapedIndexPoint(BaseModel):
    index_name: str
    value: float | None = None
    change: float | None = None
    percent_change: float | None = None
    scraped_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _normalize_index_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and "index_name" not in data and "index" in data:
            data = {**data, "index_name": data["index"]}
        return data

    @field_validator("scraped_at", mode="before")
    @classmethod
    def _parse_scraped_at(cls, value: Any) -> Any:
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return value
