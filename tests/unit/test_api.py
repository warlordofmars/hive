# Copyright (c) 2026 John Carter. All rights reserved.
"""
Unit tests for the Hive management API (FastAPI).

Uses moto to mock DynamoDB and overrides the require_token dependency
so tests don't need a live JWT — auth failure cases use a separate fixture
that leaves the override cleared.
"""

from __future__ import annotations

import os

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

os.environ.setdefault("HIVE_TABLE_NAME", "hive-unit-api")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("HIVE_JWT_SECRET", "unit-test-secret")
# Ensure unit tests never try to hit a real DynamoDB endpoint
os.environ.pop("DYNAMODB_ENDPOINT", None)


def _create_table(table_name: str = "hive-unit-api") -> None:
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=table_name,
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


@pytest.fixture()
def client():
    """TestClient with require_token overridden — no JWT needed."""
    with mock_aws():
        _create_table()
        from hive.api._auth import require_token
        from hive.api.main import app
        from hive.models import OAuthClient
        from hive.storage import HiveStorage

        storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
        oauth_client = OAuthClient(client_name="Unit Test Client")
        storage.put_client(oauth_client)

        def _override():
            return (storage, oauth_client.client_id)

        app.dependency_overrides[require_token] = _override
        yield TestClient(app), storage, oauth_client.client_id
        app.dependency_overrides.clear()


@pytest.fixture()
def unauthed_client():
    """TestClient without any auth override — used to test 401 paths."""
    with mock_aws():
        _create_table()
        from hive.api.main import app

        app.dependency_overrides.clear()
        yield TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Health check + version
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health(self, client):
        tc, *_ = client
        resp = tc.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


# ---------------------------------------------------------------------------
# Auth failures
# ---------------------------------------------------------------------------


class TestAuthFailures:
    def test_missing_token_returns_4xx(self, unauthed_client):
        resp = unauthed_client.get("/api/memories")
        assert resp.status_code in (401, 403)

    def test_invalid_token_returns_401(self, unauthed_client):
        resp = unauthed_client.get(
            "/api/memories", headers={"Authorization": "Bearer not-a-valid-jwt"}
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Memory endpoints
# ---------------------------------------------------------------------------


class TestMemories:
    def test_create_returns_201(self, client):
        tc, *_ = client
        resp = tc.post("/api/memories", json={"key": "k1", "value": "v1", "tags": ["t"]})
        assert resp.status_code == 201
        data = resp.json()
        assert data["key"] == "k1"
        assert data["tags"] == ["t"]

    def test_create_duplicate_key_upserts_200(self, client):
        tc, *_ = client
        tc.post("/api/memories", json={"key": "dup", "value": "original"})
        resp = tc.post("/api/memories", json={"key": "dup", "value": "updated"})
        assert resp.status_code == 200
        assert resp.json()["value"] == "updated"

    def test_list_all(self, client):
        tc, *_ = client
        tc.post("/api/memories", json={"key": "a", "value": "1", "tags": ["x"]})
        tc.post("/api/memories", json={"key": "b", "value": "2", "tags": ["y"]})
        resp = tc.get("/api/memories")
        assert resp.status_code == 200
        keys = {m["key"] for m in resp.json()}
        assert {"a", "b"}.issubset(keys)

    def test_list_filtered_by_tag(self, client):
        tc, *_ = client
        tc.post("/api/memories", json={"key": "tagged", "value": "v", "tags": ["filter-tag"]})
        tc.post("/api/memories", json={"key": "untagged", "value": "v", "tags": []})
        resp = tc.get("/api/memories", params={"tag": "filter-tag"})
        assert resp.status_code == 200
        keys = [m["key"] for m in resp.json()]
        assert "tagged" in keys
        assert "untagged" not in keys

    def test_get_by_id(self, client):
        tc, *_ = client
        mid = tc.post("/api/memories", json={"key": "gid", "value": "v"}).json()["memory_id"]
        resp = tc.get(f"/api/memories/{mid}")
        assert resp.status_code == 200
        assert resp.json()["memory_id"] == mid

    def test_get_nonexistent_returns_404(self, client):
        tc, *_ = client
        resp = tc.get("/api/memories/no-such-id")
        assert resp.status_code == 404

    def test_update(self, client):
        tc, *_ = client
        mid = tc.post("/api/memories", json={"key": "upd", "value": "old"}).json()["memory_id"]
        resp = tc.patch(f"/api/memories/{mid}", json={"value": "new", "tags": ["t2"]})
        assert resp.status_code == 200
        assert resp.json()["value"] == "new"

    def test_update_nonexistent_returns_404(self, client):
        tc, *_ = client
        resp = tc.patch("/api/memories/no-such-id", json={"value": "x"})
        assert resp.status_code == 404

    def test_delete(self, client):
        tc, *_ = client
        mid = tc.post("/api/memories", json={"key": "del", "value": "v"}).json()["memory_id"]
        resp = tc.delete(f"/api/memories/{mid}")
        assert resp.status_code == 204
        assert tc.get(f"/api/memories/{mid}").status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        tc, *_ = client
        resp = tc.delete("/api/memories/no-such-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Client endpoints
# ---------------------------------------------------------------------------


class TestClients:
    def test_create_returns_201(self, client):
        tc, *_ = client
        resp = tc.post(
            "/api/clients",
            json={
                "client_name": "New App",
                "redirect_uris": ["https://app.example.com/cb"],
            },
        )
        assert resp.status_code == 201
        assert resp.json()["client_name"] == "New App"

    def test_list(self, client):
        tc, *_ = client
        tc.post("/api/clients", json={"client_name": "App A"})
        tc.post("/api/clients", json={"client_name": "App B"})
        resp = tc.get("/api/clients")
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    def test_get_by_id(self, client):
        tc, *_ = client
        cid = tc.post("/api/clients", json={"client_name": "GetMe"}).json()["client_id"]
        resp = tc.get(f"/api/clients/{cid}")
        assert resp.status_code == 200
        assert resp.json()["client_id"] == cid

    def test_get_nonexistent_returns_404(self, client):
        tc, *_ = client
        resp = tc.get("/api/clients/no-such-id")
        assert resp.status_code == 404

    def test_delete(self, client):
        tc, *_ = client
        cid = tc.post("/api/clients", json={"client_name": "ToDelete"}).json()["client_id"]
        resp = tc.delete(f"/api/clients/{cid}")
        assert resp.status_code == 204

    def test_delete_nonexistent_returns_404(self, client):
        tc, *_ = client
        resp = tc.delete("/api/clients/no-such-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Stats + activity endpoints
# ---------------------------------------------------------------------------


class TestStats:
    def test_get_stats(self, client):
        tc, *_ = client
        tc.post("/api/memories", json={"key": "s1", "value": "v"})
        resp = tc.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_memories"] >= 1
        assert "total_clients" in data
        assert "events_today" in data
        assert "events_last_7_days" in data

    def test_get_activity_default(self, client):
        tc, *_ = client
        resp = tc.get("/api/activity")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_activity_custom_days(self, client):
        tc, *_ = client
        resp = tc.get("/api/activity", params={"days": 1})
        assert resp.status_code == 200

    def test_get_activity_invalid_days(self, client):
        tc, *_ = client
        resp = tc.get("/api/activity", params={"days": 0})
        assert resp.status_code == 422
