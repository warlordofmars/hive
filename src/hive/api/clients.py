# Copyright (c) 2026 John Carter. All rights reserved.
"""
OAuth client management endpoints for the Hive management API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from hive.api._auth import require_token
from hive.auth.dcr import register_client
from hive.models import (
    ActivityEvent,
    ClientRegistrationRequest,
    ClientRegistrationResponse,
    EventType,
    PagedResponse,
)
from hive.storage import HiveStorage

router = APIRouter(tags=["clients"])

_LIMIT_DEFAULT = 50
_LIMIT_MAX = 200


@router.get("/clients", response_model=PagedResponse)
async def list_clients(
    limit: int = Query(_LIMIT_DEFAULT, ge=1, le=_LIMIT_MAX),
    cursor: str | None = Query(None),
    auth: tuple[HiveStorage, str] = Depends(require_token),
) -> PagedResponse:
    storage, _ = auth
    clients, next_cursor = storage.list_clients(limit=limit, cursor=cursor)
    return PagedResponse(
        items=[ClientRegistrationResponse.from_client(c).model_dump() for c in clients],
        count=len(clients),
        has_more=next_cursor is not None,
        next_cursor=next_cursor,
    )


@router.post("/clients", response_model=ClientRegistrationResponse, status_code=201)
async def create_client(
    body: ClientRegistrationRequest,
    auth: tuple[HiveStorage, str] = Depends(require_token),
) -> ClientRegistrationResponse:
    storage, _ = auth
    try:
        resp = register_client(body, storage)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    storage.log_event(
        ActivityEvent(
            event_type=EventType.client_registered,
            client_id=resp.client_id,
            metadata={"client_name": resp.client_name},
        )
    )
    return resp


@router.get("/clients/{client_id}", response_model=ClientRegistrationResponse)
async def get_client(
    client_id: str,
    auth: tuple[HiveStorage, str] = Depends(require_token),
) -> ClientRegistrationResponse:
    storage, _ = auth
    client = storage.get_client(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return ClientRegistrationResponse.from_client(client)


@router.delete("/clients/{client_id}", status_code=204)
async def delete_client(
    client_id: str,
    auth: tuple[HiveStorage, str] = Depends(require_token),
) -> None:
    storage, caller_client_id = auth
    deleted = storage.delete_client(client_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Client not found")
    storage.log_event(
        ActivityEvent(
            event_type=EventType.client_deleted,
            client_id=caller_client_id,
            metadata={"deleted_client_id": client_id},
        )
    )
