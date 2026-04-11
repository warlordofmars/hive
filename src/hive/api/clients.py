# Copyright (c) 2026 John Carter. All rights reserved.
"""
OAuth client management endpoints for the Hive management API.

All routes require a valid management JWT.
Non-admins see only their own clients; admins see all.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from hive.api._auth import require_mgmt_user
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


def _storage() -> HiveStorage:
    return HiveStorage()


def _user_filter(claims: dict[str, Any]) -> str | None:
    return None if claims.get("role") == "admin" else claims["sub"]


@router.get("/clients", responses={401: {"description": "Unauthorized"}})
async def list_clients(
    limit: int = Query(_LIMIT_DEFAULT, ge=1, le=_LIMIT_MAX),
    cursor: str | None = Query(None),
    claims: dict[str, Any] = Depends(require_mgmt_user),
    storage: HiveStorage = Depends(_storage),
) -> PagedResponse:
    owner_user_id = _user_filter(claims)
    clients, next_cursor = storage.list_clients(
        owner_user_id=owner_user_id, limit=limit, cursor=cursor
    )
    return PagedResponse(
        items=[ClientRegistrationResponse.from_client(c).model_dump() for c in clients],
        count=len(clients),
        has_more=next_cursor is not None,
        next_cursor=next_cursor,
    )


@router.post(
    "/clients",
    status_code=201,
    responses={
        400: {"description": "Invalid client registration request"},
        401: {"description": "Unauthorized"},
    },
)
async def create_client(
    body: ClientRegistrationRequest,
    claims: dict[str, Any] = Depends(require_mgmt_user),
    storage: HiveStorage = Depends(_storage),
) -> ClientRegistrationResponse:
    owner_user_id: str = claims["sub"]
    try:
        resp = register_client(body, storage)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Attach owner to the newly registered client
    client = storage.get_client(resp.client_id)
    if client:
        client.owner_user_id = owner_user_id
        storage.put_client(client)

    storage.log_event(
        ActivityEvent(
            event_type=EventType.client_registered,
            client_id=resp.client_id,
            metadata={"client_name": resp.client_name},
        )
    )
    return resp


@router.get(
    "/clients/{client_id}",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Client not found"},
    },
)
async def get_client(
    client_id: str,
    claims: dict[str, Any] = Depends(require_mgmt_user),
    storage: HiveStorage = Depends(_storage),
) -> ClientRegistrationResponse:
    client = storage.get_client(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    owner_user_id = _user_filter(claims)
    if owner_user_id and client.owner_user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="Client not found")
    return ClientRegistrationResponse.from_client(client)


@router.delete(
    "/clients/{client_id}",
    status_code=204,
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Client not found"},
    },
)
async def delete_client(
    client_id: str,
    claims: dict[str, Any] = Depends(require_mgmt_user),
    storage: HiveStorage = Depends(_storage),
) -> None:
    client = storage.get_client(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    owner_user_id = _user_filter(claims)
    if owner_user_id and client.owner_user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="Client not found")

    storage.delete_client(client_id)
    storage.log_event(
        ActivityEvent(
            event_type=EventType.client_deleted,
            client_id=claims["sub"],
            metadata={"deleted_client_id": client_id},
        )
    )
