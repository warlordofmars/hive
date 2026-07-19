# Copyright (c) 2026 John Carter. All rights reserved.
"""
Unit tests for the workspace mutation service (#495).

Every membership mutation must pair with a structured audit event; the
sole-owner guard drives the account-deletion block. Uses moto to mock
DynamoDB, mirroring test_storage.py.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import boto3
import pytest

os.environ.setdefault("HIVE_TABLE_NAME", "hive-test-ws-service")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

from moto import mock_aws

from hive import workspace_service
from hive.models import EventType, WorkspaceRole
from hive.storage import HiveStorage


@pytest.fixture()
def storage():
    """Provide a HiveStorage backed by a fresh moto-mocked DynamoDB table."""
    with mock_aws():
        _create_table()
        yield HiveStorage(table_name="hive-test-ws-service", region="us-east-1")


def _create_table():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="hive-test-ws-service",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI5PK", "AttributeType": "S"},
            {"AttributeName": "GSI5SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "WorkspaceMemberIndex",
                "KeySchema": [
                    {"AttributeName": "GSI5PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI5SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _audit_events(storage, event_type=None):
    """Read back today's audit events via the real audit read path."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return storage.get_audit_events_for_dates(
        [today], event_type=event_type.value if event_type else None
    )


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=7)


class TestCreateWorkspace:
    def test_creates_workspace_with_owner_membership(self, storage):
        ws = workspace_service.create_workspace(
            storage, name="Team Alpha", owner_user_id="u1", description="desc"
        )
        stored = storage.get_workspace(ws.workspace_id)
        assert stored is not None
        assert stored.name == "Team Alpha"
        assert stored.description == "desc"
        assert stored.is_personal is False
        member = storage.get_workspace_member(ws.workspace_id, "u1")
        assert member is not None
        assert member.role == WorkspaceRole.owner

    def test_audits_creation_with_owner_as_default_actor(self, storage):
        ws = workspace_service.create_workspace(storage, name="Team", owner_user_id="u1")
        events = _audit_events(storage, EventType.workspace_created)
        assert len(events) == 1
        event = events[0]
        assert event.client_id == "u1"
        assert event.metadata == {
            "workspace_id": ws.workspace_id,
            "name": "Team",
            "owner_user_id": "u1",
            "is_personal": False,
        }

    def test_actor_override_and_personal_flag(self, storage):
        ws = workspace_service.create_workspace(
            storage,
            name="Personal",
            owner_user_id="u1",
            is_personal=True,
            actor_user_id="SYSTEM",
        )
        assert ws.is_personal is True
        events = _audit_events(storage, EventType.workspace_created)
        assert events[0].client_id == "SYSTEM"
        assert events[0].metadata["is_personal"] is True


class TestDeleteWorkspace:
    def test_deletes_workspace_and_audits(self, storage):
        ws = workspace_service.create_workspace(storage, name="Doomed", owner_user_id="u1")
        assert (
            workspace_service.delete_workspace(
                storage, workspace_id=ws.workspace_id, actor_user_id="u1"
            )
            is True
        )
        assert storage.get_workspace(ws.workspace_id) is None
        events = _audit_events(storage, EventType.workspace_deleted)
        assert len(events) == 1
        assert events[0].client_id == "u1"
        assert events[0].metadata == {
            "workspace_id": ws.workspace_id,
            "name": "Doomed",
            "owner_user_id": "u1",
            "is_personal": False,
        }

    def test_missing_workspace_returns_false_without_audit(self, storage):
        assert (
            workspace_service.delete_workspace(storage, workspace_id="nope", actor_user_id="u1")
            is False
        )
        assert _audit_events(storage, EventType.workspace_deleted) == []

    def test_workspace_vanishing_mid_delete_returns_false_without_audit(self, storage, monkeypatch):
        ws = workspace_service.create_workspace(storage, name="Racy", owner_user_id="u1")
        monkeypatch.setattr(HiveStorage, "delete_workspace", lambda self, ws_id: False)
        assert (
            workspace_service.delete_workspace(
                storage, workspace_id=ws.workspace_id, actor_user_id="u1"
            )
            is False
        )
        assert _audit_events(storage, EventType.workspace_deleted) == []


class TestSendInvite:
    def test_missing_workspace_raises_without_invite_or_audit(self, storage):
        with pytest.raises(workspace_service.WorkspaceNotFoundError):
            workspace_service.send_invite(
                storage,
                workspace_id="ghost-ws",
                email="new@example.com",
                role=WorkspaceRole.member,
                invited_by_user_id="u1",
                expires_at=_future(),
            )
        assert _audit_events(storage, EventType.workspace_invite_sent) == []

    def test_persists_invite_and_audits(self, storage):
        ws = workspace_service.create_workspace(storage, name="Team", owner_user_id="u1")
        invite = workspace_service.send_invite(
            storage,
            workspace_id=ws.workspace_id,
            email="new@example.com",
            role=WorkspaceRole.admin,
            invited_by_user_id="u1",
            expires_at=_future(),
        )
        stored = storage.get_invite(invite.invite_id)
        assert stored is not None
        assert stored.email == "new@example.com"
        assert stored.role == WorkspaceRole.admin
        events = _audit_events(storage, EventType.workspace_invite_sent)
        assert len(events) == 1
        assert events[0].client_id == "u1"
        assert events[0].metadata == {
            "workspace_id": ws.workspace_id,
            "invite_id": invite.invite_id,
            "email": "new@example.com",
            "role": "admin",
        }


class TestAcceptInvite:
    def test_adds_member_consumes_invite_and_audits(self, storage):
        ws = workspace_service.create_workspace(storage, name="Team", owner_user_id="u1")
        invite = workspace_service.send_invite(
            storage,
            workspace_id=ws.workspace_id,
            email="new@example.com",
            role=WorkspaceRole.member,
            invited_by_user_id="u1",
            expires_at=_future(),
        )
        member = workspace_service.accept_invite(storage, invite_id=invite.invite_id, user_id="u2")
        assert member.workspace_id == ws.workspace_id
        assert member.role == WorkspaceRole.member
        assert storage.get_workspace_member(ws.workspace_id, "u2") is not None
        assert storage.get_invite(invite.invite_id) is None
        events = _audit_events(storage, EventType.workspace_invite_accepted)
        assert len(events) == 1
        assert events[0].client_id == "u2"
        assert events[0].metadata == {
            "workspace_id": ws.workspace_id,
            "invite_id": invite.invite_id,
            "email": "new@example.com",
            "role": "member",
        }

    def test_missing_invite_raises_without_audit(self, storage):
        with pytest.raises(workspace_service.InviteError):
            workspace_service.accept_invite(storage, invite_id="ghost", user_id="u2")
        assert _audit_events(storage, EventType.workspace_invite_accepted) == []

    def test_expired_invite_raises_without_audit(self, storage):
        ws = workspace_service.create_workspace(storage, name="Team", owner_user_id="u1")
        expired = workspace_service.send_invite(
            storage,
            workspace_id=ws.workspace_id,
            email="late@example.com",
            role=WorkspaceRole.member,
            invited_by_user_id="u1",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        with pytest.raises(workspace_service.InviteError):
            workspace_service.accept_invite(storage, invite_id=expired.invite_id, user_id="u2")
        assert storage.get_workspace_member(ws.workspace_id, "u2") is None
        assert _audit_events(storage, EventType.workspace_invite_accepted) == []

    def test_workspace_deleted_after_invite_raises_without_membership_or_audit(self, storage):
        ws = workspace_service.create_workspace(storage, name="Doomed", owner_user_id="u1")
        invite = workspace_service.send_invite(
            storage,
            workspace_id=ws.workspace_id,
            email="orphan@example.com",
            role=WorkspaceRole.member,
            invited_by_user_id="u1",
            expires_at=_future(),
        )
        storage.delete_workspace(ws.workspace_id)
        with pytest.raises(workspace_service.WorkspaceNotFoundError):
            workspace_service.accept_invite(storage, invite_id=invite.invite_id, user_id="u2")
        # No orphaned MEMBER row, invite left to TTL, no audit event.
        assert storage.get_workspace_member(ws.workspace_id, "u2") is None
        assert storage.get_invite(invite.invite_id) is not None
        assert _audit_events(storage, EventType.workspace_invite_accepted) == []


class TestChangeMemberRole:
    def test_updates_role_and_audits_transition(self, storage):
        ws = workspace_service.create_workspace(storage, name="Team", owner_user_id="u1")
        storage.add_workspace_member(
            workspace_id=ws.workspace_id, user_id="u2", role=WorkspaceRole.member
        )
        ok = workspace_service.change_member_role(
            storage,
            workspace_id=ws.workspace_id,
            user_id="u2",
            role=WorkspaceRole.admin,
            actor_user_id="u1",
        )
        assert ok is True
        member = storage.get_workspace_member(ws.workspace_id, "u2")
        assert member is not None
        assert member.role == WorkspaceRole.admin
        events = _audit_events(storage, EventType.workspace_member_role_changed)
        assert len(events) == 1
        assert events[0].client_id == "u1"
        assert events[0].metadata == {
            "workspace_id": ws.workspace_id,
            "user_id": "u2",
            "previous_role": "member",
            "new_role": "admin",
        }

    def test_missing_membership_returns_false_without_audit(self, storage):
        ws = workspace_service.create_workspace(storage, name="Team", owner_user_id="u1")
        ok = workspace_service.change_member_role(
            storage,
            workspace_id=ws.workspace_id,
            user_id="ghost",
            role=WorkspaceRole.admin,
            actor_user_id="u1",
        )
        assert ok is False
        assert _audit_events(storage, EventType.workspace_member_role_changed) == []

    def test_membership_vanishing_mid_update_returns_false(self, storage, monkeypatch):
        ws = workspace_service.create_workspace(storage, name="Team", owner_user_id="u1")
        storage.add_workspace_member(
            workspace_id=ws.workspace_id, user_id="u2", role=WorkspaceRole.member
        )
        monkeypatch.setattr(
            HiveStorage, "update_workspace_member_role", lambda self, ws_id, uid, role: False
        )
        ok = workspace_service.change_member_role(
            storage,
            workspace_id=ws.workspace_id,
            user_id="u2",
            role=WorkspaceRole.admin,
            actor_user_id="u1",
        )
        assert ok is False
        assert _audit_events(storage, EventType.workspace_member_role_changed) == []


class TestRemoveMember:
    def test_removes_member_and_audits(self, storage):
        ws = workspace_service.create_workspace(storage, name="Team", owner_user_id="u1")
        storage.add_workspace_member(
            workspace_id=ws.workspace_id, user_id="u2", role=WorkspaceRole.admin
        )
        ok = workspace_service.remove_member(
            storage, workspace_id=ws.workspace_id, user_id="u2", actor_user_id="u1"
        )
        assert ok is True
        assert storage.get_workspace_member(ws.workspace_id, "u2") is None
        events = _audit_events(storage, EventType.workspace_member_removed)
        assert len(events) == 1
        assert events[0].client_id == "u1"
        assert events[0].metadata == {
            "workspace_id": ws.workspace_id,
            "user_id": "u2",
            "role": "admin",
        }

    def test_missing_membership_returns_false_without_audit(self, storage):
        ws = workspace_service.create_workspace(storage, name="Team", owner_user_id="u1")
        ok = workspace_service.remove_member(
            storage, workspace_id=ws.workspace_id, user_id="ghost", actor_user_id="u1"
        )
        assert ok is False
        assert _audit_events(storage, EventType.workspace_member_removed) == []

    def test_membership_vanishing_mid_delete_returns_false(self, storage, monkeypatch):
        ws = workspace_service.create_workspace(storage, name="Team", owner_user_id="u1")
        storage.add_workspace_member(
            workspace_id=ws.workspace_id, user_id="u2", role=WorkspaceRole.member
        )
        monkeypatch.setattr(HiveStorage, "remove_workspace_member", lambda self, ws_id, uid: False)
        ok = workspace_service.remove_member(
            storage, workspace_id=ws.workspace_id, user_id="u2", actor_user_id="u1"
        )
        assert ok is False
        assert _audit_events(storage, EventType.workspace_member_removed) == []


class TestListSoleOwnedSharedWorkspaces:
    def test_sole_owned_shared_workspace_is_returned(self, storage):
        ws = workspace_service.create_workspace(storage, name="Solo Team", owner_user_id="u1")
        result = workspace_service.list_sole_owned_shared_workspaces(storage, "u1")
        assert [w.workspace_id for w in result] == [ws.workspace_id]

    def test_shared_workspace_with_co_owner_is_not_returned(self, storage):
        ws = workspace_service.create_workspace(storage, name="Co-owned", owner_user_id="u1")
        storage.add_workspace_member(
            workspace_id=ws.workspace_id, user_id="u2", role=WorkspaceRole.owner
        )
        assert workspace_service.list_sole_owned_shared_workspaces(storage, "u1") == []

    def test_personal_workspace_is_excluded(self, storage):
        workspace_service.create_workspace(
            storage, name="Personal", owner_user_id="u1", is_personal=True
        )
        assert workspace_service.list_sole_owned_shared_workspaces(storage, "u1") == []

    def test_non_owner_membership_is_excluded(self, storage):
        ws = workspace_service.create_workspace(storage, name="Team", owner_user_id="u1")
        storage.add_workspace_member(
            workspace_id=ws.workspace_id, user_id="u2", role=WorkspaceRole.admin
        )
        # u2 is admin, not owner — their account deletion is not blocked.
        assert workspace_service.list_sole_owned_shared_workspaces(storage, "u2") == []

    def test_no_workspaces_returns_empty(self, storage):
        assert workspace_service.list_sole_owned_shared_workspaces(storage, "nobody") == []

    def test_mixed_memberships_returns_only_blocking_workspaces(self, storage):
        blocking = workspace_service.create_workspace(storage, name="Blocking", owner_user_id="u1")
        co_owned = workspace_service.create_workspace(storage, name="Co-owned", owner_user_id="u1")
        storage.add_workspace_member(
            workspace_id=co_owned.workspace_id, user_id="u2", role=WorkspaceRole.owner
        )
        workspace_service.create_workspace(
            storage, name="Personal", owner_user_id="u1", is_personal=True
        )
        result = workspace_service.list_sole_owned_shared_workspaces(storage, "u1")
        assert [w.workspace_id for w in result] == [blocking.workspace_id]
