"""
Usage stats and activity log endpoints for the Hive management API.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query

from hive.api._auth import require_token
from hive.models import StatsResponse
from hive.storage import HiveStorage

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    auth: tuple[HiveStorage, str] = Depends(require_token),
) -> StatsResponse:
    storage, _ = auth
    today = date.today()
    last_7 = [(today - timedelta(days=i)).isoformat() for i in range(7)]

    events_today = storage.get_events_for_date(today.isoformat())
    events_7 = storage.get_events_for_dates(last_7)

    return StatsResponse(
        total_memories=storage.count_memories(),
        total_clients=storage.count_clients(),
        events_today=len(events_today),
        events_last_7_days=len(events_7),
    )


@router.get("/activity", response_model=list[dict])
async def get_activity(
    days: int = Query(7, ge=1, le=90, description="Number of days of history to return"),
    auth: tuple[HiveStorage, str] = Depends(require_token),
) -> list[dict]:
    storage, _ = auth
    today = date.today()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(days)]
    events = storage.get_events_for_dates(dates)
    return [
        {
            "event_id": e.event_id,
            "event_type": e.event_type.value,
            "client_id": e.client_id,
            "timestamp": e.timestamp.isoformat(),
            "metadata": e.metadata,
        }
        for e in events
    ]
