# Copyright (c) 2026 John Carter. All rights reserved.
"""
Unit tests for the workspace management endpoints (#492).

Covers the full role-authorization matrix (owner / admin / member /
non-member) on every mutating endpoint, invite expiry, and the
sole-owner 409 guards.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

os.environ.setdefault("HIVE_TABLE_NAME", "hive-unit-workspaces")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("HIVE_JWT_SECRET", "unit-test-secret")
os.environ.pop("DYNAMODB_ENDPOINT", None)

_TABLE = "hive-unit-workspaces"

_OWNER = "ws-owner-1"
_ADMIN = "ws-admin-1"
_MEMBER = "ws-member-1"
_OUTSIDER = "ws-outsider-1"
_EMAILS = {
    _OWNER: "owner@example.com",
    _ADMIN: "admin@example.com",
    _MEMBER: "member@example.com",
    _OUTSIDER: "outsider@example.com",
}


def _create_table() -> None:
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=_TABLE,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
            {"AttributeName": "GSI4PK", "AttributeType": "S"},
            {"AttributeName": "GSI5PK", "AttributeType": "S"},
            {"AttributeName": "GSI5SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "TagIndex",
                "KeySchema": [
                    {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "UserEmailIndex",
                "KeySchema": [
                    {"AttributeName": "GSI4PK", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
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


class Ctx:
    """Test context: client + storage + claims switcher + seeded workspace."""

    def __init__(
        self, client: TestClient, storage: Any, claims: dict[str, Any], workspace_id: str
    ) -> None:
        self.client = client
        self.storage = storage
        self._claims = claims
        self.workspace_id = workspace_id

    def login(self, user_id: str, email: str | None = None) -> None:
        self._claims.clear()
        self._claims.update(
            {
                "sub": user_id,
                "role": "user",
                "email": _EMAILS.get(user_id, f"{user_id}@example.com") if email is None else email,
            }
        )

    def login_claims(self, claims: dict[str, Any]) -> None:
        self._claims.clear()
        self._claims.update(claims)


@pytest.fixture()
def ctx():
    with mock_aws():
        _create_table()
        from hive import workspace_service
        from hive.api import _auth as auth_mod
        from hive.api import workspaces as workspaces_mod
        from hive.api.main import app
        from hive.models import User, WorkspaceRole
        from hive.storage import HiveStorage

        storage = HiveStorage(table_name=_TABLE, region="us-east-1")
        for user_id, email in _EMAILS.items():
            storage.put_user(User(user_id=user_id, email=email, display_name=user_id, role="user"))

        ws = workspace_service.create_workspace(storage, name="Team Alpha", owner_user_id=_OWNER)
        storage.add_workspace_member(ws.workspace_id, _ADMIN, WorkspaceRole.admin)
        storage.add_workspace_member(ws.workspace_id, _MEMBER, WorkspaceRole.member)

        claims: dict[str, Any] = {}

        def _override_mgmt_user() -> dict[str, Any]:
            return dict(claims)

        def _override_storage() -> HiveStorage:
            return storage

        app.dependency_overrides[auth_mod.require_mgmt_user] = _override_mgmt_user
        app.dependency_overrides[workspaces_mod._storage] = _override_storage
        context = Ctx(TestClient(app), storage, claims, ws.workspace_id)
        context.login(_OWNER)
        yield context
        app.dependency_overrides.clear()


@pytest.fixture()
def unauthed_client():
    with mock_aws():
        _create_table()
        from hive.api.main import app

        app.dependency_overrides.clear()
        yield TestClient(app, raise_server_exceptions=False)


def _role_of(ctx: Ctx, workspace_id: str, user_id: str) -> str | None:
    member = ctx.storage.get_workspace_member(workspace_id, user_id)
    return None if member is None else member.role.value


def _audit_events(ctx: Ctx, event_type: str) -> list[Any]:
    # Query today and yesterday so a test spanning midnight UTC cannot miss
    # an event written just before the day boundary.
    now = datetime.now(timezone.utc)
    dates = [(now - timedelta(days=1)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")]
    return ctx.storage.get_audit_events_for_dates(dates, event_type=event_type)


class TestHelpers:
    def test_storage_dep_returns_hive_storage(self):
        with mock_aws():
            _create_table()
            from hive.api.workspaces import _storage
            from hive.storage import HiveStorage

            assert isinstance(_storage(), HiveStorage)

    def test_invite_ttl_days_default(self, monkeypatch):
        from hive.api.workspaces import _invite_ttl_days

        monkeypatch.delenv("HIVE_INVITE_TTL_DAYS", raising=False)
        assert _invite_ttl_days() == 7

    def test_invite_ttl_days_env_override(self, monkeypatch):
        from hive.api.workspaces import _invite_ttl_days

        monkeypatch.setenv("HIVE_INVITE_TTL_DAYS", "1")
        assert _invite_ttl_days() == 1

    @pytest.mark.parametrize("raw", ["not-a-number", "", "0", "-3"])
    def test_invite_ttl_days_invalid_values_fall_back_to_default(self, monkeypatch, raw):
        from hive.api.workspaces import _invite_ttl_days

        monkeypatch.setenv("HIVE_INVITE_TTL_DAYS", raw)
        assert _invite_ttl_days() == 7


class TestCreateWorkspace:
    def test_creator_becomes_owner(self, ctx):
        resp = ctx.client.post("/api/workspaces", json={"name": "Team Beta"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Team Beta"
        assert body["role"] == "owner"
        assert body["owner_user_id"] == _OWNER
        assert body["is_personal"] is False
        assert _role_of(ctx, body["workspace_id"], _OWNER) == "owner"

    def test_name_is_stripped(self, ctx):
        resp = ctx.client.post("/api/workspaces", json={"name": "  Padded Name  "})
        assert resp.status_code == 201
        assert resp.json()["name"] == "Padded Name"

    def test_description_round_trips(self, ctx):
        resp = ctx.client.post(
            "/api/workspaces", json={"name": "Documented", "description": "notes"}
        )
        assert resp.status_code == 201
        assert resp.json()["description"] == "notes"

    def test_duplicate_name_conflicts_case_insensitively(self, ctx):
        resp = ctx.client.post("/api/workspaces", json={"name": "  team ALPHA "})
        assert resp.status_code == 409

    def test_same_name_allowed_for_different_user(self, ctx):
        ctx.login(_OUTSIDER)
        resp = ctx.client.post("/api/workspaces", json={"name": "Team Alpha"})
        assert resp.status_code == 201

    def test_blank_name_rejected(self, ctx):
        resp = ctx.client.post("/api/workspaces", json={"name": "   "})
        assert resp.status_code == 422

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.post("/api/workspaces", json={"name": "X"})
        assert resp.status_code in (401, 403)


class TestListWorkspaces:
    @pytest.mark.parametrize(
        ("user_id", "role"), [(_OWNER, "owner"), (_ADMIN, "admin"), (_MEMBER, "member")]
    )
    def test_lists_workspace_with_caller_role(self, ctx, user_id, role):
        ctx.login(user_id)
        resp = ctx.client.get("/api/workspaces")
        assert resp.status_code == 200
        rows = resp.json()
        assert [r["workspace_id"] for r in rows] == [ctx.workspace_id]
        assert rows[0]["role"] == role

    def test_non_member_sees_empty_list(self, ctx):
        ctx.login(_OUTSIDER)
        resp = ctx.client.get("/api/workspaces")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_vanished_membership_is_skipped(self, ctx, monkeypatch):
        monkeypatch.setattr(ctx.storage, "get_workspace_member", lambda *a, **k: None)
        resp = ctx.client.get("/api/workspaces")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.get("/api/workspaces")
        assert resp.status_code in (401, 403)


class TestRenameWorkspace:
    @pytest.mark.parametrize("user_id", [_OWNER, _ADMIN])
    def test_owner_and_admin_can_rename(self, ctx, user_id):
        ctx.login(user_id)
        resp = ctx.client.patch(
            f"/api/workspaces/{ctx.workspace_id}", json={"name": f"Renamed by {user_id}"}
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == f"Renamed by {user_id}"
        assert ctx.storage.get_workspace(ctx.workspace_id).name == f"Renamed by {user_id}"

    def test_member_cannot_rename(self, ctx):
        ctx.login(_MEMBER)
        resp = ctx.client.patch(f"/api/workspaces/{ctx.workspace_id}", json={"name": "Nope"})
        assert resp.status_code == 403

    def test_non_member_cannot_rename(self, ctx):
        ctx.login(_OUTSIDER)
        resp = ctx.client.patch(f"/api/workspaces/{ctx.workspace_id}", json={"name": "Nope"})
        assert resp.status_code == 403

    def test_missing_workspace_404(self, ctx):
        resp = ctx.client.patch("/api/workspaces/ghost", json={"name": "Nope"})
        assert resp.status_code == 404

    def test_rename_conflicts_with_another_owned_workspace(self, ctx):
        assert ctx.client.post("/api/workspaces", json={"name": "Team Beta"}).status_code == 201
        resp = ctx.client.patch(f"/api/workspaces/{ctx.workspace_id}", json={"name": "team beta"})
        assert resp.status_code == 409

    def test_rename_to_own_current_name_is_allowed(self, ctx):
        resp = ctx.client.patch(f"/api/workspaces/{ctx.workspace_id}", json={"name": "Team Alpha"})
        assert resp.status_code == 200

    def test_workspace_vanishing_mid_rename_404(self, ctx, monkeypatch):
        monkeypatch.setattr(ctx.storage, "rename_workspace", lambda *a, **k: False)
        resp = ctx.client.patch(f"/api/workspaces/{ctx.workspace_id}", json={"name": "Gone"})
        assert resp.status_code == 404

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.patch("/api/workspaces/x", json={"name": "X"})
        assert resp.status_code in (401, 403)


class TestDeleteWorkspace:
    @pytest.mark.parametrize("user_id", [_ADMIN, _MEMBER])
    def test_non_owner_roles_cannot_delete(self, ctx, user_id):
        ctx.login(user_id)
        resp = ctx.client.delete(f"/api/workspaces/{ctx.workspace_id}")
        assert resp.status_code == 403

    def test_non_member_cannot_delete(self, ctx):
        ctx.login(_OUTSIDER)
        resp = ctx.client.delete(f"/api/workspaces/{ctx.workspace_id}")
        assert resp.status_code == 403

    def test_delete_blocked_while_other_members_remain(self, ctx):
        resp = ctx.client.delete(f"/api/workspaces/{ctx.workspace_id}")
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        remaining = {m["user_id"] for m in detail["members"]}
        assert remaining == {_ADMIN, _MEMBER}
        assert ctx.storage.get_workspace(ctx.workspace_id) is not None

    def test_personal_workspace_cannot_be_deleted(self, ctx):
        from hive import workspace_service

        personal = workspace_service.create_workspace(
            ctx.storage, name="My Personal", owner_user_id=_OWNER, is_personal=True
        )
        resp = ctx.client.delete(f"/api/workspaces/{personal.workspace_id}")
        assert resp.status_code == 409
        assert ctx.storage.get_workspace(personal.workspace_id) is not None

    def test_sole_member_owner_can_delete(self, ctx):
        created = ctx.client.post("/api/workspaces", json={"name": "Disposable"}).json()
        resp = ctx.client.delete(f"/api/workspaces/{created['workspace_id']}")
        assert resp.status_code == 204
        assert ctx.storage.get_workspace(created["workspace_id"]) is None
        deleted = [
            e
            for e in _audit_events(ctx, "workspace_deleted")
            if e.metadata.get("workspace_id") == created["workspace_id"]
        ]
        assert len(deleted) == 1

    def test_missing_workspace_404(self, ctx):
        resp = ctx.client.delete("/api/workspaces/ghost")
        assert resp.status_code == 404

    def test_workspace_vanishing_mid_delete_404(self, ctx, monkeypatch):
        created = ctx.client.post("/api/workspaces", json={"name": "Vanishing"}).json()
        monkeypatch.setattr("hive.workspace_service.delete_workspace", lambda *a, **k: False)
        resp = ctx.client.delete(f"/api/workspaces/{created['workspace_id']}")
        assert resp.status_code == 404

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.delete("/api/workspaces/x")
        assert resp.status_code in (401, 403)


class TestListMembers:
    def test_any_member_can_list(self, ctx):
        ctx.login(_MEMBER)
        resp = ctx.client.get(f"/api/workspaces/{ctx.workspace_id}/members")
        assert resp.status_code == 200
        rows = {r["user_id"]: r for r in resp.json()}
        assert set(rows) == {_OWNER, _ADMIN, _MEMBER}
        assert rows[_OWNER]["role"] == "owner"
        assert rows[_ADMIN]["role"] == "admin"
        assert rows[_MEMBER]["email"] == _EMAILS[_MEMBER]
        assert rows[_MEMBER]["display_name"] == _MEMBER

    def test_member_without_user_record_has_null_profile(self, ctx):
        from hive.models import WorkspaceRole

        ctx.storage.add_workspace_member(ctx.workspace_id, "ghost-user", WorkspaceRole.member)
        resp = ctx.client.get(f"/api/workspaces/{ctx.workspace_id}/members")
        rows = {r["user_id"]: r for r in resp.json()}
        assert rows["ghost-user"]["email"] is None
        assert rows["ghost-user"]["display_name"] is None

    def test_non_member_cannot_list(self, ctx):
        ctx.login(_OUTSIDER)
        resp = ctx.client.get(f"/api/workspaces/{ctx.workspace_id}/members")
        assert resp.status_code == 403

    def test_missing_workspace_404(self, ctx):
        resp = ctx.client.get("/api/workspaces/ghost/members")
        assert resp.status_code == 404

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.get("/api/workspaces/x/members")
        assert resp.status_code in (401, 403)


class TestUpdateMemberRole:
    def _put(self, ctx: Ctx, target: str, role: str, workspace_id: str | None = None):
        return ctx.client.put(
            f"/api/workspaces/{workspace_id or ctx.workspace_id}/members/{target}",
            json={"role": role},
        )

    def test_owner_promotes_member_to_admin(self, ctx):
        resp = self._put(ctx, _MEMBER, "admin")
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"
        assert _role_of(ctx, ctx.workspace_id, _MEMBER) == "admin"

    def test_owner_promotes_admin_to_owner(self, ctx):
        resp = self._put(ctx, _ADMIN, "owner")
        assert resp.status_code == 200
        assert _role_of(ctx, ctx.workspace_id, _ADMIN) == "owner"

    def test_admin_promotes_member_to_admin(self, ctx):
        ctx.login(_ADMIN)
        resp = self._put(ctx, _MEMBER, "admin")
        assert resp.status_code == 200
        assert _role_of(ctx, ctx.workspace_id, _MEMBER) == "admin"

    def test_admin_demotes_another_admin(self, ctx):
        from hive.models import WorkspaceRole

        ctx.storage.add_workspace_member(ctx.workspace_id, "admin-2", WorkspaceRole.admin)
        ctx.login(_ADMIN)
        resp = self._put(ctx, "admin-2", "member")
        assert resp.status_code == 200
        assert _role_of(ctx, ctx.workspace_id, "admin-2") == "member"

    def test_admin_cannot_grant_owner(self, ctx):
        ctx.login(_ADMIN)
        resp = self._put(ctx, _MEMBER, "owner")
        assert resp.status_code == 403
        assert _role_of(ctx, ctx.workspace_id, _MEMBER) == "member"

    def test_admin_cannot_change_an_owner(self, ctx):
        ctx.login(_ADMIN)
        resp = self._put(ctx, _OWNER, "member")
        assert resp.status_code == 403
        assert _role_of(ctx, ctx.workspace_id, _OWNER) == "owner"

    def test_member_cannot_change_roles(self, ctx):
        ctx.login(_MEMBER)
        resp = self._put(ctx, _ADMIN, "member")
        assert resp.status_code == 403

    def test_non_member_cannot_change_roles(self, ctx):
        ctx.login(_OUTSIDER)
        resp = self._put(ctx, _MEMBER, "admin")
        assert resp.status_code == 403

    def test_demoting_the_only_owner_conflicts(self, ctx):
        resp = self._put(ctx, _OWNER, "member")
        assert resp.status_code == 409
        assert _role_of(ctx, ctx.workspace_id, _OWNER) == "owner"

    def test_demoting_a_co_owner_is_allowed(self, ctx):
        assert self._put(ctx, _ADMIN, "owner").status_code == 200
        resp = self._put(ctx, _OWNER, "member")
        assert resp.status_code == 200
        assert _role_of(ctx, ctx.workspace_id, _OWNER) == "member"

    def test_noop_role_change_skips_the_audit_trail(self, ctx):
        resp = self._put(ctx, _MEMBER, "member")
        assert resp.status_code == 200
        assert resp.json()["role"] == "member"
        assert _audit_events(ctx, "workspace_member_role_changed") == []

    def test_target_not_a_member_404(self, ctx):
        resp = self._put(ctx, _OUTSIDER, "admin")
        assert resp.status_code == 404

    def test_missing_workspace_404(self, ctx):
        resp = self._put(ctx, _MEMBER, "admin", workspace_id="ghost")
        assert resp.status_code == 404

    def test_invalid_role_rejected(self, ctx):
        resp = self._put(ctx, _MEMBER, "guest")
        assert resp.status_code == 422

    def test_membership_vanishing_mid_update_404(self, ctx, monkeypatch):
        monkeypatch.setattr("hive.workspace_service.change_member_role", lambda *a, **k: False)
        resp = self._put(ctx, _MEMBER, "admin")
        assert resp.status_code == 404

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.put("/api/workspaces/x/members/y", json={"role": "member"})
        assert resp.status_code in (401, 403)


class TestRemoveMember:
    def _delete(self, ctx: Ctx, target: str, workspace_id: str | None = None):
        return ctx.client.delete(
            f"/api/workspaces/{workspace_id or ctx.workspace_id}/members/{target}"
        )

    def test_owner_removes_member(self, ctx):
        resp = self._delete(ctx, _MEMBER)
        assert resp.status_code == 204
        assert _role_of(ctx, ctx.workspace_id, _MEMBER) is None

    def test_owner_removes_admin(self, ctx):
        resp = self._delete(ctx, _ADMIN)
        assert resp.status_code == 204

    def test_admin_removes_member(self, ctx):
        ctx.login(_ADMIN)
        resp = self._delete(ctx, _MEMBER)
        assert resp.status_code == 204

    def test_admin_removes_another_admin(self, ctx):
        from hive.models import WorkspaceRole

        ctx.storage.add_workspace_member(ctx.workspace_id, "admin-2", WorkspaceRole.admin)
        ctx.login(_ADMIN)
        resp = self._delete(ctx, "admin-2")
        assert resp.status_code == 204

    def test_admin_cannot_remove_owner(self, ctx):
        ctx.login(_ADMIN)
        resp = self._delete(ctx, _OWNER)
        assert resp.status_code == 403
        assert _role_of(ctx, ctx.workspace_id, _OWNER) == "owner"

    def test_member_cannot_remove_others(self, ctx):
        ctx.login(_MEMBER)
        resp = self._delete(ctx, _ADMIN)
        assert resp.status_code == 403

    def test_member_can_leave(self, ctx):
        ctx.login(_MEMBER)
        resp = self._delete(ctx, _MEMBER)
        assert resp.status_code == 204
        assert _role_of(ctx, ctx.workspace_id, _MEMBER) is None

    def test_admin_can_leave(self, ctx):
        ctx.login(_ADMIN)
        resp = self._delete(ctx, _ADMIN)
        assert resp.status_code == 204

    def test_sole_owner_cannot_leave(self, ctx):
        resp = self._delete(ctx, _OWNER)
        assert resp.status_code == 409
        assert _role_of(ctx, ctx.workspace_id, _OWNER) == "owner"

    def test_owner_can_leave_when_another_owner_exists(self, ctx):
        ctx.client.put(
            f"/api/workspaces/{ctx.workspace_id}/members/{_ADMIN}", json={"role": "owner"}
        )
        resp = self._delete(ctx, _OWNER)
        assert resp.status_code == 204
        assert _role_of(ctx, ctx.workspace_id, _OWNER) is None

    def test_non_member_cannot_remove(self, ctx):
        ctx.login(_OUTSIDER)
        resp = self._delete(ctx, _MEMBER)
        assert resp.status_code == 403

    def test_target_not_a_member_404(self, ctx):
        resp = self._delete(ctx, _OUTSIDER)
        assert resp.status_code == 404

    def test_missing_workspace_404(self, ctx):
        resp = self._delete(ctx, _MEMBER, workspace_id="ghost")
        assert resp.status_code == 404

    def test_membership_vanishing_mid_remove_404(self, ctx, monkeypatch):
        monkeypatch.setattr("hive.workspace_service.remove_member", lambda *a, **k: False)
        resp = self._delete(ctx, _MEMBER)
        assert resp.status_code == 404

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.delete("/api/workspaces/x/members/y")
        assert resp.status_code in (401, 403)


class TestCreateInvite:
    def _post(
        self,
        ctx: Ctx,
        email: str = "newcomer@example.com",
        role: str = "member",
        workspace_id: str | None = None,
    ):
        return ctx.client.post(
            f"/api/workspaces/{workspace_id or ctx.workspace_id}/invites",
            json={"email": email, "role": role},
        )

    def test_owner_creates_invite(self, ctx):
        resp = self._post(ctx)
        assert resp.status_code == 201
        body = resp.json()
        assert body["email"] == "newcomer@example.com"
        assert body["role"] == "member"
        stored = ctx.storage.get_invite(body["invite_id"])
        assert stored is not None
        assert stored.invited_by_user_id == _OWNER
        expires_at = datetime.fromisoformat(body["expires_at"])
        expected = datetime.now(timezone.utc) + timedelta(days=7)
        assert abs((expires_at - expected).total_seconds()) < 60

    def test_admin_creates_admin_role_invite(self, ctx):
        ctx.login(_ADMIN)
        resp = self._post(ctx, role="admin")
        assert resp.status_code == 201
        assert resp.json()["role"] == "admin"

    def test_email_is_normalized_before_pattern_check(self, ctx):
        # Trimming/lowercasing runs before the pattern constraint, so a
        # pasted address with surrounding whitespace is accepted.
        resp = self._post(ctx, email="  NewComer@Example.COM  ")
        assert resp.status_code == 201
        assert resp.json()["email"] == "newcomer@example.com"

    def test_non_string_email_rejected(self, ctx):
        resp = ctx.client.post(
            f"/api/workspaces/{ctx.workspace_id}/invites",
            json={"email": 123, "role": "member"},
        )
        assert resp.status_code == 422

    def test_invite_ttl_env_override(self, ctx, monkeypatch):
        monkeypatch.setenv("HIVE_INVITE_TTL_DAYS", "1")
        resp = self._post(ctx)
        expires_at = datetime.fromisoformat(resp.json()["expires_at"])
        expected = datetime.now(timezone.utc) + timedelta(days=1)
        assert abs((expires_at - expected).total_seconds()) < 60

    def test_member_cannot_invite(self, ctx):
        ctx.login(_MEMBER)
        assert self._post(ctx).status_code == 403

    def test_non_member_cannot_invite(self, ctx):
        ctx.login(_OUTSIDER)
        assert self._post(ctx).status_code == 403

    def test_missing_workspace_404(self, ctx):
        assert self._post(ctx, workspace_id="ghost").status_code == 404

    def test_personal_workspace_cannot_invite(self, ctx):
        from hive import workspace_service

        personal = workspace_service.create_workspace(
            ctx.storage, name="My Personal", owner_user_id=_OWNER, is_personal=True
        )
        resp = self._post(ctx, workspace_id=personal.workspace_id)
        assert resp.status_code == 409

    def test_owner_role_not_invitable(self, ctx):
        assert self._post(ctx, role="owner").status_code == 422

    def test_invalid_email_rejected(self, ctx):
        assert self._post(ctx, email="not-an-email").status_code == 422

    def test_existing_member_email_conflicts(self, ctx):
        resp = self._post(ctx, email=_EMAILS[_MEMBER])
        assert resp.status_code == 409

    def test_duplicate_pending_invite_conflicts(self, ctx):
        assert self._post(ctx).status_code == 201
        assert self._post(ctx, email="NEWCOMER@example.com").status_code == 409

    def test_workspace_vanishing_mid_invite_404(self, ctx, monkeypatch):
        from hive.workspace_service import WorkspaceNotFoundError

        def _raise(*a, **k):
            raise WorkspaceNotFoundError("gone")

        monkeypatch.setattr("hive.workspace_service.send_invite", _raise)
        assert self._post(ctx).status_code == 404

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.post(
            "/api/workspaces/x/invites", json={"email": "a@b.co", "role": "member"}
        )
        assert resp.status_code in (401, 403)


class TestAcceptInvite:
    def _invite(self, ctx: Ctx, email: str = _EMAILS[_OUTSIDER], role: str = "member") -> str:
        resp = ctx.client.post(
            f"/api/workspaces/{ctx.workspace_id}/invites",
            json={"email": email, "role": role},
        )
        assert resp.status_code == 201
        return resp.json()["invite_id"]

    def test_accept_adds_member_and_consumes_invite(self, ctx):
        invite_id = self._invite(ctx, role="admin")
        ctx.login(_OUTSIDER)
        resp = ctx.client.post(f"/api/invites/{invite_id}/accept")
        assert resp.status_code == 200
        body = resp.json()
        assert body["workspace_id"] == ctx.workspace_id
        assert body["name"] == "Team Alpha"
        assert body["role"] == "admin"
        assert _role_of(ctx, ctx.workspace_id, _OUTSIDER) == "admin"
        assert ctx.storage.get_invite(invite_id) is None
        # Single-use: a second accept finds nothing.
        assert ctx.client.post(f"/api/invites/{invite_id}/accept").status_code == 404

    def test_email_match_is_case_insensitive(self, ctx):
        invite_id = self._invite(ctx)
        ctx.login(_OUTSIDER, email=_EMAILS[_OUTSIDER].upper())
        resp = ctx.client.post(f"/api/invites/{invite_id}/accept")
        assert resp.status_code == 200

    def test_expired_invite_404(self, ctx):
        from hive.models import Invite, WorkspaceRole

        invite = Invite(
            workspace_id=ctx.workspace_id,
            email=_EMAILS[_OUTSIDER],
            role=WorkspaceRole.member,
            invited_by_user_id=_OWNER,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        ctx.storage.put_invite(invite)
        ctx.login(_OUTSIDER)
        resp = ctx.client.post(f"/api/invites/{invite.invite_id}/accept")
        assert resp.status_code == 404
        assert _role_of(ctx, ctx.workspace_id, _OUTSIDER) is None

    def test_missing_invite_404(self, ctx):
        ctx.login(_OUTSIDER)
        assert ctx.client.post("/api/invites/ghost/accept").status_code == 404

    def test_email_mismatch_403(self, ctx):
        invite_id = self._invite(ctx)
        ctx.login(_OUTSIDER, email="someone-else@example.com")
        resp = ctx.client.post(f"/api/invites/{invite_id}/accept")
        assert resp.status_code == 403
        assert ctx.storage.get_invite(invite_id) is not None

    def test_claims_without_email_403(self, ctx):
        invite_id = self._invite(ctx)
        ctx.login_claims({"sub": _OUTSIDER, "role": "user"})
        resp = ctx.client.post(f"/api/invites/{invite_id}/accept")
        assert resp.status_code == 403

    def test_existing_member_conflict_leaves_invite_pending(self, ctx):
        from hive.models import Invite, WorkspaceRole

        # Seed the invite directly — it pre-dates the membership in this
        # scenario (the user joined through another path before accepting).
        invite = Invite(
            workspace_id=ctx.workspace_id,
            email=_EMAILS[_MEMBER],
            role=WorkspaceRole.admin,
            invited_by_user_id=_OWNER,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        ctx.storage.put_invite(invite)
        ctx.login(_MEMBER)
        resp = ctx.client.post(f"/api/invites/{invite.invite_id}/accept")
        assert resp.status_code == 409
        assert ctx.storage.get_invite(invite.invite_id) is not None
        # The existing (lower) role is untouched — accepting would have
        # overwritten it with the invited role.
        assert _role_of(ctx, ctx.workspace_id, _MEMBER) == "member"

    def test_workspace_deleted_after_invite_404(self, ctx):
        from hive.models import Invite, WorkspaceRole

        invite = Invite(
            workspace_id="ghost-workspace",
            email=_EMAILS[_OUTSIDER],
            role=WorkspaceRole.member,
            invited_by_user_id=_OWNER,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        ctx.storage.put_invite(invite)
        ctx.login(_OUTSIDER)
        resp = ctx.client.post(f"/api/invites/{invite.invite_id}/accept")
        assert resp.status_code == 404

    def test_membership_appearing_mid_accept_409(self, ctx, monkeypatch):
        from hive.workspace_service import AlreadyMemberError

        invite_id = self._invite(ctx)

        def _raise(*a, **k):
            raise AlreadyMemberError("already a member")

        # Membership appeared between the endpoint's pre-check and the
        # service's conditional membership write.
        monkeypatch.setattr("hive.workspace_service.accept_invite", _raise)
        ctx.login(_OUTSIDER)
        assert ctx.client.post(f"/api/invites/{invite_id}/accept").status_code == 409

    def test_invite_claimed_concurrently_404(self, ctx, monkeypatch):
        from hive.workspace_service import InviteError

        invite_id = self._invite(ctx)

        def _raise(*a, **k):
            raise InviteError("claimed")

        monkeypatch.setattr("hive.workspace_service.accept_invite", _raise)
        ctx.login(_OUTSIDER)
        assert ctx.client.post(f"/api/invites/{invite_id}/accept").status_code == 404

    def test_workspace_vanishing_mid_accept_404(self, ctx, monkeypatch):
        from hive.workspace_service import WorkspaceNotFoundError

        invite_id = self._invite(ctx)

        def _raise(*a, **k):
            raise WorkspaceNotFoundError("gone")

        monkeypatch.setattr("hive.workspace_service.accept_invite", _raise)
        ctx.login(_OUTSIDER)
        assert ctx.client.post(f"/api/invites/{invite_id}/accept").status_code == 404

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.post("/api/invites/x/accept")
        assert resp.status_code in (401, 403)
