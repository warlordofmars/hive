# Copyright (c) 2026 John Carter. All rights reserved.
"""
Unit tests for the DELETE /api/account self-service account deletion endpoint.
"""

from __future__ import annotations

import os

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

os.environ.setdefault("HIVE_TABLE_NAME", "hive-unit-account")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("HIVE_JWT_SECRET", "unit-test-secret")
os.environ.pop("DYNAMODB_ENDPOINT", None)

_USER_ID = "account-user-001"
_USER_CLAIMS = {"sub": _USER_ID, "role": "user", "email": "user@example.com"}


def _create_table() -> None:
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="hive-unit-account",
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


@pytest.fixture()
def client():
    with mock_aws():
        _create_table()
        from hive.api import _auth as auth_mod
        from hive.api import account as account_mod
        from hive.api.main import app
        from hive.models import Memory, User
        from hive.storage import HiveStorage

        storage = HiveStorage(table_name="hive-unit-account", region="us-east-1")

        user = User(user_id=_USER_ID, email="user@example.com", display_name="Test", role="user")
        storage.put_user(user)

        # Pre-seed a memory and a client so we can verify deletion
        memory = Memory(
            key="test-key",
            value="test-value",
            tags=["t1"],
            owner_client_id=_USER_ID,
            owner_user_id=_USER_ID,
        )
        storage.put_memory(memory)

        def _override_mgmt_user():
            return _USER_CLAIMS

        def _override_storage():
            return storage

        app.dependency_overrides[auth_mod.require_mgmt_user] = _override_mgmt_user
        app.dependency_overrides[account_mod._storage] = _override_storage
        yield TestClient(app), storage
        app.dependency_overrides.clear()


@pytest.fixture()
def unauthed_client():
    with mock_aws():
        _create_table()
        from hive.api.main import app

        app.dependency_overrides.clear()
        yield TestClient(app, raise_server_exceptions=False)


class TestDeleteAccount:
    def test_requires_confirm_true(self, client):
        tc, _ = client
        resp = tc.request("DELETE", "/api/account", json={"confirm": False})
        assert resp.status_code == 400
        assert "confirm" in resp.json()["detail"]

    def test_requires_confirm_field(self, client):
        tc, _ = client
        resp = tc.request("DELETE", "/api/account", json={})
        assert resp.status_code == 400

    def test_deletes_account_and_data(self, client):
        tc, storage = client
        resp = tc.request("DELETE", "/api/account", json={"confirm": True})
        assert resp.status_code == 204
        # User record should be gone
        assert storage.get_user_by_id(_USER_ID) is None
        # Memory should be gone
        memories, _ = storage.list_all_memories(owner_user_id=_USER_ID, limit=10)
        assert memories == []

    def test_returns_404_if_user_not_found(self, client):
        tc, storage = client
        # Delete user first so it's missing on the DELETE call
        storage.delete_user(_USER_ID)
        resp = tc.request("DELETE", "/api/account", json={"confirm": True})
        assert resp.status_code == 404

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.request("DELETE", "/api/account", json={"confirm": True})
        assert resp.status_code in (401, 403)
