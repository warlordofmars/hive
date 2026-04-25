# Copyright (c) 2026 John Carter. All rights reserved.
"""Unit tests for scripts/migrate_workspaces.py — the #490 cutover."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import boto3
import pytest

os.environ.setdefault("HIVE_TABLE_NAME", "hive-test-migrate")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

from moto import mock_aws

from hive.models import Memory, OAuthClient, Token, User, Workspace, WorkspaceRole
from hive.storage import HiveStorage
from scripts.migrate_workspaces import (
    MigrationStats,
    _personal_workspace_name,
    main,
    run,
)

TABLE_NAME = "hive-test-migrate"


@pytest.fixture()
def storage():
    with mock_aws():
        _create_table()
        yield HiveStorage(table_name=TABLE_NAME, region="us-east-1")


def _create_table():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
            {"AttributeName": "GSI4PK", "AttributeType": "S"},
            {"AttributeName": "GSI5PK", "AttributeType": "S"},
            {"AttributeName": "GSI5SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "KeyIndex",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
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
                "KeySchema": [{"AttributeName": "GSI4PK", "KeyType": "HASH"}],
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


def _seed_user(storage, email: str = "alice@example.com") -> User:
    user = User(email=email, display_name=email.split("@")[0].title())
    storage.put_user(user)
    return user


def _seed_memory(storage, *, owner_user_id: str | None, value: str = "v", key: str = "m") -> Memory:
    # owner_client_id is irrelevant for migration; workspace_id comes from user.
    mem = Memory(
        key=key,
        value=value,
        owner_client_id="client-1",
        owner_user_id=owner_user_id,
    )
    storage.put_memory(mem)
    return mem


def _seed_client(storage, *, owner_user_id: str | None, name: str = "Test") -> OAuthClient:
    client = OAuthClient(client_name=name, owner_user_id=owner_user_id)
    storage.put_client(client)
    return client


def _seed_token(storage, client_id: str = "c1") -> Token:
    now = datetime.now(timezone.utc)
    token = Token(
        client_id=client_id,
        scope="memories:read",
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    storage.put_token(token)
    return token


class TestHelpers:
    def test_personal_workspace_name(self):
        assert _personal_workspace_name("alice@example.com") == "alice@example.com's Personal"

    def test_stats_report_includes_every_counter(self):
        s = MigrationStats(
            users_seen=1,
            workspaces_created=1,
            memories_seen=2,
            memories_migrated=2,
            clients_seen=1,
            clients_migrated=1,
            tokens_revoked=3,
        )
        text = s.report()
        assert "users_seen=1" in text
        assert "workspaces_created=1" in text
        assert "memories_migrated=2" in text
        assert "clients_migrated=1" in text
        assert "tokens_revoked=3" in text


class TestUserMigration:
    def test_creates_personal_workspace_for_each_user(self, storage):
        alice = _seed_user(storage, "alice@example.com")
        bob = _seed_user(storage, "bob@example.com")
        stats = run(storage=storage)
        assert stats.users_seen == 2
        assert stats.workspaces_created == 2
        assert stats.workspaces_skipped == 0

        alice_ws = storage.list_workspaces_for_user(alice.user_id)
        bob_ws = storage.list_workspaces_for_user(bob.user_id)
        assert len(alice_ws) == 1 and alice_ws[0].is_personal
        assert len(bob_ws) == 1 and bob_ws[0].is_personal
        assert alice_ws[0].name == "alice@example.com's Personal"

    def test_makes_user_the_owner_of_their_personal_workspace(self, storage):
        alice = _seed_user(storage)
        run(storage=storage)
        ws = storage.list_workspaces_for_user(alice.user_id)[0]
        member = storage.get_workspace_member(ws.workspace_id, alice.user_id)
        assert member is not None
        assert member.role is WorkspaceRole.owner

    def test_rerun_is_idempotent_for_users(self, storage):
        _seed_user(storage)
        run(storage=storage)
        stats2 = run(storage=storage)
        assert stats2.workspaces_skipped == 1
        assert stats2.workspaces_created == 0

    def test_repairs_partial_run_where_meta_exists_but_member_missing(self, storage):
        """A prior partial run may have written the Workspace META but not the MEMBER row.

        The fallback scan in _find_personal_workspace must detect this and repair
        it rather than creating a duplicate workspace.
        """
        alice = _seed_user(storage)
        # Simulate a partial prior run: write the workspace META directly
        # but intentionally skip add_workspace_member so the MEMBER row is absent.
        partial_ws = Workspace(
            name="alice@example.com's Personal",
            owner_user_id=alice.user_id,
            is_personal=True,
        )
        storage.put_workspace(partial_ws)
        # No add_workspace_member call — MEMBER row is missing.
        assert storage.list_workspaces_for_user(alice.user_id) == []

        # Re-running the migration should detect the orphaned META, repair the
        # MEMBER row, and NOT create a second workspace.
        stats = run(storage=storage)
        assert stats.workspaces_created == 0
        assert stats.workspaces_skipped == 1
        ws_list = storage.list_workspaces_for_user(alice.user_id)
        assert len(ws_list) == 1
        assert ws_list[0].workspace_id == partial_ws.workspace_id


class TestMemoryMigration:
    def test_stamps_workspace_id_on_each_memory(self, storage):
        alice = _seed_user(storage)
        mem = _seed_memory(storage, owner_user_id=alice.user_id)
        stats = run(storage=storage)
        assert stats.memories_migrated == 1
        fetched = storage.get_memory_by_id(mem.memory_id)
        assert fetched.workspace_id is not None
        ws = storage.list_workspaces_for_user(alice.user_id)[0]
        assert fetched.workspace_id == ws.workspace_id

    def test_skips_memories_without_owner_user_id(self, storage):
        _seed_user(storage)
        mem = _seed_memory(storage, owner_user_id=None, key="legacy")
        stats = run(storage=storage)
        assert stats.memories_skipped == 1
        assert storage.get_memory_by_id(mem.memory_id).workspace_id is None

    def test_skips_already_migrated_memories(self, storage):
        alice = _seed_user(storage)
        mem = _seed_memory(storage, owner_user_id=alice.user_id)
        run(storage=storage)
        stats2 = run(storage=storage)
        # Second run sees the same memory but skips it because workspace_id is set.
        assert stats2.memories_migrated == 0
        assert stats2.memories_skipped == 1
        assert storage.get_memory_by_id(mem.memory_id).workspace_id is not None

    def test_skips_memories_referencing_unknown_user(self, storage):
        # Seed a memory pointing at a user_id that has no User record.
        mem = _seed_memory(storage, owner_user_id="ghost-user", key="orphan")
        stats = run(storage=storage)
        assert stats.memories_skipped == 1
        assert storage.get_memory_by_id(mem.memory_id).workspace_id is None

    def test_skips_memory_that_disappears_mid_migration(self, storage):
        """ConditionalCheckFailedException during update_item is treated as a skip."""
        from unittest.mock import patch

        from botocore.exceptions import ClientError

        alice = _seed_user(storage)
        _seed_memory(storage, owner_user_id=alice.user_id, key="vanishing")
        error = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": ""}},
            "UpdateItem",
        )
        with patch.object(storage.table, "update_item", side_effect=error):
            stats = run(storage=storage)
        assert stats.memories_skipped == 1
        assert stats.memories_migrated == 0


class TestClientMigration:
    def test_stamps_workspace_id_on_each_client(self, storage):
        alice = _seed_user(storage)
        client = _seed_client(storage, owner_user_id=alice.user_id)
        stats = run(storage=storage)
        assert stats.clients_migrated == 1
        fetched = storage.get_client(client.client_id)
        ws = storage.list_workspaces_for_user(alice.user_id)[0]
        assert fetched.workspace_id == ws.workspace_id

    def test_skips_clients_without_owner_user_id(self, storage):
        _seed_user(storage)
        client = _seed_client(storage, owner_user_id=None)
        stats = run(storage=storage)
        assert stats.clients_skipped == 1
        assert storage.get_client(client.client_id).workspace_id is None

    def test_skips_already_migrated_clients(self, storage):
        alice = _seed_user(storage)
        _seed_client(storage, owner_user_id=alice.user_id)
        run(storage=storage)
        stats2 = run(storage=storage)
        assert stats2.clients_migrated == 0
        assert stats2.clients_skipped == 1

    def test_skips_clients_referencing_unknown_user(self, storage):
        client = _seed_client(storage, owner_user_id="ghost-user")
        stats = run(storage=storage)
        assert stats.clients_skipped == 1
        assert storage.get_client(client.client_id).workspace_id is None

    def test_skips_client_that_disappears_mid_migration(self, storage):
        """ConditionalCheckFailedException during update_item is treated as a skip."""
        from unittest.mock import patch

        from botocore.exceptions import ClientError

        alice = _seed_user(storage)
        _seed_client(storage, owner_user_id=alice.user_id)
        error = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": ""}},
            "UpdateItem",
        )
        with patch.object(storage.table, "update_item", side_effect=error):
            stats = run(storage=storage)
        assert stats.clients_skipped == 1
        assert stats.clients_migrated == 0


class TestTokenRevocation:
    def test_revokes_every_token(self, storage):
        _seed_user(storage)
        token = _seed_token(storage)
        stats = run(storage=storage)
        assert stats.tokens_revoked >= 1
        assert storage.get_token(token.jti).revoked is True


class TestDryRun:
    def test_dry_run_reports_without_writing_workspaces(self, storage):
        alice = _seed_user(storage)
        _seed_memory(storage, owner_user_id=alice.user_id)
        _seed_client(storage, owner_user_id=alice.user_id)
        stats = run(storage=storage, dry_run=True)
        assert stats.workspaces_created == 1
        assert stats.memories_migrated == 1
        assert stats.clients_migrated == 1
        # Nothing should actually have landed.
        assert storage.list_workspaces_for_user(alice.user_id) == []

    def test_dry_run_skips_token_revocation(self, storage):
        _seed_user(storage)
        token = _seed_token(storage)
        stats = run(storage=storage, dry_run=True)
        assert stats.tokens_revoked == 0
        assert storage.get_token(token.jti).revoked is False


class TestCli:
    def test_main_runs_without_args(self, storage, capsys, monkeypatch):
        _seed_user(storage)
        # main() constructs its own HiveStorage; point it at the moto-backed table.
        monkeypatch.setenv("HIVE_TABLE_NAME", TABLE_NAME)
        assert main([]) == 0
        out = capsys.readouterr().out
        assert "users_seen=1" in out

    def test_main_dry_run(self, storage, capsys, monkeypatch):
        _seed_user(storage)
        monkeypatch.setenv("HIVE_TABLE_NAME", TABLE_NAME)
        assert main(["--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "workspaces_created=1" in out
