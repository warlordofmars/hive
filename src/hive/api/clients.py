"""
OAuth client management endpoints for the Hive management API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from hive.api._auth import require_token
from hive.auth.dcr import register_client
from hive.models import (
    ActivityEvent,
    ClientRegistrationRequest,
    ClientRegistrationResponse,
    EventType,
    OAuthClient,
)
from hive.storage import HiveStorage

router = APIRouter(tags=["clients"])


class ClientSummary(ClientRegistrationResponse):
    created_at: str


@router.get("/clients", response_model=list[ClientRegistrationResponse])
async def list_clients(
    auth: tuple[HiveStorage, str] = Depends(require_token),
) -> list[ClientRegistrationResponse]:
    storage, _ = auth
    return [ClientRegistrationResponse.from_client(c) for c in storage.list_clients()]


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
