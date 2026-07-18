# Copyright (c) 2026 John Carter. All rights reserved.
"""
Integration tests for workspace compliance (#495) against DynamoDB Local.

Exercises the workspace mutation service end-to-end: every membership
mutation must write a structured audit event to the AUDIT# partition, and
the sole-owner guard must block only while the user is the last owner of a
shared workspace.

Usage:
  docker run -p 8080:8000 amazon/dynamodb-local
  DYNAMODB_ENDPOINT=http://localhost:8080 pytest tests/integration/
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

DYNAMO_ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT")

pytestmark = pytest.mark.skipif(
    not DYNAMO_ENDPOINT,
    reason="DYNAMODB_ENDPOINT not set — skipping integration tests",
)

_TABLE = "hive-integration-workspace-compliance"


@pytest.fixture(scope="module")
def storage():
    """HiveStorage backed by a fresh table in DynamoDB Local."""
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

    from hive.storage import HiveStorage

    yield HiveStorage(table_name=_TABLE, region="us-east-1")

    with contextlib.suppress(Exception):
        ddb.delete_table(TableName=_TABLE)


def _audit_events_for_workspace(storage, workspace_id, event_type):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    events = storage.get_audit_events_for_dates([today], event_type=event_type.value)
    return [e for e in events if e.metadata.get("workspace_id") == workspace_id]


class TestMembershipMutationAuditTrail:
    def test_every_membership_mutation_writes_an_audit_event(self, storage):
        from hive import workspace_service
        from hive.models import EventType, WorkspaceRole

        ws = workspace_service.create_workspace(
            storage, name="Compliance Team", owner_user_id="owner-1"
        )
        invite = workspace_service.send_invite(
            storage,
            workspace_id=ws.workspace_id,
            email="member@example.com",
            role=WorkspaceRole.member,
            invited_by_user_id="owner-1",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        workspace_service.accept_invite(storage, invite_id=invite.invite_id, user_id="member-1")
        workspace_service.change_member_role(
            storage,
            workspace_id=ws.workspace_id,
            user_id="member-1",
            role=WorkspaceRole.admin,
            actor_user_id="owner-1",
        )
        workspace_service.remove_member(
            storage, workspace_id=ws.workspace_id, user_id="member-1", actor_user_id="owner-1"
        )
        workspace_service.delete_workspace(
            storage, workspace_id=ws.workspace_id, actor_user_id="owner-1"
        )

        created = _audit_events_for_workspace(storage, ws.workspace_id, EventType.workspace_created)
        assert len(created) == 1
        assert created[0].client_id == "owner-1"

        sent = _audit_events_for_workspace(
            storage, ws.workspace_id, EventType.workspace_invite_sent
        )
        assert len(sent) == 1
        assert sent[0].metadata["email"] == "member@example.com"

        accepted = _audit_events_for_workspace(
            storage, ws.workspace_id, EventType.workspace_invite_accepted
        )
        assert len(accepted) == 1
        assert accepted[0].client_id == "member-1"
        assert accepted[0].metadata["invite_id"] == invite.invite_id

        role_changed = _audit_events_for_workspace(
            storage, ws.workspace_id, EventType.workspace_member_role_changed
        )
        assert len(role_changed) == 1
        assert role_changed[0].metadata["previous_role"] == "member"
        assert role_changed[0].metadata["new_role"] == "admin"

        removed = _audit_events_for_workspace(
            storage, ws.workspace_id, EventType.workspace_member_removed
        )
        assert len(removed) == 1
        assert removed[0].metadata["user_id"] == "member-1"
        # Role captured at removal time reflects the earlier promotion.
        assert removed[0].metadata["role"] == "admin"

        deleted = _audit_events_for_workspace(storage, ws.workspace_id, EventType.workspace_deleted)
        assert len(deleted) == 1
        assert deleted[0].metadata["name"] == "Compliance Team"


class TestSoleOwnerGuard:
    def test_guard_blocks_then_clears_after_ownership_transfer(self, storage):
        from hive import workspace_service
        from hive.models import WorkspaceRole

        ws = workspace_service.create_workspace(
            storage, name="Guarded Team", owner_user_id="guard-owner"
        )
        blocking = workspace_service.list_sole_owned_shared_workspaces(storage, "guard-owner")
        assert ws.workspace_id in [w.workspace_id for w in blocking]

        # Promote a second member to owner — the guard must clear.
        storage.add_workspace_member(
            workspace_id=ws.workspace_id, user_id="guard-heir", role=WorkspaceRole.member
        )
        workspace_service.change_member_role(
            storage,
            workspace_id=ws.workspace_id,
            user_id="guard-heir",
            role=WorkspaceRole.owner,
            actor_user_id="guard-owner",
        )
        blocking = workspace_service.list_sole_owned_shared_workspaces(storage, "guard-owner")
        assert ws.workspace_id not in [w.workspace_id for w in blocking]

    def test_personal_workspace_never_blocks(self, storage):
        from hive import workspace_service

        workspace_service.create_workspace(
            storage, name="Guard Personal", owner_user_id="guard-solo", is_personal=True
        )
        assert workspace_service.list_sole_owned_shared_workspaces(storage, "guard-solo") == []
