# Copyright (c) 2026 John Carter. All rights reserved.
"""
Workspace mutation service — storage mutations + compliance audit events (#495).

Every workspace membership mutation (create/delete workspace, invite sent /
accepted, role change, member removal) must leave a structured entry in the
immutable audit log (#395). This module pairs each mutation with its audit
event so the two can never drift apart. The membership-mutation API
endpoints (#492) call these helpers instead of raw ``HiveStorage`` methods.

Authorization (who may invite / remove / re-role) stays with the caller —
this layer only guarantees that the mutation and its audit trail happen
together. Audit events follow the existing ``ActivityEvent`` structure:
``client_id`` carries the acting user's id (matching the management API's
convention of logging ``claims["sub"]`` as the actor) and ``metadata``
carries the mutation details.

Also home to the account-deletion sole-owner guard: a user who is the only
owner of a shared workspace cannot delete their account until they transfer
ownership or delete the workspace — otherwise the workspace would be
orphaned with members but no owner.
"""

from __future__ import annotations

from datetime import datetime

from hive.models import (
    ActivityEvent,
    EventType,
    Invite,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from hive.storage import HiveStorage


class InviteError(Exception):
    """Raised when accepting an invite that is missing or expired."""


def _audit(
    storage: HiveStorage,
    event_type: EventType,
    actor_user_id: str,
    metadata: dict[str, object],
) -> None:
    storage.log_audit_event(
        ActivityEvent(event_type=event_type, client_id=actor_user_id, metadata=metadata)
    )


def create_workspace(
    storage: HiveStorage,
    *,
    name: str,
    owner_user_id: str,
    description: str | None = None,
    is_personal: bool = False,
    actor_user_id: str | None = None,
) -> Workspace:
    """Create a workspace with its owner membership row and audit the creation.

    ``actor_user_id`` defaults to the owner — pass it explicitly when the
    creation is performed on someone's behalf (e.g. the signup migration
    creating personal workspaces would pass ``"SYSTEM"``).
    """
    workspace = Workspace(
        name=name,
        owner_user_id=owner_user_id,
        description=description,
        is_personal=is_personal,
    )
    storage.put_workspace(workspace)
    storage.add_workspace_member(
        workspace_id=workspace.workspace_id,
        user_id=owner_user_id,
        role=WorkspaceRole.owner,
    )
    _audit(
        storage,
        EventType.workspace_created,
        actor_user_id or owner_user_id,
        {
            "workspace_id": workspace.workspace_id,
            "name": workspace.name,
            "owner_user_id": owner_user_id,
            "is_personal": is_personal,
        },
    )
    return workspace


def delete_workspace(storage: HiveStorage, *, workspace_id: str, actor_user_id: str) -> bool:
    """Delete a workspace (META + members) and audit the deletion.

    Returns False (and writes no audit event) when the workspace does not
    exist.
    """
    workspace = storage.get_workspace(workspace_id)
    if workspace is None:
        return False
    storage.delete_workspace(workspace_id)
    _audit(
        storage,
        EventType.workspace_deleted,
        actor_user_id,
        {
            "workspace_id": workspace.workspace_id,
            "name": workspace.name,
            "owner_user_id": workspace.owner_user_id,
            "is_personal": workspace.is_personal,
        },
    )
    return True


def send_invite(
    storage: HiveStorage,
    *,
    workspace_id: str,
    email: str,
    role: WorkspaceRole,
    invited_by_user_id: str,
    expires_at: datetime,
) -> Invite:
    """Create a pending invite and audit that it was sent."""
    invite = Invite(
        workspace_id=workspace_id,
        email=email,
        role=role,
        invited_by_user_id=invited_by_user_id,
        expires_at=expires_at,
    )
    storage.put_invite(invite)
    _audit(
        storage,
        EventType.workspace_invite_sent,
        invited_by_user_id,
        {
            "workspace_id": workspace_id,
            "invite_id": invite.invite_id,
            "email": email,
            "role": role.value,
        },
    )
    return invite


def accept_invite(storage: HiveStorage, *, invite_id: str, user_id: str) -> WorkspaceMember:
    """Redeem an invite: add the membership, consume the invite, audit it.

    Raises :class:`InviteError` when the invite is missing (never existed,
    already redeemed, or TTL-expired out of the table) or past its
    ``expires_at``. Matching the invite email to the accepting user is the
    caller's responsibility — it knows the authenticated user's email.
    """
    invite = storage.get_invite(invite_id)
    if invite is None or invite.is_expired:
        raise InviteError(f"Invite '{invite_id}' not found or expired.")
    member = storage.add_workspace_member(
        workspace_id=invite.workspace_id,
        user_id=user_id,
        role=invite.role,
    )
    storage.delete_invite(invite_id)
    _audit(
        storage,
        EventType.workspace_invite_accepted,
        user_id,
        {
            "workspace_id": invite.workspace_id,
            "invite_id": invite_id,
            "email": invite.email,
            "role": invite.role.value,
        },
    )
    return member


def change_member_role(
    storage: HiveStorage,
    *,
    workspace_id: str,
    user_id: str,
    role: WorkspaceRole,
    actor_user_id: str,
) -> bool:
    """Change a member's role and audit the previous → new transition.

    Returns False (no audit event) when the membership does not exist.
    """
    existing = storage.get_workspace_member(workspace_id, user_id)
    if existing is None:
        return False
    if not storage.update_workspace_member_role(workspace_id, user_id, role):
        # Membership vanished between the read and the conditional update.
        return False
    _audit(
        storage,
        EventType.workspace_member_role_changed,
        actor_user_id,
        {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "previous_role": existing.role.value,
            "new_role": role.value,
        },
    )
    return True


def remove_member(
    storage: HiveStorage,
    *,
    workspace_id: str,
    user_id: str,
    actor_user_id: str,
) -> bool:
    """Remove a member from a workspace and audit the removal.

    Returns False (no audit event) when the membership does not exist.
    A member removing themself is a "leave"; the audit event's actor vs
    ``user_id`` distinguishes the two.
    """
    existing = storage.get_workspace_member(workspace_id, user_id)
    if existing is None:
        return False
    if not storage.remove_workspace_member(workspace_id, user_id):
        # Membership vanished between the read and the delete.
        return False
    _audit(
        storage,
        EventType.workspace_member_removed,
        actor_user_id,
        {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "role": existing.role.value,
        },
    )
    return True


def list_sole_owned_shared_workspaces(storage: HiveStorage, user_id: str) -> list[Workspace]:
    """Return shared workspaces where the user is the only owner-role member.

    Used by the account-deletion guard (#495): deleting the account of a
    sole owner would orphan the workspace for its remaining members, so
    deletion is blocked until ownership is transferred or the workspace is
    deleted. Personal workspaces are excluded — they die with the account.
    Ordering follows ``list_workspaces_for_user`` (stable by workspace_id).
    """
    blocking: list[Workspace] = []
    for workspace in storage.list_workspaces_for_user(user_id):
        if workspace.is_personal:
            continue
        members = storage.list_workspace_members(workspace.workspace_id)
        owners = {m.user_id for m in members if m.role == WorkspaceRole.owner}
        if owners == {user_id}:
            blocking.append(workspace)
    return blocking
