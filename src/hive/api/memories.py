# Copyright (c) 2026 John Carter. All rights reserved.
"""
Memory CRUD endpoints for the Hive management API.

All routes require a valid OAuth 2.1 Bearer token via the auth dependency.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from hive.api._auth import require_memories_read, require_memories_write
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


@router.get("/memories", response_model=PagedResponse)
async def list_memories(
    tag: str | None = Query(None, description="Filter by tag"),
    limit: int = Query(_LIMIT_DEFAULT, ge=1, le=_LIMIT_MAX, description="Max items to return"),
    cursor: str | None = Query(None, description="Pagination cursor from previous response"),
    auth: tuple[HiveStorage, str] = Depends(require_memories_read),
) -> PagedResponse:
    storage, _ = auth
    if tag:
        items, next_cursor = storage.list_memories_by_tag(tag, limit=limit, cursor=cursor)
    else:
        items, next_cursor = storage.list_all_memories(limit=limit, cursor=cursor)
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
    auth: tuple[HiveStorage, str] = Depends(require_memories_write),
) -> MemoryResponse:
    storage, client_id = auth

    existing = storage.get_memory_by_key(body.key)
    if existing:
        # Upsert: update existing memory instead of rejecting
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
                client_id=client_id,
                metadata={"key": body.key, "tags": body.tags},
            )
        )
        response.status_code = 200
        return MemoryResponse.from_memory(existing)

    memory = Memory(key=body.key, value=body.value, tags=body.tags, owner_client_id=client_id)
    try:
        storage.put_memory(memory)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_created,
            client_id=client_id,
            metadata={"key": body.key, "tags": body.tags},
        )
    )
    response.status_code = 201
    return MemoryResponse.from_memory(memory)


@router.get("/memories/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: str,
    auth: tuple[HiveStorage, str] = Depends(require_memories_read),
) -> MemoryResponse:
    storage, _ = auth
    memory = storage.get_memory_by_id(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return MemoryResponse.from_memory(memory)


@router.patch("/memories/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: str,
    body: MemoryUpdate,
    auth: tuple[HiveStorage, str] = Depends(require_memories_write),
) -> MemoryResponse:
    storage, client_id = auth
    memory = storage.get_memory_by_id(memory_id)
    if memory is None:
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
            client_id=client_id,
            metadata={"memory_id": memory_id},
        )
    )
    return MemoryResponse.from_memory(memory)


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: str,
    auth: tuple[HiveStorage, str] = Depends(require_memories_write),
) -> None:
    storage, client_id = auth
    deleted = storage.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_deleted,
            client_id=client_id,
            metadata={"memory_id": memory_id},
        )
    )
