from datetime import datetime


def to_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if isinstance(dt, datetime) else None
