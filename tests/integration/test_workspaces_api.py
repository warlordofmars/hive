# Copyright (c) 2026 John Carter. All rights reserved.
"""
Integration tests for the workspaces API (#492) against DynamoDB Local.

Drives the full invite lifecycle end-to-end through the FastAPI endpoints:
create workspace -> invite -> accept -> role change -> leave -> delete,
asserting the membership state, the single-use invite semantics, invite
expiry, and the compliance audit trail (#495) written by every mutation.

Usage:
  docker run -p 8080:8000 amazon/dynamodb-local
  DYNAMODB_ENDPOINT=http://localhost:8080 pytest tests/integration/
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

DYNAMO_ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT")

pytestmark = pytest.mark.skipif(
    not DYNAMO_ENDPOINT,
    reason="DYNAMODB_ENDPOINT not set — skipping integration tests",
)

_TABLE = "hive-integration-workspaces-api"

_ALICE = "ws-api-alice"
_BOB = "ws-api-bob"
_EMAILS = {_ALICE: "alice@example.com", _BOB: "bob@example.com"}


@pytest.fixture(scope="module")
def env():
    """(client, storage, login) against a fresh DynamoDB Local table."""
    import contextlib

    import boto3

    ddb = boto3.client(
        "dynamodb",
        endpoint_url=DYNAMO_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    with contextlib.suppress(Exception):
        ddb.delete_table(TableName=_TABLE)

    ddb.create_table(
        TableName=_TABLE,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI4PK", "AttributeType": "S"},
            {"AttributeName": "GSI5PK", "AttributeType": "S"},
            {"AttributeName": "GSI5SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
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

    from hive.api import _auth as auth_mod
    from hive.api import workspaces as workspaces_mod
    from hive.api.main import app
    from hive.models import User
    from hive.storage import HiveStorage

    storage = HiveStorage(
        table_name=_TABLE,
        region="us-east-1",
        endpoint_url=DYNAMO_ENDPOINT,
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    for user_id, email in _EMAILS.items():
        storage.put_user(User(user_id=user_id, email=email, display_name=user_id, role="user"))

    claims: dict[str, Any] = {}

    def _override_mgmt_user() -> dict[str, Any]:
        return dict(claims)

    def _override_storage() -> HiveStorage:
        return storage

    def login(user_id: str) -> None:
        claims.clear()
        claims.update({"sub": user_id, "role": "user", "email": _EMAILS[user_id]})

    app.dependency_overrides[auth_mod.require_mgmt_user] = _override_mgmt_user
    app.dependency_overrides[workspaces_mod._storage] = _override_storage

    yield TestClient(app), storage, login

    app.dependency_overrides.clear()
    with contextlib.suppress(Exception):
        ddb.delete_table(TableName=_TABLE)


def _audit_events(storage: Any, workspace_id: str, event_type: str) -> list[Any]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    events = storage.get_audit_events_for_dates([today], event_type=event_type)
    return [e for e in events if e.metadata.get("workspace_id") == workspace_id]


class TestInviteLifecycle:
    def test_full_lifecycle_create_invite_accept_promote_leave_delete(self, env):
        client, storage, login = env

        # Alice creates a workspace and becomes its owner.
        login(_ALICE)
        resp = client.post("/api/workspaces", json={"name": "Lifecycle Team", "description": "e2e"})
        assert resp.status_code == 201
        ws_id = resp.json()["workspace_id"]
        assert resp.json()["role"] == "owner"
        assert len(_audit_events(storage, ws_id, "workspace_created")) == 1

        # Alice invites Bob as admin.
        resp = client.post(
            f"/api/workspaces/{ws_id}/invites",
            json={"email": _EMAILS[_BOB], "role": "admin"},
        )
        assert resp.status_code == 201
        invite_id = resp.json()["invite_id"]
        assert len(_audit_events(storage, ws_id, "workspace_invite_sent")) == 1

        # A second identical invite is rejected while one is pending.
        resp = client.post(
            f"/api/workspaces/{ws_id}/invites",
            json={"email": _EMAILS[_BOB], "role": "member"},
        )
        assert resp.status_code == 409

        # Bob cannot see the workspace before accepting.
        login(_BOB)
        assert client.get("/api/workspaces").json() == []

        # Bob accepts the invite and joins with the invited role.
        resp = client.post(f"/api/invites/{invite_id}/accept")
        assert resp.status_code == 200
        assert resp.json() == {
            "workspace_id": ws_id,
            "name": "Lifecycle Team",
            "role": "admin",
        }
        assert len(_audit_events(storage, ws_id, "workspace_invite_accepted")) == 1

        # Single-use: the invite is consumed.
        assert client.post(f"/api/invites/{invite_id}/accept").status_code == 404

        # Both members now appear in the member list.
        resp = client.get(f"/api/workspaces/{ws_id}/members")
        assert resp.status_code == 200
        roles = {m["user_id"]: m["role"] for m in resp.json()}
        assert roles == {_ALICE: "owner", _BOB: "admin"}
        emails = {m["user_id"]: m["email"] for m in resp.json()}
        assert emails[_BOB] == _EMAILS[_BOB]

        # Bob (admin) cannot delete the workspace; Alice (owner) is blocked
        # by the remaining-members guard.
        assert client.delete(f"/api/workspaces/{ws_id}").status_code == 403
        login(_ALICE)
        resp = client.delete(f"/api/workspaces/{ws_id}")
        assert resp.status_code == 409
        assert resp.json()["detail"]["members"] == [{"user_id": _BOB, "role": "admin"}]

        # Alice promotes Bob to owner, then leaves.
        resp = client.put(f"/api/workspaces/{ws_id}/members/{_BOB}", json={"role": "owner"})
        assert resp.status_code == 200
        events = _audit_events(storage, ws_id, "workspace_member_role_changed")
        assert len(events) == 1
        assert events[0].metadata["previous_role"] == "admin"
        assert events[0].metadata["new_role"] == "owner"

        assert client.delete(f"/api/workspaces/{ws_id}/members/{_ALICE}").status_code == 204
        removed = _audit_events(storage, ws_id, "workspace_member_removed")
        assert len(removed) == 1
        assert removed[0].client_id == _ALICE  # self-removal: actor == target
        assert client.get("/api/workspaces").json() == []

        # Bob — now the sole owner and sole member — deletes the workspace.
        login(_BOB)
        assert client.delete(f"/api/workspaces/{ws_id}").status_code == 204
        assert len(_audit_events(storage, ws_id, "workspace_deleted")) == 1
        assert client.get("/api/workspaces").json() == []
        assert storage.get_workspace(ws_id) is None

    def test_expired_invite_is_rejected_and_membership_untouched(self, env):
        client, storage, login = env
        from hive.models import Invite, WorkspaceRole

        login(_ALICE)
        resp = client.post("/api/workspaces", json={"name": "Expiry Team"})
        assert resp.status_code == 201
        ws_id = resp.json()["workspace_id"]

        invite = Invite(
            workspace_id=ws_id,
            email=_EMAILS[_BOB],
            role=WorkspaceRole.member,
            invited_by_user_id=_ALICE,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        storage.put_invite(invite)

        login(_BOB)
        resp = client.post(f"/api/invites/{invite.invite_id}/accept")
        assert resp.status_code == 404
        assert storage.get_workspace_member(ws_id, _BOB) is None
        assert _audit_events(storage, ws_id, "workspace_invite_accepted") == []

    def test_sole_owner_demotion_and_leave_are_blocked(self, env):
        client, storage, login = env

        login(_ALICE)
        resp = client.post("/api/workspaces", json={"name": "Guard Team"})
        assert resp.status_code == 201
        ws_id = resp.json()["workspace_id"]

        resp = client.put(f"/api/workspaces/{ws_id}/members/{_ALICE}", json={"role": "member"})
        assert resp.status_code == 409
        resp = client.delete(f"/api/workspaces/{ws_id}/members/{_ALICE}")
        assert resp.status_code == 409
        member = storage.get_workspace_member(ws_id, _ALICE)
        assert member is not None
        assert member.role.value == "owner"
