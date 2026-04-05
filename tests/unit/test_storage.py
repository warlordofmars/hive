# Copyright (c) 2026 John Carter. All rights reserved.
"""
Unit tests for the storage layer using moto to mock DynamoDB.
"""

from __future__ import annotations

import os

import boto3
import pytest

# Must set env var before importing storage so TABLE_NAME picks it up
os.environ.setdefault("HIVE_TABLE_NAME", "hive-test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

from moto import mock_aws

from hive.models import ActivityEvent, EventType, Memory, OAuthClient, TokenType, User
from hive.storage import HiveStorage


@pytest.fixture()
def storage():
    """Provide a HiveStorage backed by a fresh moto-mocked DynamoDB table."""
    with mock_aws():
        _create_table()
        yield HiveStorage(table_name="hive-test", region="us-east-1")


def _create_table():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="hive-test",
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
                "KeySchema": [
                    {"AttributeName": "GSI4PK", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )


# ---------------------------------------------------------------------------
# Memory tests
# ---------------------------------------------------------------------------


class TestMemoryStorage:
    def test_put_and_get_by_key(self, storage):
        m = Memory(key="hello", value="world", owner_client_id="c1")
        storage.put_memory(m)
        result = storage.get_memory_by_key("hello")
        assert result is not None
        assert result.value == "world"

    def test_get_nonexistent_key(self, storage):
        assert storage.get_memory_by_key("no-such-key") is None

    def test_get_by_id(self, storage):
        m = Memory(key="k", value="v", owner_client_id="c1")
        storage.put_memory(m)
        result = storage.get_memory_by_id(m.memory_id)
        assert result is not None
        assert result.memory_id == m.memory_id

    def test_delete(self, storage):
        m = Memory(key="to-delete", value="bye", owner_client_id="c1")
        storage.put_memory(m)
        assert storage.delete_memory(m.memory_id)
        assert storage.get_memory_by_key("to-delete") is None

    def test_delete_nonexistent(self, storage):
        assert not storage.delete_memory("fake-id")

    def test_list_by_tag(self, storage):
        m1 = Memory(key="a", value="1", tags=["x", "y"], owner_client_id="c1")
        m2 = Memory(key="b", value="2", tags=["y", "z"], owner_client_id="c1")
        m3 = Memory(key="c", value="3", tags=["z"], owner_client_id="c1")
        for m in [m1, m2, m3]:
            storage.put_memory(m)

        tagged_y, _ = storage.list_memories_by_tag("y")
        keys = {m.key for m in tagged_y}
        assert keys == {"a", "b"}

        tagged_z, _ = storage.list_memories_by_tag("z")
        keys_z = {m.key for m in tagged_z}
        assert keys_z == {"b", "c"}

    def test_update_replaces_tags(self, storage):
        m = Memory(key="k", value="v", tags=["old"], owner_client_id="c1")
        storage.put_memory(m)

        m.tags = ["new"]
        storage.put_memory(m)

        old_tagged, _ = storage.list_memories_by_tag("old")
        assert old_tagged == []
        new_tagged, _ = storage.list_memories_by_tag("new")
        assert len(new_tagged) == 1

    def test_upsert_by_key(self, storage):
        m = Memory(key="upsert-key", value="v1", tags=["a"], owner_client_id="c1")
        storage.put_memory(m)

        m2 = storage.get_memory_by_key("upsert-key")
        assert m2 is not None
        m2.value = "v2"
        m2.tags = ["b"]
        storage.put_memory(m2)

        result = storage.get_memory_by_key("upsert-key")
        assert result is not None
        assert result.value == "v2"
        assert result.tags == ["b"]
        assert result.memory_id == m.memory_id  # same item, not a new one

    def test_put_memory_too_large_raises_value_error(self, storage):
        from unittest.mock import patch

        from botocore.exceptions import ClientError

        oversized = Memory(key="big", value="x" * 1000, tags=[], owner_client_id="c1")
        error_response = {
            "Error": {
                "Code": "ValidationException",
                "Message": "Item size has exceeded the maximum allowed size",
            }
        }
        with patch.object(storage.table, "batch_writer") as mock_bw:
            mock_bw.return_value.__enter__.return_value.put_item.side_effect = ClientError(
                error_response, "PutItem"
            )
            with pytest.raises(ValueError, match="too large"):
                storage.put_memory(oversized)

    def test_put_memory_other_client_error_reraises(self, storage):
        from unittest.mock import patch

        from botocore.exceptions import ClientError

        m = Memory(key="err", value="v", tags=[], owner_client_id="c1")
        error_response = {
            "Error": {"Code": "ProvisionedThroughputExceededException", "Message": "slow"}
        }
        with patch.object(storage.table, "batch_writer") as mock_bw:
            mock_bw.return_value.__enter__.return_value.put_item.side_effect = ClientError(
                error_response, "PutItem"
            )
            with pytest.raises(ClientError):
                storage.put_memory(m)


# ---------------------------------------------------------------------------
# Client tests
# ---------------------------------------------------------------------------


class TestClientStorage:
    def test_put_and_get(self, storage):
        c = OAuthClient(client_name="Test")
        storage.put_client(c)
        result = storage.get_client(c.client_id)
        assert result is not None
        assert result.client_name == "Test"

    def test_delete(self, storage):
        c = OAuthClient(client_name="Delete Me")
        storage.put_client(c)
        assert storage.delete_client(c.client_id)
        assert storage.get_client(c.client_id) is None

    def test_list(self, storage):
        for i in range(3):
            storage.put_client(OAuthClient(client_name=f"App {i}"))
        clients, _ = storage.list_clients()
        assert len(clients) == 3

    def test_list_clients_with_cursor(self, storage):
        """Covers storage.py:220 — list_clients pagination cursor."""
        for i in range(4):
            storage.put_client(OAuthClient(client_name=f"PagApp {i}"))
        page1, cursor1 = storage.list_clients(limit=2)
        assert len(page1) == 2
        assert cursor1 is not None
        page2, cursor2 = storage.list_clients(limit=2, cursor=cursor1)
        assert len(page2) == 2


# ---------------------------------------------------------------------------
# Token tests
# ---------------------------------------------------------------------------


class TestTokenStorage:
    def test_create_and_get(self, storage):
        access, refresh = storage.create_token_pair("c1", "memories:read")
        fetched = storage.get_token(access.jti)
        assert fetched is not None
        assert fetched.client_id == "c1"
        assert fetched.token_type == TokenType.access

    def test_revoke(self, storage):
        access, _ = storage.create_token_pair("c1", "s")
        storage.revoke_token(access.jti)
        fetched = storage.get_token(access.jti)
        assert fetched is not None
        assert fetched.revoked


# ---------------------------------------------------------------------------
# Activity log tests
# ---------------------------------------------------------------------------


class TestActivityLog:
    def test_log_and_query(self, storage):
        event = ActivityEvent(
            event_type=EventType.memory_created,
            client_id="c1",
            metadata={"key": "x"},
        )
        storage.log_event(event)

        date_str = event.timestamp.strftime("%Y-%m-%d")
        events = storage.get_events_for_date(date_str)
        assert len(events) == 1
        assert events[0].event_id == event.event_id

    def test_hour_sharded_pk(self, storage):
        """Events must be written to LOG#{date}#{hour} partitions."""
        event = ActivityEvent(
            event_type=EventType.memory_recalled,
            client_id="c1",
            metadata={},
        )
        storage.log_event(event)

        item = storage.table.get_item(
            Key={
                "PK": f"LOG#{event.timestamp.strftime('%Y-%m-%d#%H')}",
                "SK": f"{event.timestamp.isoformat()}#{event.event_id}",
            }
        ).get("Item")
        assert item is not None
        assert item["event_id"] == event.event_id

    def test_get_events_for_dates(self, storage):
        """get_events_for_dates aggregates across multiple days."""
        from datetime import timedelta

        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        for days_ago in range(3):
            ts = now - timedelta(days=days_ago)
            storage.log_event(
                ActivityEvent(
                    event_type=EventType.memory_created,
                    client_id="c1",
                    metadata={},
                    timestamp=ts,
                )
            )
        dates = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]
        events = storage.get_events_for_dates(dates)
        assert len(events) == 3
        # Results are sorted newest-first
        assert events[0].timestamp >= events[-1].timestamp


# ---------------------------------------------------------------------------
# list_all_memories and count helpers
# ---------------------------------------------------------------------------


class TestListAllAndCounts:
    def test_list_all_memories(self, storage):
        storage.put_memory(Memory(key="x", value="1", owner_client_id="c1"))
        storage.put_memory(Memory(key="y", value="2", owner_client_id="c2"))
        all_mems, _ = storage.list_all_memories()
        keys = {m.key for m in all_mems}
        assert {"x", "y"}.issubset(keys)

    def test_list_all_memories_filtered_by_client(self, storage):
        storage.put_memory(Memory(key="a", value="1", owner_client_id="client-a"))
        storage.put_memory(Memory(key="b", value="2", owner_client_id="client-b"))
        mems, _ = storage.list_all_memories(client_id="client-a")
        assert all(m.owner_client_id == "client-a" for m in mems)
        assert any(m.key == "a" for m in mems)

    def test_count_memories(self, storage):
        assert storage.count_memories() == 0
        storage.put_memory(Memory(key="k1", value="v", owner_client_id="c1"))
        storage.put_memory(Memory(key="k2", value="v", owner_client_id="c1"))
        assert storage.count_memories() == 2

    def test_count_clients(self, storage):
        assert storage.count_clients() == 0
        from hive.models import OAuthClient

        storage.put_client(OAuthClient(client_name="A"))
        storage.put_client(OAuthClient(client_name="B"))
        assert storage.count_clients() == 2


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestPagination:
    def test_list_all_memories_cursor(self, storage):
        for i in range(5):
            storage.put_memory(Memory(key=f"pg-{i}", value="v", owner_client_id="c1"))

        page1, cursor1 = storage.list_all_memories(limit=3)
        assert len(page1) == 3
        assert cursor1 is not None

        page2, cursor2 = storage.list_all_memories(limit=3, cursor=cursor1)
        assert len(page2) == 2
        assert cursor2 is None

        all_keys = {m.key for m in page1 + page2}
        assert all_keys == {f"pg-{i}" for i in range(5)}

    def test_list_memories_by_tag_cursor(self, storage):
        for i in range(4):
            storage.put_memory(
                Memory(key=f"tpg-{i}", value="v", tags=["page"], owner_client_id="c1")
            )

        page1, cursor1 = storage.list_memories_by_tag("page", limit=2)
        assert len(page1) == 2
        assert cursor1 is not None

        page2, cursor2 = storage.list_memories_by_tag("page", limit=2, cursor=cursor1)
        assert len(page2) == 2
        assert cursor2 is None

    def test_invalid_cursor_raises(self, storage):
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            storage.list_all_memories(cursor="not-valid-base64!!!")

    def test_list_all_memories_follows_scan_pages(self, storage):
        """Covers the scan-loop continuation path when DynamoDB returns LastEvaluatedKey."""
        from unittest.mock import patch

        mems = [Memory(key=f"paged-{i}", value="v", owner_client_id="c1") for i in range(3)]
        for m in mems:
            storage.put_memory(m)

        fake_lek = {"PK": f"MEMORY#{mems[0].memory_id}", "SK": "META"}
        page1_items = [mems[0].to_dynamo_meta()]
        page2_items = [mems[1].to_dynamo_meta(), mems[2].to_dynamo_meta()]
        responses = iter(
            [
                {"Items": page1_items, "LastEvaluatedKey": fake_lek},
                {"Items": page2_items},
            ]
        )

        with patch.object(storage.table, "scan", side_effect=lambda **_kw: next(responses)):
            result, cursor = storage.list_all_memories(limit=5)

        assert len(result) == 3
        assert cursor is None

    def test_list_clients_follows_scan_pages(self, storage):
        """Covers the scan-loop continuation path in list_clients."""
        from unittest.mock import patch

        from hive.models import OAuthClient

        clients = [OAuthClient(client_name=f"C{i}") for i in range(3)]
        for c in clients:
            storage.put_client(c)

        fake_lek = {"PK": f"CLIENT#{clients[0].client_id}", "SK": "META"}
        page1_items = [clients[0].to_dynamo()]
        page2_items = [clients[1].to_dynamo(), clients[2].to_dynamo()]
        responses = iter(
            [
                {"Items": page1_items, "LastEvaluatedKey": fake_lek},
                {"Items": page2_items},
            ]
        )

        with patch.object(storage.table, "scan", side_effect=lambda **_kw: next(responses)):
            result, cursor = storage.list_clients(limit=5)

        assert len(result) == 3
        assert cursor is None

    def test_activity_limit_respected(self, storage):
        from datetime import date

        from hive.models import ActivityEvent, EventType

        today = date.today().isoformat()
        for _i in range(10):
            storage.log_event(
                ActivityEvent(event_type=EventType.memory_recalled, client_id="c1", metadata={})
            )
        events = storage.get_events_for_dates([today], limit=5)
        assert len(events) <= 5


# ---------------------------------------------------------------------------
# Pending auth tests
# ---------------------------------------------------------------------------


class TestPendingAuthStorage:
    def test_create_and_get(self, storage):
        pending = storage.create_pending_auth(
            client_id="c1",
            redirect_uri="https://app.example.com/cb",
            scope="memories:read",
            code_challenge="abc123",
            code_challenge_method="S256",
            original_state="xyz",
        )
        assert pending.state
        fetched = storage.get_pending_auth(pending.state)
        assert fetched is not None
        assert fetched.client_id == "c1"
        assert fetched.scope == "memories:read"
        assert fetched.original_state == "xyz"

    def test_get_nonexistent_returns_none(self, storage):
        assert storage.get_pending_auth("no-such-state") is None

    def test_delete_pending_auth(self, storage):
        pending = storage.create_pending_auth(
            client_id="c1",
            redirect_uri="https://app.example.com/cb",
            scope="memories:read",
            code_challenge="abc",
            code_challenge_method="S256",
            original_state="",
        )
        storage.delete_pending_auth(pending.state)
        assert storage.get_pending_auth(pending.state) is None


# ---------------------------------------------------------------------------
# User storage
# ---------------------------------------------------------------------------


class TestUserStorage:
    def _user(self, email: str = "alice@example.com", role: str = "user") -> User:
        return User(email=email, display_name="Alice", role=role)

    def test_put_and_get_by_id(self, storage):
        u = self._user()
        storage.put_user(u)
        fetched = storage.get_user_by_id(u.user_id)
        assert fetched is not None
        assert fetched.email == u.email
        assert fetched.role == u.role

    def test_get_nonexistent_by_id_returns_none(self, storage):
        assert storage.get_user_by_id("no-such-id") is None

    def test_get_by_email(self, storage):
        u = self._user(email="bob@example.com")
        storage.put_user(u)
        fetched = storage.get_user_by_email("bob@example.com")
        assert fetched is not None
        assert fetched.user_id == u.user_id

    def test_get_nonexistent_by_email_returns_none(self, storage):
        assert storage.get_user_by_email("nobody@example.com") is None

    def test_delete(self, storage):
        u = self._user()
        storage.put_user(u)
        assert storage.delete_user(u.user_id) is True
        assert storage.get_user_by_id(u.user_id) is None

    def test_delete_nonexistent_returns_false(self, storage):
        assert storage.delete_user("no-such-id") is False

    def test_list_users(self, storage):
        storage.put_user(self._user("a@example.com"))
        storage.put_user(self._user("b@example.com"))
        users, cursor = storage.list_users()
        emails = {u.email for u in users}
        assert {"a@example.com", "b@example.com"}.issubset(emails)
        assert cursor is None


# ---------------------------------------------------------------------------
# MgmtPendingState storage
# ---------------------------------------------------------------------------


class TestMgmtPendingStateStorage:
    def test_create_and_get(self, storage):
        pending = storage.create_mgmt_pending_state()
        assert pending.state
        fetched = storage.get_mgmt_pending_state(pending.state)
        assert fetched is not None
        assert fetched.state == pending.state

    def test_get_nonexistent_returns_none(self, storage):
        assert storage.get_mgmt_pending_state("no-such-state") is None

    def test_delete(self, storage):
        pending = storage.create_mgmt_pending_state()
        storage.delete_mgmt_pending_state(pending.state)
        assert storage.get_mgmt_pending_state(pending.state) is None


# ---------------------------------------------------------------------------
# owner_user_id filtering
# ---------------------------------------------------------------------------


class TestOwnerUserIdFiltering:
    def test_list_all_memories_filtered_by_user(self, storage):
        storage.put_memory(Memory(key="a", value="1", owner_client_id="c1", owner_user_id="user-1"))
        storage.put_memory(Memory(key="b", value="2", owner_client_id="c2", owner_user_id="user-2"))
        mems, _ = storage.list_all_memories(owner_user_id="user-1")
        assert len(mems) == 1
        assert mems[0].key == "a"

    def test_list_clients_filtered_by_user(self, storage):
        storage.put_client(OAuthClient(client_name="A", owner_user_id="user-1"))
        storage.put_client(OAuthClient(client_name="B", owner_user_id="user-2"))
        clients, _ = storage.list_clients(owner_user_id="user-1")
        assert len(clients) == 1
        assert clients[0].client_name == "A"

    def test_count_memories_filtered_by_user(self, storage):
        storage.put_memory(Memory(key="x", value="v", owner_client_id="c1", owner_user_id="user-1"))
        storage.put_memory(Memory(key="y", value="v", owner_client_id="c1", owner_user_id="user-2"))
        assert storage.count_memories(owner_user_id="user-1") == 1
        assert storage.count_memories() == 2

    def test_count_clients_filtered_by_user(self, storage):
        storage.put_client(OAuthClient(client_name="C1", owner_user_id="user-1"))
        storage.put_client(OAuthClient(client_name="C2", owner_user_id="user-2"))
        assert storage.count_clients(owner_user_id="user-1") == 1
        assert storage.count_clients() == 2
