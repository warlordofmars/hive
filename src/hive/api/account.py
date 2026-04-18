# Copyright (c) 2026 John Carter. All rights reserved.
"""
Account self-service endpoints.

- DELETE /api/account        — GDPR Article 17 right-to-erasure
- GET    /api/account/export — GDPR Article 20 right-to-portability / CCPA §1798.100
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from hive.api._auth import require_mgmt_user
from hive.models import ActivityEvent, EventType
from hive.storage import HiveStorage

router = APIRouter(tags=["account"])

EXPORT_RATE_LIMIT_SECONDS = 300  # one export per 5 minutes per user
EXPORT_ACTIVITY_LOOKBACK_DAYS = 90  # activity-log retention per Privacy Policy §9
EXPORT_CLIENTS_LIMIT = 1000  # safety cap; quota is much lower in practice


def _storage() -> HiveStorage:
    return HiveStorage()


class AccountDeleteRequest(BaseModel):
    confirm: bool = False


@router.delete(
    "/account",
    summary="Delete my account",
    description=(
        "Permanently delete all data for the authenticated user: memories, OAuth clients, "
        "and the user record itself. Requires `confirm: true` in the request body. "
        "The deletion is recorded in an immutable audit log. This action cannot be undone."
    ),
    status_code=204,
    responses={
        400: {"description": "confirm must be true"},
        401: {"description": "Unauthorized"},
        404: {"description": "User not found"},
    },
)
async def delete_account(
    body: AccountDeleteRequest,
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> None:
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true to delete your account")

    user_id: str = claims["sub"]

    user = storage.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    counts = storage.delete_user_data(user_id)

    storage.log_audit_event(
        ActivityEvent(
            event_type=EventType.account_deleted,
            client_id="SYSTEM",
            metadata={
                "deleted_user_id": user_id,
                "deleted_memories": counts["deleted_memories"],
                "deleted_clients": counts["deleted_clients"],
            },
        )
    )


@router.get(
    "/account/export",
    summary="Export my data",
    description=(
        "Stream a JSON document containing the authenticated user's profile, "
        "all their memories, OAuth clients, and recent activity log entries "
        "(90-day window, matching the retention policy). Satisfies GDPR "
        "Article 20 and CCPA §1798.100 portability rights. Rate-limited to "
        "one export per 5 minutes per user."
    ),
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "User not found"},
        429: {"description": "Export rate limit exceeded"},
    },
)
async def export_account(
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> StreamingResponse:
    user_id: str = claims["sub"]

    user = storage.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Rate limit: one export per EXPORT_RATE_LIMIT_SECONDS. The counter item
    # has a matching TTL and is only set on first write (``if_not_exists``),
    # so DynamoDB cleans it up on its own after the window passes.
    count = storage.increment_rate_limit_counter(
        user_id, "export", ttl_seconds=EXPORT_RATE_LIMIT_SECONDS
    )
    if count > 1:
        raise HTTPException(
            status_code=429,
            detail="Exports are limited to one per 5 minutes.",
            headers={"Retry-After": str(EXPORT_RATE_LIMIT_SECONDS)},
        )

    now = datetime.now(timezone.utc)

    clients, _ = storage.list_clients(owner_user_id=user_id, limit=EXPORT_CLIENTS_LIMIT)
    client_ids = {c.client_id for c in clients}

    today = now.date()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(EXPORT_ACTIVITY_LOOKBACK_DAYS)]

    def _stream() -> Iterator[str]:
        yield "{"
        yield f'"exported_at":{json.dumps(now.isoformat())},'
        yield '"user":' + json.dumps(
            {
                "user_id": user.user_id,
                "email": user.email,
                "display_name": user.display_name,
                "role": user.role,
                "created_at": user.created_at.isoformat(),
            }
        )
        yield ',"memories":['
        for i, memory in enumerate(storage.iter_all_memories(owner_user_id=user_id)):
            if i:
                yield ","
            yield json.dumps(
                {
                    "memory_id": memory.memory_id,
                    "key": memory.key,
                    "value": memory.value,
                    "tags": memory.tags,
                    "owner_client_id": memory.owner_client_id,
                    "created_at": memory.created_at.isoformat(),
                    "updated_at": memory.updated_at.isoformat(),
                    "expires_at": (
                        memory.expires_at.isoformat() if memory.expires_at is not None else None
                    ),
                }
            )
        yield '],"clients":['
        for i, client in enumerate(clients):
            if i:
                yield ","
            yield json.dumps(
                {
                    "client_id": client.client_id,
                    "client_name": client.client_name,
                    "client_type": client.client_type.value,
                    "created_at": client.created_at.isoformat(),
                }
            )
        yield '],"activity_log":['
        events = storage.get_events_for_dates(dates, limit=10000)
        emitted = 0
        for event in events:
            if event.client_id not in client_ids:
                continue
            if emitted:
                yield ","
            emitted += 1
            yield json.dumps(
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type.value,
                    "client_id": event.client_id,
                    "timestamp": event.timestamp.isoformat(),
                    "metadata": event.metadata,
                }
            )
        yield "]}"

    filename = f"hive-export-{user_id}-{now.strftime('%Y%m%d')}.json"
    return StreamingResponse(
        _stream(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
