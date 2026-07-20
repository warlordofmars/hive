# Copyright (c) 2026 John Carter. All rights reserved.
"""
Workspace management endpoints (#492).

- ``POST   /api/workspaces``                        — create (caller becomes owner)
- ``GET    /api/workspaces``                        — list caller's workspaces + roles
- ``PATCH  /api/workspaces/{id}``                   — rename (owner/admin)
- ``DELETE /api/workspaces/{id}``                   — delete (owner only; 409 while
  other members remain or the workspace is Personal)
- ``GET    /api/workspaces/{id}/members``           — list members (any member)
- ``PUT    /api/workspaces/{id}/members/{user_id}`` — change role (owner/admin)
- ``DELETE /api/workspaces/{id}/members/{user_id}`` — remove member / leave
- ``POST   /api/workspaces/{id}/invites``           — create invite (owner/admin)
- ``POST   /api/invites/{id}/accept``               — accept invite (email must match)

Authorization is resolved per-request from the caller's membership row
(``storage.get_workspace_member``), not from the JWT's ``workspace_role``
claim — the management token may be scoped to a different workspace than
the one being managed, and membership rows are the source of truth (#491).
Every membership mutation goes through :mod:`hive.workspace_service` so the
compliance audit trail (#495) stays paired with the mutation.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from hive import workspace_service
from hive.api._auth import require_mgmt_user
from hive.models import Workspace, WorkspaceMember, WorkspaceRole
from hive.storage import HiveStorage
from hive.workspace_service import AlreadyMemberError, InviteError, WorkspaceNotFoundError

router = APIRouter(tags=["workspaces"])

_WORKSPACE_NOT_FOUND = "Workspace not found"
_MEMBER_NOT_FOUND = "Member not found"
_DEFAULT_INVITE_TTL_DAYS = 7
_NAME_MAX = 100
_DESCRIPTION_MAX = 500
# Deliberately loose — rejects whitespace and missing @/dot without trying to
# fully validate RFC 5322. The invite is only redeemable by a user whose
# Google-verified login email matches, so a typo'd address simply expires.
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def _invite_ttl_days() -> int:
    """Invite lifetime in days (``HIVE_INVITE_TTL_DAYS``, default 7).

    Falls back to the default when the value is unset, non-numeric, or
    non-positive — a zero/negative TTL would mint already-expired invites,
    and a parse error would 500 every invite creation.
    """
    try:
        days = int(os.environ.get("HIVE_INVITE_TTL_DAYS", ""))
    except ValueError:
        return _DEFAULT_INVITE_TTL_DAYS
    return days if days > 0 else _DEFAULT_INVITE_TTL_DAYS


def _storage() -> HiveStorage:
    return HiveStorage()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class _WorkspaceNameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=_NAME_MAX)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class WorkspaceCreateRequest(_WorkspaceNameRequest):
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX)


class WorkspaceUpdateRequest(_WorkspaceNameRequest):
    pass


class WorkspaceResponse(BaseModel):
    workspace_id: str
    name: str
    description: str | None
    is_personal: bool
    owner_user_id: str
    created_at: datetime
    role: str

    @classmethod
    def from_workspace(cls, workspace: Workspace, role: str) -> WorkspaceResponse:
        return cls(
            workspace_id=workspace.workspace_id,
            name=workspace.name,
            description=workspace.description,
            is_personal=workspace.is_personal,
            owner_user_id=workspace.owner_user_id,
            created_at=workspace.created_at,
            role=role,
        )


class MemberResponse(BaseModel):
    user_id: str
    role: str
    joined_at: datetime
    email: str | None = None
    display_name: str | None = None


class MemberRoleUpdateRequest(BaseModel):
    role: WorkspaceRole


class InviteCreateRequest(BaseModel):
    email: str = Field(max_length=320, pattern=_EMAIL_PATTERN)
    # ``owner`` is deliberately not invitable — the owner role is granted by
    # an existing owner via the role endpoint after the invitee has joined.
    role: Literal["admin", "member"] = "member"

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, value: Any) -> Any:
        # mode="before" so trimming/lowercasing happens ahead of the Field
        # pattern check — a pasted " User@Example.com " normalizes instead
        # of tripping the whitespace-rejecting regex. Non-strings pass
        # through for pydantic's own type validation to reject.
        return value.strip().lower() if isinstance(value, str) else value


class InviteResponse(BaseModel):
    invite_id: str
    workspace_id: str
    email: str
    role: str
    invited_by_user_id: str
    created_at: datetime
    expires_at: datetime


class AcceptInviteResponse(BaseModel):
    workspace_id: str
    name: str
    role: str


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _require_workspace_member(
    storage: HiveStorage, workspace_id: str, user_id: str
) -> tuple[Workspace, WorkspaceMember]:
    """Resolve (workspace, caller-membership) or raise 404 / 403.

    Matches the status-code convention of ``POST /api/account/workspace-token``
    (#491): 404 when the workspace does not exist, 403 when it exists but the
    caller is not a member.
    """
    workspace = storage.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=_WORKSPACE_NOT_FOUND)
    member = storage.get_workspace_member(workspace_id, user_id)
    if member is None:
        raise HTTPException(status_code=403, detail="You are not a member of this workspace")
    return workspace, member


def _name_taken(
    storage: HiveStorage,
    user_id: str,
    name: str,
    exclude_workspace_id: str | None = None,
) -> bool:
    """Best-effort per-user name uniqueness (#482 design decision 2).

    Workspace names are display-only and per-user unique; only the caller's
    own workspace list is checked — global uniqueness is intentionally not
    enforced.
    """
    normalized = name.lower()
    for workspace in storage.list_workspaces_for_user(user_id):
        if workspace.workspace_id == exclude_workspace_id:
            continue
        if workspace.name.strip().lower() == normalized:
            return True
    return False


def _member_response(storage: HiveStorage, member: WorkspaceMember) -> MemberResponse:
    user = storage.get_user_by_id(member.user_id)
    return MemberResponse(
        user_id=member.user_id,
        role=member.role.value,
        joined_at=member.joined_at,
        email=user.email if user else None,
        display_name=user.display_name if user else None,
    )


# ---------------------------------------------------------------------------
# Workspace CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/workspaces",
    status_code=201,
    summary="Create a workspace",
    description=(
        "Create a shared workspace. The caller becomes its owner. Workspace "
        "names are display-only and per-user unique — creating a second "
        "workspace with a name you already use fails with 409."
    ),
    responses={
        401: {"description": "Unauthorized"},
        409: {"description": "You already have a workspace with this name"},
    },
)
async def create_workspace(
    body: WorkspaceCreateRequest,
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> WorkspaceResponse:
    user_id: str = claims["sub"]
    if _name_taken(storage, user_id, body.name):
        raise HTTPException(
            status_code=409, detail=f"You already have a workspace named '{body.name}'"
        )
    workspace = workspace_service.create_workspace(
        storage, name=body.name, owner_user_id=user_id, description=body.description
    )
    return WorkspaceResponse.from_workspace(workspace, WorkspaceRole.owner.value)


@router.get(
    "/workspaces",
    summary="List my workspaces",
    description=(
        "Return every workspace the authenticated user belongs to, each with "
        "the caller's role in it."
    ),
    responses={401: {"description": "Unauthorized"}},
)
async def list_workspaces(
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> list[WorkspaceResponse]:
    user_id: str = claims["sub"]
    workspaces: list[WorkspaceResponse] = []
    for workspace in storage.list_workspaces_for_user(user_id):
        member = storage.get_workspace_member(workspace.workspace_id, user_id)
        if member is None:
            # Membership vanished between the GSI listing and this read.
            continue
        workspaces.append(WorkspaceResponse.from_workspace(workspace, member.role.value))
    return workspaces


@router.patch(
    "/workspaces/{workspace_id}",
    summary="Rename a workspace",
    description="Update a workspace's display name. Requires the owner or admin role.",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Not a member, or insufficient role"},
        404: {"description": _WORKSPACE_NOT_FOUND},
        409: {"description": "You already have a workspace with this name"},
    },
)
async def update_workspace(
    workspace_id: str,
    body: WorkspaceUpdateRequest,
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> WorkspaceResponse:
    user_id: str = claims["sub"]
    workspace, member = _require_workspace_member(storage, workspace_id, user_id)
    if member.role not in (WorkspaceRole.owner, WorkspaceRole.admin):
        raise HTTPException(
            status_code=403, detail="Owner or admin role required to rename this workspace"
        )
    if _name_taken(storage, user_id, body.name, exclude_workspace_id=workspace_id):
        raise HTTPException(
            status_code=409, detail=f"You already have a workspace named '{body.name}'"
        )
    if not storage.rename_workspace(workspace_id, body.name):
        # Deleted between the membership check and the conditional update.
        raise HTTPException(status_code=404, detail=_WORKSPACE_NOT_FOUND)
    workspace.name = body.name
    return WorkspaceResponse.from_workspace(workspace, member.role.value)


@router.delete(
    "/workspaces/{workspace_id}",
    status_code=204,
    summary="Delete a workspace",
    description=(
        "Delete a workspace and its memberships. Owner only. Personal "
        "workspaces cannot be deleted — they are removed with the account. "
        "Fails with 409 while other members remain (consistent with the "
        "account-deletion sole-owner guard, #495): remove them or transfer "
        "ownership so the new owner can decide."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Not a member, or not an owner"},
        404: {"description": _WORKSPACE_NOT_FOUND},
        409: {"description": "Workspace is Personal, or still has other members"},
    },
)
async def delete_workspace(
    workspace_id: str,
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> None:
    user_id: str = claims["sub"]
    workspace, member = _require_workspace_member(storage, workspace_id, user_id)
    if member.role is not WorkspaceRole.owner:
        raise HTTPException(status_code=403, detail="Only an owner can delete a workspace")
    if workspace.is_personal:
        raise HTTPException(
            status_code=409,
            detail="Personal workspaces cannot be deleted; they are removed with your account",
        )
    others = [m for m in storage.list_workspace_members(workspace_id) if m.user_id != user_id]
    if others:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "This workspace still has other members. Remove them or "
                    "transfer ownership before deleting it."
                ),
                "members": [{"user_id": m.user_id, "role": m.role.value} for m in others],
            },
        )
    if not workspace_service.delete_workspace(
        storage, workspace_id=workspace_id, actor_user_id=user_id
    ):
        # Deleted between the membership check and the delete.
        raise HTTPException(status_code=404, detail=_WORKSPACE_NOT_FOUND)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


@router.get(
    "/workspaces/{workspace_id}/members",
    summary="List workspace members",
    description=(
        "Return every member of the workspace with their role, join date, and "
        "profile (email / display name) where the user record still exists. "
        "Any member can list members."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Not a member of the workspace"},
        404: {"description": _WORKSPACE_NOT_FOUND},
    },
)
async def list_members(
    workspace_id: str,
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> list[MemberResponse]:
    user_id: str = claims["sub"]
    _require_workspace_member(storage, workspace_id, user_id)
    # Per-member get_user_by_id is an accepted N+1 at workspace scale —
    # membership is invite-only and human-sized, matching the per-item read
    # patterns elsewhere (e.g. list_workspaces_for_user). Swap to a
    # BatchGetItem-backed lookup if workspaces ever grow beyond that.
    return [
        _member_response(storage, member) for member in storage.list_workspace_members(workspace_id)
    ]


@router.put(
    "/workspaces/{workspace_id}/members/{user_id}",
    summary="Change a member's role",
    description=(
        "Set a member's role. Owners can set any role; admins can move "
        "non-owner members between `member` and `admin` but cannot grant or "
        "revoke the owner role. Demoting the only owner fails with 409 — "
        "promote another owner first."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Not a member, or insufficient role for this transition"},
        404: {"description": "Workspace or member not found"},
        409: {"description": "Cannot demote the only owner"},
    },
)
async def update_member_role(
    workspace_id: str,
    user_id: str,
    body: MemberRoleUpdateRequest,
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> MemberResponse:
    actor_user_id: str = claims["sub"]
    _, actor = _require_workspace_member(storage, workspace_id, actor_user_id)
    if actor.role not in (WorkspaceRole.owner, WorkspaceRole.admin):
        raise HTTPException(
            status_code=403, detail="Owner or admin role required to change member roles"
        )
    target = storage.get_workspace_member(workspace_id, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail=_MEMBER_NOT_FOUND)
    new_role = body.role
    if actor.role is WorkspaceRole.admin and WorkspaceRole.owner in (target.role, new_role):
        raise HTTPException(
            status_code=403, detail="Only an owner can grant or revoke the owner role"
        )
    if target.role is WorkspaceRole.owner and new_role is not WorkspaceRole.owner:
        owners = {
            m.user_id
            for m in storage.list_workspace_members(workspace_id)
            if m.role is WorkspaceRole.owner
        }
        if owners == {user_id}:
            raise HTTPException(
                status_code=409,
                detail="Cannot demote the only owner. Promote another owner first.",
            )
    if target.role is new_role:
        # No-op — skip the mutation so the audit trail records real changes only.
        return _member_response(storage, target)
    if not workspace_service.change_member_role(
        storage,
        workspace_id=workspace_id,
        user_id=user_id,
        role=new_role,
        actor_user_id=actor_user_id,
    ):
        # Membership vanished between the read and the conditional update.
        raise HTTPException(status_code=404, detail=_MEMBER_NOT_FOUND)
    target.role = new_role
    return _member_response(storage, target)


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    status_code=204,
    summary="Remove a member (or leave)",
    description=(
        "Remove a member from the workspace. Any member may remove themself "
        "(leave) — except the only owner, who must transfer ownership or "
        "delete the workspace instead (409). Owners can remove anyone; admins "
        "can remove non-owners; members can only remove themselves."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Not a member, or insufficient role"},
        404: {"description": "Workspace or member not found"},
        409: {"description": "The only owner cannot leave"},
    },
)
async def remove_member(
    workspace_id: str,
    user_id: str,
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> None:
    actor_user_id: str = claims["sub"]
    _, actor = _require_workspace_member(storage, workspace_id, actor_user_id)
    target = storage.get_workspace_member(workspace_id, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail=_MEMBER_NOT_FOUND)
    if user_id == actor_user_id:
        if actor.role is WorkspaceRole.owner:
            owners = {
                m.user_id
                for m in storage.list_workspace_members(workspace_id)
                if m.role is WorkspaceRole.owner
            }
            if owners == {actor_user_id}:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "You are the only owner of this workspace. Transfer "
                        "ownership or delete the workspace instead."
                    ),
                )
    elif actor.role is WorkspaceRole.member:
        raise HTTPException(status_code=403, detail="Members can only remove themselves")
    elif actor.role is WorkspaceRole.admin and target.role is WorkspaceRole.owner:
        raise HTTPException(status_code=403, detail="Admins cannot remove owners")
    if not workspace_service.remove_member(
        storage, workspace_id=workspace_id, user_id=user_id, actor_user_id=actor_user_id
    ):
        # Membership vanished between the read and the delete.
        raise HTTPException(status_code=404, detail=_MEMBER_NOT_FOUND)


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


@router.post(
    "/workspaces/{workspace_id}/invites",
    status_code=201,
    summary="Invite a user to the workspace",
    description=(
        "Create a pending invite for an email address with a `member` or "
        "`admin` role (owner is granted post-join via the role endpoint). "
        "Requires the owner or admin role. Invites expire after "
        "`HIVE_INVITE_TTL_DAYS` days (default 7) via DynamoDB TTL."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Not a member, or insufficient role"},
        404: {"description": _WORKSPACE_NOT_FOUND},
        409: {
            "description": (
                "Workspace is Personal, the email is already a member, or an "
                "invite for it is already pending"
            )
        },
    },
)
async def create_invite(
    workspace_id: str,
    body: InviteCreateRequest,
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> InviteResponse:
    actor_user_id: str = claims["sub"]
    workspace, actor = _require_workspace_member(storage, workspace_id, actor_user_id)
    if actor.role not in (WorkspaceRole.owner, WorkspaceRole.admin):
        raise HTTPException(
            status_code=403, detail="Owner or admin role required to invite members"
        )
    if workspace.is_personal:
        raise HTTPException(
            status_code=409,
            detail=(
                "Personal workspaces cannot have additional members. "
                "Create a shared workspace instead."
            ),
        )
    existing_user = storage.get_user_by_email(body.email)
    if (
        existing_user is not None
        and storage.get_workspace_member(workspace_id, existing_user.user_id) is not None
    ):
        raise HTTPException(
            status_code=409, detail=f"'{body.email}' is already a member of this workspace"
        )
    # Best-effort duplicate suppression: the pending-invite listing is a
    # filtered scan (acceptable at invite volume — see the storage-layer
    # docstring) and the check-then-write is not atomic. A duplicate that
    # slips through a concurrent race is harmless: invites are single-use
    # and TTL out, and redemption's conditional membership write means a
    # second accept cannot alter an existing member's role.
    if any(
        invite.email.lower() == body.email
        for invite in storage.list_pending_invites_for_workspace(workspace_id)
    ):
        raise HTTPException(
            status_code=409, detail=f"An invite for '{body.email}' is already pending"
        )
    expires_at = datetime.now(timezone.utc) + timedelta(days=_invite_ttl_days())
    try:
        invite = workspace_service.send_invite(
            storage,
            workspace_id=workspace_id,
            email=body.email,
            role=WorkspaceRole(body.role),
            invited_by_user_id=actor_user_id,
            expires_at=expires_at,
        )
    except WorkspaceNotFoundError as exc:
        # Deleted between the membership check and the invite write.
        raise HTTPException(status_code=404, detail=_WORKSPACE_NOT_FOUND) from exc
    return InviteResponse(
        invite_id=invite.invite_id,
        workspace_id=invite.workspace_id,
        email=invite.email,
        role=invite.role.value,
        invited_by_user_id=invite.invited_by_user_id,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
    )


@router.post(
    "/invites/{invite_id}/accept",
    summary="Accept a workspace invite",
    description=(
        "Redeem a pending invite: the authenticated user joins the workspace "
        "with the invited role and the invite is consumed (single-use). The "
        "caller's login email must match the invited address. Expired or "
        "already-redeemed invites return 404."
    ),
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Invite was issued for a different email address"},
        404: {"description": "Invite not found or expired, or workspace deleted"},
        409: {"description": "Already a member of the workspace"},
    },
)
async def accept_invite(
    invite_id: str,
    claims: Annotated[dict[str, Any], Depends(require_mgmt_user)],
    storage: Annotated[HiveStorage, Depends(_storage)],
) -> AcceptInviteResponse:
    user_id: str = claims["sub"]
    email = str(claims.get("email") or "").strip().lower()
    invite = storage.get_invite(invite_id)
    if invite is None or invite.is_expired:
        raise HTTPException(status_code=404, detail="Invite not found or expired")
    if not email or invite.email.lower() != email:
        raise HTTPException(
            status_code=403, detail="This invite was issued for a different email address"
        )
    workspace = storage.get_workspace(invite.workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=404, detail="The workspace for this invite no longer exists"
        )
    if storage.get_workspace_member(invite.workspace_id, user_id) is not None:
        # Friendly pre-check: reject without consuming the invite. The
        # atomic backstop is the service's conditional membership write —
        # a membership appearing after this check raises AlreadyMemberError
        # below rather than being overwritten with the invited role.
        raise HTTPException(status_code=409, detail="You are already a member of this workspace")
    try:
        joined = workspace_service.accept_invite(storage, invite_id=invite_id, user_id=user_id)
    except InviteError as exc:
        # Consumed or TTL-expired between the read and the atomic claim.
        raise HTTPException(status_code=404, detail="Invite not found or expired") from exc
    except AlreadyMemberError as exc:
        # Membership appeared between the pre-check and the claim; the
        # existing row (and role) is untouched.
        raise HTTPException(
            status_code=409, detail="You are already a member of this workspace"
        ) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="The workspace for this invite no longer exists"
        ) from exc
    return AcceptInviteResponse(
        workspace_id=workspace.workspace_id, name=workspace.name, role=joined.role.value
    )
