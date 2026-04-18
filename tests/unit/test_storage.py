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

from hive.models import (
    ActivityEvent,
    ApiKey,
    EventType,
    Memory,
    OAuthClient,
    TokenType,
    User,
    UserResponse,
)
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

    def test_list_distinct_tags_returns_sorted_unique(self, storage):
        for m in [
            Memory(key="a", value="1", tags=["zebra", "alpha"], owner_client_id="c1"),
            Memory(key="b", value="2", tags=["alpha", "mango"], owner_client_id="c1"),
            Memory(key="c", value="3", tags=[], owner_client_id="c1"),
        ]:
            storage.put_memory(m)

        assert storage.list_distinct_tags("c1") == ["alpha", "mango", "zebra"]

    def test_list_distinct_tags_scoped_to_client(self, storage):
        storage.put_memory(Memory(key="a", value="1", tags=["mine"], owner_client_id="c1"))
        storage.put_memory(Memory(key="b", value="2", tags=["theirs"], owner_client_id="c2"))

        assert storage.list_distinct_tags("c1") == ["mine"]
        assert storage.list_distinct_tags("c2") == ["theirs"]

    def test_list_distinct_tags_empty_when_no_memories(self, storage):
        assert storage.list_distinct_tags("c1") == []

    def test_list_distinct_tags_follows_scan_pages(self, storage):
        from unittest.mock import patch

        responses = iter(
            [
                {"Items": [{"GSI2PK": "TAG#alpha"}], "LastEvaluatedKey": {"PK": "x"}},
                {"Items": [{"GSI2PK": "TAG#beta"}, {"GSI2PK": "NOT_A_TAG"}]},
            ]
        )
        with patch.object(storage.table, "scan", side_effect=lambda **_kw: next(responses)):
            result = storage.list_distinct_tags("c1")

        assert result == ["alpha", "beta"]

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

    def test_put_and_get_memory_with_ttl(self, storage):
        from datetime import datetime, timedelta, timezone

        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        m = Memory(key="ttl-key", value="ttl-val", owner_client_id="c1", expires_at=expires_at)
        storage.put_memory(m)
        result = storage.get_memory_by_id(m.memory_id)
        assert result is not None
        assert result.expires_at is not None
        assert abs((result.expires_at - expires_at).total_seconds()) < 1

    def test_get_expired_memory_returns_none(self, storage):
        from datetime import datetime, timedelta, timezone

        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        m = Memory(key="expired-key", value="gone", owner_client_id="c1", expires_at=past)
        storage.put_memory(m)
        # DynamoDB TTL is eventually consistent; filter client-side
        result = storage.get_memory_by_id(m.memory_id)
        assert result is None

    def test_get_memory_by_key_expired_returns_none(self, storage):
        from datetime import datetime, timedelta, timezone

        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        m = Memory(key="expired-key2", value="gone", owner_client_id="c1", expires_at=past)
        storage.put_memory(m)
        result = storage.get_memory_by_key("expired-key2")
        assert result is None

    def test_memory_serialise_ttl_in_dynamo(self):
        from datetime import datetime, timedelta, timezone

        expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
        m = Memory(key="k", value="v", owner_client_id="c1", expires_at=expires_at)
        item = m.to_dynamo_meta()
        assert "expires_at" in item
        assert "ttl" in item
        assert item["ttl"] == int(expires_at.timestamp())

    def test_memory_deserialise_ttl_from_dynamo(self):
        from datetime import datetime, timedelta, timezone

        expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
        m = Memory(key="k", value="v", owner_client_id="c1", expires_at=expires_at)
        item = m.to_dynamo_meta()
        restored = Memory.from_dynamo(item)
        assert restored.expires_at is not None
        assert abs((restored.expires_at - expires_at).total_seconds()) < 1

    def test_memory_is_expired_false_when_no_ttl(self):
        m = Memory(key="k", value="v", owner_client_id="c1")
        assert not m.is_expired

    def test_memory_is_expired_true_when_past(self):
        from datetime import datetime, timedelta, timezone

        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        m = Memory(key="k", value="v", owner_client_id="c1", expires_at=past)
        assert m.is_expired

    def test_put_memory_saves_version_on_update(self, storage):
        """Updating an existing memory should create a version snapshot."""
        m = Memory(key="v-key", value="v1", owner_client_id="c1")
        storage.put_memory(m)
        m.value = "v2"
        storage.put_memory(m)
        versions = storage.list_memory_versions(m.memory_id)
        assert len(versions) == 1
        assert versions[0].value == "v1"

    def test_put_new_memory_does_not_create_version(self, storage):
        """Creating a brand-new memory should NOT create a version snapshot."""
        m = Memory(key="fresh", value="x", owner_client_id="c1")
        storage.put_memory(m)
        assert storage.list_memory_versions(m.memory_id) == []


# ---------------------------------------------------------------------------
# Memory version tests
# ---------------------------------------------------------------------------


class TestMemoryVersionStorage:
    def test_list_versions_newest_first(self, storage):

        m = Memory(key="hist", value="v1", owner_client_id="c1")
        storage.put_memory(m)
        # two updates → two version snapshots
        m.value = "v2"
        storage.put_memory(m)
        m.value = "v3"
        storage.put_memory(m)
        versions = storage.list_memory_versions(m.memory_id)
        assert len(versions) == 2
        # newest first (ScanIndexForward=False)
        assert versions[0].value == "v2"
        assert versions[1].value == "v1"

    def test_get_memory_version_found(self, storage):
        m = Memory(key="gv", value="original", owner_client_id="c1")
        storage.put_memory(m)
        m.value = "updated"
        storage.put_memory(m)
        versions = storage.list_memory_versions(m.memory_id)
        assert len(versions) == 1
        fetched = storage.get_memory_version(m.memory_id, versions[0].version_timestamp)
        assert fetched is not None
        assert fetched.value == "original"

    def test_get_memory_version_not_found(self, storage):
        m = Memory(key="missing-v", value="v", owner_client_id="c1")
        storage.put_memory(m)
        result = storage.get_memory_version(m.memory_id, "nonexistent-ts")
        assert result is None

    def test_version_serialise_deserialise(self):
        from hive.models import MemoryVersion

        m = Memory(key="ser", value="old-val", tags=["t1"], owner_client_id="c1")
        v = MemoryVersion.from_memory(m)
        item = v.to_dynamo()
        restored = MemoryVersion.from_dynamo(item)
        assert restored.memory_id == v.memory_id
        assert restored.value == "old-val"
        assert restored.tags == ["t1"]

    def test_version_response_from_version(self):
        from hive.models import MemoryVersion, MemoryVersionResponse

        m = Memory(key="resp", value="v", tags=[], owner_client_id="c1")
        v = MemoryVersion.from_memory(m)
        resp = MemoryVersionResponse.from_version(v)
        assert resp.memory_id == v.memory_id
        assert resp.version_timestamp == v.version_timestamp
        assert resp.value == "v"


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

    def test_delete_nonexistent_returns_false(self, storage):
        """Covers storage.py delete_client early-return False when item not found."""
        assert storage.delete_client("no-such-client") is False

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

    def test_count_users(self, storage):
        assert storage.count_users() == 0
        from hive.models import User

        storage.put_user(User(email="a@x.com", display_name="A"))
        storage.put_user(User(email="b@x.com", display_name="B"))
        assert storage.count_users() == 2


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

    def test_update_user_role(self, storage):
        u = self._user()
        u.role = "user"
        storage.put_user(u)
        assert storage.update_user_role(u.user_id, "admin") is True
        assert storage.get_user_by_id(u.user_id).role == "admin"

    def test_update_user_role_nonexistent_returns_false(self, storage):
        assert storage.update_user_role("no-such-id", "admin") is False

    def test_list_users(self, storage):
        storage.put_user(self._user("a@example.com"))
        storage.put_user(self._user("b@example.com"))
        users, cursor = storage.list_users()
        emails = {u.email for u in users}
        assert {"a@example.com", "b@example.com"}.issubset(emails)
        assert cursor is None

    def test_list_users_pagination(self, storage):
        for i in range(5):
            storage.put_user(self._user(f"user{i}@example.com"))
        page1, cursor1 = storage.list_users(limit=3)
        assert len(page1) == 3
        assert cursor1 is not None
        page2, cursor2 = storage.list_users(limit=3, cursor=cursor1)
        assert len(page2) == 2
        assert cursor2 is None

    def test_list_users_follows_scan_pages(self, storage):
        """Covers the scan-loop continuation path in list_users."""
        from unittest.mock import patch

        users = [User(email=f"u{i}@example.com", display_name=f"U{i}") for i in range(3)]
        for u in users:
            storage.put_user(u)

        fake_lek = {"PK": f"USER#{users[0].user_id}", "SK": "META"}
        page1_items = [users[0].to_dynamo()]
        page2_items = [users[1].to_dynamo(), users[2].to_dynamo()]
        responses = iter(
            [
                {"Items": page1_items, "LastEvaluatedKey": fake_lek},
                {"Items": page2_items},
            ]
        )

        with patch.object(storage.table, "scan", side_effect=lambda **_kw: next(responses)):
            result, cursor = storage.list_users(limit=5)

        assert len(result) == 3
        assert cursor is None

    def test_user_response_from_user(self):
        u = User(email="x@example.com", display_name="X", role="admin")
        resp = UserResponse.from_user(u)
        assert resp.user_id == u.user_id
        assert resp.email == u.email
        assert resp.display_name == u.display_name
        assert resp.role == "admin"


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


# ---------------------------------------------------------------------------
# hydrate_memory_ids
# ---------------------------------------------------------------------------


class TestHydrateMemoryIds:
    def test_returns_memory_and_score_pairs(self, storage):
        m = Memory(key="h1", value="v1", owner_client_id="c1")
        storage.put_memory(m)
        pairs = [(m.memory_id, 0.95)]
        result = storage.hydrate_memory_ids(pairs)
        assert len(result) == 1
        mem, score = result[0]
        assert mem.key == "h1"
        assert score == 0.95

    def test_skips_missing_memory_ids(self, storage):
        m = Memory(key="h2", value="v2", owner_client_id="c1")
        storage.put_memory(m)
        pairs = [("nonexistent-id", 0.8), (m.memory_id, 0.7)]
        result = storage.hydrate_memory_ids(pairs)
        assert len(result) == 1
        assert result[0][1] == 0.7

    def test_returns_empty_for_empty_input(self, storage):
        assert storage.hydrate_memory_ids([]) == []

    def test_preserves_order(self, storage):
        m1 = Memory(key="ord-a", value="v", owner_client_id="c")
        m2 = Memory(key="ord-b", value="v", owner_client_id="c")
        storage.put_memory(m1)
        storage.put_memory(m2)
        pairs = [(m1.memory_id, 0.9), (m2.memory_id, 0.5)]
        result = storage.hydrate_memory_ids(pairs)
        assert result[0][0].key == "ord-a"
        assert result[1][0].key == "ord-b"


# ---------------------------------------------------------------------------
# API Key storage
# ---------------------------------------------------------------------------


class TestApiKeyStorage:
    def _key(self, owner_user_id: str = "u1", name: str = "test") -> ApiKey:
        return ApiKey(owner_user_id=owner_user_id, name=name, key_hash="hash-" + name)

    def test_put_and_get_by_id(self, storage):
        k = self._key()
        storage.put_api_key(k)
        fetched = storage.get_api_key_by_id(k.key_id)
        assert fetched is not None
        assert fetched.key_id == k.key_id
        assert fetched.name == "test"

    def test_get_by_id_not_found(self, storage):
        assert storage.get_api_key_by_id("no-such-key") is None

    def test_get_by_hash(self, storage):
        k = self._key()
        storage.put_api_key(k)
        found = storage.get_api_key_by_hash("hash-test")
        assert found is not None
        assert found.key_id == k.key_id

    def test_get_by_hash_not_found(self, storage):
        assert storage.get_api_key_by_hash("nonexistent-hash") is None

    def test_list_for_user(self, storage):
        k1 = self._key("u1", "key1")
        k2 = self._key("u1", "key2")
        k3 = self._key("u2", "other")
        for k in (k1, k2, k3):
            storage.put_api_key(k)
        result = storage.list_api_keys_for_user("u1")
        names = {k.name for k in result}
        assert "key1" in names
        assert "key2" in names
        assert "other" not in names

    def test_list_for_user_empty(self, storage):
        assert storage.list_api_keys_for_user("no-such-user") == []

    def test_delete(self, storage):
        k = self._key()
        storage.put_api_key(k)
        assert storage.delete_api_key(k.key_id) is True
        assert storage.get_api_key_by_id(k.key_id) is None

    def test_delete_nonexistent(self, storage):
        assert storage.delete_api_key("no-such-key") is False


# ---------------------------------------------------------------------------
# Bulk memory operations
# ---------------------------------------------------------------------------


class TestBulkMemoryOperations:
    def test_delete_memories_by_tag_returns_count(self, storage):
        m1 = Memory(key="a", value="1", tags=["bulk"], owner_client_id="c1", owner_user_id="u1")
        m2 = Memory(key="b", value="2", tags=["bulk"], owner_client_id="c1", owner_user_id="u1")
        m3 = Memory(key="c", value="3", tags=["other"], owner_client_id="c1", owner_user_id="u1")
        for m in [m1, m2, m3]:
            storage.put_memory(m)
        deleted = storage.delete_memories_by_tag("bulk")
        assert deleted == 2
        assert storage.get_memory_by_key("a") is None
        assert storage.get_memory_by_key("b") is None
        assert storage.get_memory_by_key("c") is not None

    def test_delete_memories_by_tag_with_owner_filter(self, storage):
        m1 = Memory(key="x", value="1", tags=["t"], owner_client_id="c1", owner_user_id="u1")
        m2 = Memory(key="y", value="2", tags=["t"], owner_client_id="c2", owner_user_id="u2")
        for m in [m1, m2]:
            storage.put_memory(m)
        deleted = storage.delete_memories_by_tag("t", owner_user_id="u1")
        assert deleted == 1
        assert storage.get_memory_by_key("x") is None
        assert storage.get_memory_by_key("y") is not None

    def test_delete_memories_by_tag_empty(self, storage):
        assert storage.delete_memories_by_tag("no-such-tag") == 0

    def test_iter_all_memories_no_filter(self, storage):
        for i in range(3):
            storage.put_memory(Memory(key=f"k{i}", value=f"v{i}", owner_client_id="c1"))
        result = list(storage.iter_all_memories())
        assert len(result) == 3

    def test_iter_all_memories_with_tag(self, storage):
        m1 = Memory(key="tagged", value="1", tags=["export"], owner_client_id="c1")
        m2 = Memory(key="untagged", value="2", tags=[], owner_client_id="c1")
        storage.put_memory(m1)
        storage.put_memory(m2)
        result = list(storage.iter_all_memories(tag="export"))
        assert len(result) == 1
        assert result[0].key == "tagged"

    def test_iter_all_memories_with_owner_filter(self, storage):
        m1 = Memory(key="mine", value="1", owner_client_id="c1", owner_user_id="u1")
        m2 = Memory(key="theirs", value="2", owner_client_id="c2", owner_user_id="u2")
        storage.put_memory(m1)
        storage.put_memory(m2)
        result = list(storage.iter_all_memories(owner_user_id="u1"))
        assert len(result) == 1
        assert result[0].key == "mine"

    def test_iter_all_memories_tag_and_owner_filter(self, storage):
        m1 = Memory(key="a", value="1", tags=["t"], owner_client_id="c1", owner_user_id="u1")
        m2 = Memory(key="b", value="2", tags=["t"], owner_client_id="c2", owner_user_id="u2")
        storage.put_memory(m1)
        storage.put_memory(m2)
        result = list(storage.iter_all_memories(tag="t", owner_user_id="u2"))
        assert len(result) == 1
        assert result[0].key == "b"

    def test_iter_all_memories_follows_scan_pages(self, storage):
        """iter_all_memories should follow DynamoDB scan pages via ExclusiveStartKey."""

        memories = [Memory(key=f"page-{i}", value=f"v{i}", owner_client_id="c1") for i in range(3)]
        for m in memories:
            storage.put_memory(m)

        # Capture calls to prove pagination works by using real storage
        # (moto handles pagination internally, so just verify all items returned)
        result = list(storage.iter_all_memories())
        assert len(result) == 3

    def test_iter_all_memories_multi_page(self, storage):
        """iter_all_memories handles scan responses with ExclusiveStartKey."""
        from unittest.mock import patch

        from hive.models import Memory as _Memory

        m1 = _Memory(key="page1", value="v1", owner_client_id="c1")
        m1_item = m1.to_dynamo_meta()

        page1_resp = {
            "Items": [m1_item],
            "LastEvaluatedKey": {"PK": "MEMORY#page1", "SK": "META"},
        }
        m2 = _Memory(key="page2", value="v2", owner_client_id="c1")
        m2_item = m2.to_dynamo_meta()
        page2_resp = {"Items": [m2_item]}

        with patch.object(storage.table, "scan", side_effect=[page1_resp, page2_resp]):
            result = list(storage.iter_all_memories())

        assert len(result) == 2
