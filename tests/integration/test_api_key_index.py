# Copyright (c) 2026 John Carter. All rights reserved.
"""
Integration tests for #589 / #596 — API key lookups via the ApiKeyHashIndex
and ApiKeyOwnerIndex GSIs.

Runs against DynamoDB Local (Docker) — set DYNAMODB_ENDPOINT env var.

Two tables are exercised:

- one **with** ``ApiKeyHashIndex`` + ``ApiKeyOwnerIndex`` — proves
  ``get_api_key_by_hash`` and ``list_api_keys_for_user`` resolve keys
  through single-partition GSI queries (the fast paths) against a real
  DynamoDB query engine, not just moto;
- one **without** the indexes — proves the graceful-degradation contract: a
  real ``ValidationException`` from DynamoDB Local triggers the legacy
  full-table-scan fallback, which is what production relies on while the
  GSIs are still backfilling after deployment.
"""

from __future__ import annotations

import contextlib
import os

import pytest

from hive.models import ApiKey

DYNAMO_ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT")

pytestmark = pytest.mark.skipif(
    not DYNAMO_ENDPOINT,
    reason="DYNAMODB_ENDPOINT not set — skipping integration tests",
)

_BASE_TABLE_KWARGS = {
    "KeySchema": [
        {"AttributeName": "PK", "KeyType": "HASH"},
        {"AttributeName": "SK", "KeyType": "RANGE"},
    ],
    "BillingMode": "PAY_PER_REQUEST",
}


def _ddb_client():
    import boto3

    return boto3.client(
        "dynamodb",
        endpoint_url=DYNAMO_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )


def _storage_for(table_name: str):
    from hive.storage import HiveStorage

    return HiveStorage(
        table_name=table_name,
        region="us-east-1",
        endpoint_url=DYNAMO_ENDPOINT,
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )


@pytest.fixture(scope="module")
def storage_with_index():
    """HiveStorage on a table carrying both API key GSIs (production schema)."""
    ddb = _ddb_client()
    table_name = "hive-integration-apikey-idx"
    with contextlib.suppress(Exception):
        ddb.delete_table(TableName=table_name)
    ddb.create_table(
        TableName=table_name,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "key_hash", "AttributeType": "S"},
            {"AttributeName": "owner_user_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "ApiKeyHashIndex",
                "KeySchema": [
                    {"AttributeName": "key_hash", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "ApiKeyOwnerIndex",
                "KeySchema": [
                    {"AttributeName": "owner_user_id", "KeyType": "HASH"},
                    {"AttributeName": "PK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        **_BASE_TABLE_KWARGS,
    )
    yield _storage_for(table_name)


@pytest.fixture(scope="module")
def storage_without_index():
    """HiveStorage on a legacy-schema table lacking both API key GSIs."""
    ddb = _ddb_client()
    table_name = "hive-integration-apikey-noidx"
    with contextlib.suppress(Exception):
        ddb.delete_table(TableName=table_name)
    ddb.create_table(
        TableName=table_name,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        **_BASE_TABLE_KWARGS,
    )
    yield _storage_for(table_name)


def _make_key(name: str) -> ApiKey:
    return ApiKey(owner_user_id="int-user", name=name, key_hash=f"int-hash-{name}")


class TestApiKeyHashIndexQuery:
    """Fast path — lookups resolve through the GSI on a real DynamoDB engine."""

    def test_lookup_hits_gsi(self, storage_with_index):
        from unittest.mock import patch

        key = _make_key("gsi-hit")
        storage_with_index.put_api_key(key)
        # Block the scan path entirely — the GSI query alone must resolve it.
        with patch.object(storage_with_index.table, "scan") as mock_scan:
            found = storage_with_index.get_api_key_by_hash("int-hash-gsi-hit")
        assert found is not None
        assert found.key_id == key.key_id
        assert found.owner_user_id == "int-user"
        mock_scan.assert_not_called()

    def test_lookup_miss_returns_none(self, storage_with_index):
        assert storage_with_index.get_api_key_by_hash("int-hash-absent") is None


class TestApiKeyHashIndexFallback:
    """Degraded path — a table without the GSI still resolves keys via scan."""

    def test_lookup_falls_back_to_scan(self, storage_without_index):
        key = _make_key("legacy")
        storage_without_index.put_api_key(key)
        found = storage_without_index.get_api_key_by_hash("int-hash-legacy")
        assert found is not None
        assert found.key_id == key.key_id

    def test_fallback_miss_returns_none(self, storage_without_index):
        assert storage_without_index.get_api_key_by_hash("int-hash-nope") is None


def _make_owned_key(owner_user_id: str, name: str) -> ApiKey:
    return ApiKey(owner_user_id=owner_user_id, name=name, key_hash=f"int-hash-{name}")


class TestApiKeyOwnerIndexQuery:
    """Fast path — listings resolve through the GSI on a real DynamoDB engine."""

    def test_list_hits_gsi(self, storage_with_index):
        from unittest.mock import patch

        k1 = _make_owned_key("int-owner-list", "owner-a")
        k2 = _make_owned_key("int-owner-list", "owner-b")
        storage_with_index.put_api_key(k1)
        storage_with_index.put_api_key(k2)
        storage_with_index.put_api_key(_make_owned_key("int-owner-other", "owner-c"))
        # ApiKeyOwnerIndex is not sparse — a workspace item owned by the same
        # user lands in the same index partition. The begins_with(PK, APIKEY#)
        # sort-key condition must keep it out of the listing.
        storage_with_index.table.put_item(
            Item={
                "PK": "WORKSPACE#int-ws",
                "SK": "META",
                "owner_user_id": "int-owner-list",
                "name": "ws",
            }
        )
        # Block the scan path entirely — the GSI query alone must resolve it.
        with patch.object(storage_with_index.table, "scan") as mock_scan:
            result = storage_with_index.list_api_keys_for_user("int-owner-list")
        assert {k.name for k in result} == {"owner-a", "owner-b"}
        mock_scan.assert_not_called()

    def test_list_miss_returns_empty(self, storage_with_index):
        assert storage_with_index.list_api_keys_for_user("int-owner-absent") == []


class TestApiKeyOwnerIndexFallback:
    """Degraded path — a table without the GSI still lists keys via scan."""

    def test_list_falls_back_to_scan(self, storage_without_index):
        key = _make_owned_key("int-owner-fallback", "owner-legacy")
        storage_without_index.put_api_key(key)
        result = storage_without_index.list_api_keys_for_user("int-owner-fallback")
        assert [k.key_id for k in result] == [key.key_id]

    def test_fallback_miss_returns_empty(self, storage_without_index):
        assert storage_without_index.list_api_keys_for_user("int-owner-nope") == []
