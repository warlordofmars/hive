"""
Memory CRUD endpoints for the Hive management API.

All routes require a valid OAuth 2.1 Bearer token via the auth dependency.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from hive.api._auth import require_token
from hive.models import ActivityEvent, EventType, Memory, MemoryCreate, MemoryResponse, MemoryUpdate
from hive.storage import HiveStorage

router = APIRouter(tags=["memories"])


def _storage() -> HiveStorage:
    return HiveStorage()


@router.get("/memories", response_model=list[MemoryResponse])
async def list_memories(
    tag: str | None = Query(None, description="Filter by tag"),
    auth: tuple[HiveStorage, str] = Depends(require_token),
) -> list[MemoryResponse]:
    storage, client_id = auth
    memories = storage.list_memories_by_tag(tag) if tag else storage.list_all_memories()
    return [MemoryResponse.from_memory(m) for m in memories]


@router.post("/memories", response_model=MemoryResponse, status_code=201)
async def create_memory(
    body: MemoryCreate,
    auth: tuple[HiveStorage, str] = Depends(require_token),
) -> MemoryResponse:
    storage, client_id = auth

    # Reject duplicate keys
    existing = storage.get_memory_by_key(body.key)
    if existing:
        raise HTTPException(status_code=409, detail=f"Memory with key '{body.key}' already exists")

    memory = Memory(key=body.key, value=body.value, tags=body.tags, owner_client_id=client_id)
    storage.put_memory(memory)
    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_created,
            client_id=client_id,
            metadata={"key": body.key, "tags": body.tags},
        )
    )
    return MemoryResponse.from_memory(memory)


@router.get("/memories/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: str,
    auth: tuple[HiveStorage, str] = Depends(require_token),
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
    auth: tuple[HiveStorage, str] = Depends(require_token),
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

    storage.put_memory(memory)
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
    auth: tuple[HiveStorage, str] = Depends(require_token),
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
