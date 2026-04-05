# Copyright (c) 2026 John Carter. All rights reserved.
"""
Memory CRUD endpoints for the Hive management API.

All routes require a valid management JWT via require_mgmt_user.
Non-admin users can only access their own memories (owner_user_id filtering).
Admins can access all memories.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from hive.api._auth import require_mgmt_user
from hive.models import (
    ActivityEvent,
    EventType,
    Memory,
    MemoryCreate,
    MemoryResponse,
    MemoryUpdate,
    PagedResponse,
)
from hive.storage import HiveStorage

router = APIRouter(tags=["memories"])

_LIMIT_DEFAULT = 50
_LIMIT_MAX = 200


def _storage() -> HiveStorage:
    return HiveStorage()


def _user_filter(claims: dict[str, Any]) -> str | None:
    """Return owner_user_id filter for non-admins; None for admins (see all)."""
    return None if claims.get("role") == "admin" else claims["sub"]


@router.get("/memories", response_model=PagedResponse)
async def list_memories(
    tag: str | None = Query(None, description="Filter by tag"),
    limit: int = Query(_LIMIT_DEFAULT, ge=1, le=_LIMIT_MAX, description="Max items to return"),
    cursor: str | None = Query(None, description="Pagination cursor from previous response"),
    claims: dict[str, Any] = Depends(require_mgmt_user),
    storage: HiveStorage = Depends(_storage),
) -> PagedResponse:
    owner_user_id = _user_filter(claims)
    if tag:
        items, next_cursor = storage.list_memories_by_tag(tag, limit=limit, cursor=cursor)
        if owner_user_id:
            items = [m for m in items if m.owner_user_id == owner_user_id]
    else:
        items, next_cursor = storage.list_all_memories(
            owner_user_id=owner_user_id, limit=limit, cursor=cursor
        )
    return PagedResponse(
        items=[MemoryResponse.from_memory(m).model_dump() for m in items],
        count=len(items),
        has_more=next_cursor is not None,
        next_cursor=next_cursor,
    )


@router.post("/memories", response_model=MemoryResponse)
async def create_memory(
    body: MemoryCreate,
    response: Response,
    claims: dict[str, Any] = Depends(require_mgmt_user),
    storage: HiveStorage = Depends(_storage),
) -> MemoryResponse:
    owner_user_id: str = claims["sub"]

    existing = storage.get_memory_by_key(body.key)
    if existing:
        # Non-admins cannot overwrite another user's memory
        if (
            existing.owner_user_id is not None
            and existing.owner_user_id != owner_user_id
            and claims.get("role") != "admin"
        ):
            raise HTTPException(status_code=404, detail="Memory not found")

        existing.value = body.value
        existing.tags = body.tags
        existing.updated_at = datetime.now(timezone.utc)
        try:
            storage.put_memory(existing)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        storage.log_event(
            ActivityEvent(
                event_type=EventType.memory_updated,
                client_id=owner_user_id,
                metadata={"key": body.key, "tags": body.tags},
            )
        )
        response.status_code = 200
        return MemoryResponse.from_memory(existing)

    memory = Memory(
        key=body.key,
        value=body.value,
        tags=body.tags,
        owner_client_id=owner_user_id,
        owner_user_id=owner_user_id,
    )
    try:
        storage.put_memory(memory)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_created,
            client_id=owner_user_id,
            metadata={"key": body.key, "tags": body.tags},
        )
    )
    response.status_code = 201
    return MemoryResponse.from_memory(memory)


@router.get("/memories/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: str,
    claims: dict[str, Any] = Depends(require_mgmt_user),
    storage: HiveStorage = Depends(_storage),
) -> MemoryResponse:
    memory = storage.get_memory_by_id(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    owner_user_id = _user_filter(claims)
    if owner_user_id and memory.owner_user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="Memory not found")
    return MemoryResponse.from_memory(memory)


@router.patch("/memories/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: str,
    body: MemoryUpdate,
    claims: dict[str, Any] = Depends(require_mgmt_user),
    storage: HiveStorage = Depends(_storage),
) -> MemoryResponse:
    memory = storage.get_memory_by_id(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    owner_user_id = _user_filter(claims)
    if owner_user_id and memory.owner_user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="Memory not found")

    if body.value is not None:
        memory.value = body.value
    if body.tags is not None:
        memory.tags = body.tags
    memory.updated_at = datetime.now(timezone.utc)

    try:
        storage.put_memory(memory)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_updated,
            client_id=claims["sub"],
            metadata={"memory_id": memory_id},
        )
    )
    return MemoryResponse.from_memory(memory)


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: str,
    claims: dict[str, Any] = Depends(require_mgmt_user),
    storage: HiveStorage = Depends(_storage),
) -> None:
    memory = storage.get_memory_by_id(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    owner_user_id = _user_filter(claims)
    if owner_user_id and memory.owner_user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="Memory not found")

    storage.delete_memory(memory_id)
    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_deleted,
            client_id=claims["sub"],
            metadata={"memory_id": memory_id},
        )
    )
