# Copyright (c) 2026 John Carter. All rights reserved.
"""
Account self-service endpoint.

DELETE /api/account — permanently erase all data for the authenticated user,
satisfying GDPR Article 17 right-to-erasure.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from hive.api._auth import require_mgmt_user
from hive.models import ActivityEvent, EventType
from hive.storage import HiveStorage

router = APIRouter(tags=["account"])


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
