# Copyright (c) 2026 John Carter. All rights reserved.
"""
Memory CRUD endpoints for the Hive management API.

All routes require a valid management JWT via require_mgmt_user.
Non-admin users can only access their own memories (owner_user_id filtering).
Admins can access all memories.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from hive.api._auth import require_mgmt_user
from hive.models import (
    ActivityEvent,
    EventType,
    Memory,
    MemoryCreate,
    MemoryResponse,
    MemorySearchResult,
    MemoryUpdate,
    PagedResponse,
)
from hive.storage import HiveStorage
from hive.vector_store import VectorIndexNotFoundError, VectorStore

router = APIRouter(tags=["memories"])

_LIMIT_DEFAULT = 50
_LIMIT_MAX = 200


def _storage() -> HiveStorage:
    return HiveStorage()


def _vector_store() -> VectorStore:
    return VectorStore()


def _user_filter(claims: dict[str, Any]) -> str | None:
    """Return owner_user_id filter for non-admins; None for admins (see all)."""
    return None if claims.get("role") == "admin" else claims["sub"]


@router.get("/memories")
async def list_memories(
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
    vs: Annotated[VectorStore, Depends(_vector_store)],
    tag: Annotated[str | None, Query(description="Filter by tag")] = None,
    search: Annotated[str | None, Query(description="Semantic search query")] = None,
    limit: Annotated[
        int, Query(ge=1, le=_LIMIT_MAX, description="Max items to return")
    ] = _LIMIT_DEFAULT,
    cursor: Annotated[
        str | None, Query(description="Pagination cursor from previous response")
    ] = None,
) -> PagedResponse:
    owner_user_id = _user_filter(claims)

    if search:
        # Semantic search — top-K, no pagination
        client_id: str = claims["sub"]
        try:
            pairs = vs.search(search, client_id, top_k=min(limit, 50))
        except VectorIndexNotFoundError:
            return PagedResponse(items=[], count=0, has_more=False, next_cursor=None)
        results = storage.hydrate_memory_ids(pairs)
        if owner_user_id:
            results = [(m, s) for m, s in results if m.owner_user_id == owner_user_id]
        return PagedResponse(
            items=[
                MemorySearchResult.from_memory_and_score(m, score).model_dump()
                for m, score in results
            ],
            count=len(results),
            has_more=False,
            next_cursor=None,
        )

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


@router.post("/memories")
async def create_memory(
    body: MemoryCreate,
    response: Response,
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
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


@router.get("/memories/{memory_id}")
async def get_memory(
    memory_id: str,
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> MemoryResponse:
    memory = storage.get_memory_by_id(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    owner_user_id = _user_filter(claims)
    if owner_user_id and memory.owner_user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="Memory not found")
    return MemoryResponse.from_memory(memory)


@router.patch("/memories/{memory_id}")
async def update_memory(
    memory_id: str,
    body: MemoryUpdate,
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
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
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
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
