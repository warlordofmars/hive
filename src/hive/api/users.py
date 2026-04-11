# Copyright (c) 2026 John Carter. All rights reserved.
"""
User management endpoints for the Hive management API.

GET /users/me — any authenticated management user.
GET /users — admin only, lists all users.
DELETE /users/{user_id} — admin only.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from hive.api._auth import require_admin, require_mgmt_user
from hive.models import PagedResponse, UserResponse
from hive.storage import HiveStorage

router = APIRouter(tags=["users"])

_LIMIT_DEFAULT = 50
_LIMIT_MAX = 200


def _storage() -> HiveStorage:
    return HiveStorage()


@router.get(
    "/users/me",
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


@router.delete(
    "/users/{user_id}",
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
