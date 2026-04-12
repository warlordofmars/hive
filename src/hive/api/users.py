# Copyright (c) 2026 John Carter. All rights reserved.
"""
User management endpoints for the Hive management API.

GET /users/me — any authenticated management user.
GET /users — admin only, lists all users.
PATCH /users/{user_id} — admin only, update role.
GET /users/{user_id}/stats — admin only, per-user memory/client counts.
DELETE /users/{user_id} — admin only.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from hive.api._auth import require_admin, require_mgmt_user
from hive.models import PagedResponse, UserResponse
from hive.storage import HiveStorage

router = APIRouter(tags=["users"])

_LIMIT_DEFAULT = 50
_LIMIT_MAX = 200


def _storage() -> HiveStorage:
    return HiveStorage()


class UpdateUserRoleRequest(BaseModel):
    role: Literal["admin", "user"]


class UserStatsResponse(BaseModel):
    user_id: str
    memory_count: int
    client_count: int


@router.get(
    "/users/me",
    summary="Get current user",
    description="Return the profile of the currently authenticated management user.",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "User not found"},
    },
)
async def get_me(
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> UserResponse:
    user = storage.get_user_by_id(claims["sub"])
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.from_user(user)


@router.get(
    "/users",
    summary="List all users",
    description="Return a paginated list of all registered users. Admin only.",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Admin role required"},
    },
)
async def list_users(
    claims: Annotated[dict[str, Any], Depends(require_admin)],
    storage: Annotated[HiveStorage, Depends(_storage)],
    limit: Annotated[int, Query(ge=1, le=_LIMIT_MAX)] = _LIMIT_DEFAULT,
    cursor: Annotated[str | None, Query()] = None,
) -> PagedResponse:
    users, next_cursor = storage.list_users(limit=limit, cursor=cursor)
    return PagedResponse(
        items=[UserResponse.from_user(u).model_dump() for u in users],
        count=len(users),
        has_more=next_cursor is not None,
        next_cursor=next_cursor,
    )


@router.patch(
    "/users/{user_id}",
    summary="Update user role",
    description="Promote or demote a user's role. Admin only.",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Admin role required"},
        404: {"description": "User not found"},
    },
)
async def update_user_role(
    user_id: str,
    body: UpdateUserRoleRequest,
    claims: Annotated[dict[str, Any], Depends(require_admin)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> UserResponse:
    updated = storage.update_user_role(user_id, body.role)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    user = storage.get_user_by_id(user_id)
    if user is None:  # pragma: no cover
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.from_user(user)


@router.get(
    "/users/{user_id}/stats",
    summary="Get per-user statistics",
    description="Return memory and client counts for a user. Admin only.",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Admin role required"},
        404: {"description": "User not found"},
    },
)
async def get_user_stats(
    user_id: str,
    claims: Annotated[dict[str, Any], Depends(require_admin)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> UserStatsResponse:
    user = storage.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    memory_count = storage.count_memories(owner_user_id=user_id)
    client_count = storage.count_clients(owner_user_id=user_id)
    return UserStatsResponse(
        user_id=user_id,
        memory_count=memory_count,
        client_count=client_count,
    )


@router.delete(
    "/users/{user_id}",
    summary="Delete a user",
    description="Permanently delete a user account by ID. Admin only.",
    status_code=204,
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Admin role required"},
        404: {"description": "User not found"},
    },
)
async def delete_user(
    user_id: str,
    claims: Annotated[dict[str, Any], Depends(require_admin)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> None:
    deleted = storage.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
