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
