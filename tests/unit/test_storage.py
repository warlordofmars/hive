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

from hive.models import ActivityEvent, EventType, Memory, OAuthClient, TokenType
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

        tagged_y = storage.list_memories_by_tag("y")
        keys = {m.key for m in tagged_y}
        assert keys == {"a", "b"}

        tagged_z = storage.list_memories_by_tag("z")
        keys_z = {m.key for m in tagged_z}
        assert keys_z == {"b", "c"}

    def test_update_replaces_tags(self, storage):
        m = Memory(key="k", value="v", tags=["old"], owner_client_id="c1")
        storage.put_memory(m)

        m.tags = ["new"]
        storage.put_memory(m)

        old_tagged = storage.list_memories_by_tag("old")
        assert old_tagged == []
        new_tagged = storage.list_memories_by_tag("new")
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
        clients = storage.list_clients()
        assert len(clients) == 3


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
        all_mems = storage.list_all_memories()
        keys = {m.key for m in all_mems}
        assert {"x", "y"}.issubset(keys)

    def test_list_all_memories_filtered_by_client(self, storage):
        storage.put_memory(Memory(key="a", value="1", owner_client_id="client-a"))
        storage.put_memory(Memory(key="b", value="2", owner_client_id="client-b"))
        mems = storage.list_all_memories(client_id="client-a")
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
