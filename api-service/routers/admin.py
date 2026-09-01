from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from temporalio.client import Client

from deps import get_current_claims, get_db
from services.admin_service import AdminBackfillService
from services.temporal_client import get_temporal_client

router = APIRouter(dependencies=[Depends(get_current_claims)])


def _parse_iso_date(value: str, field_name: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name}; expected YYYY-MM-DD",
        ) from e


@router.post("/historical/backfill")
async def admin_start_historical_backfill(
    start_date: str = Query(default="2020-01-01", description="YYYY-MM-DD"),
    end_date: str = Query(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d"), description="YYYY-MM-DD"
    ),
    db: Session = Depends(get_db),
    temporal_client: Client = Depends(get_temporal_client),
) -> dict[str, Any]:
    start = _parse_iso_date(start_date, "start_date")
    end = _parse_iso_date(end_date, "end_date")

    service = AdminBackfillService(db, temporal_client)
    return await service.request_backfill(start, end)


@router.get("/historical/backfill/status")
def admin_historical_backfill_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    service = AdminBackfillService(db, temporal_client=None)
    return service.get_backfill_status()
