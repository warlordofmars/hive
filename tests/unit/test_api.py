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
    """TestClient with all auth dependencies overridden — no JWT needed."""
    with mock_aws():
        _create_table()
        from hive.api._auth import (
            require_clients_read,
            require_clients_write,
            require_memories_read,
            require_memories_write,
            require_token,
        )
        from hive.api.main import app
        from hive.models import OAuthClient
        from hive.storage import HiveStorage

        storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
        oauth_client = OAuthClient(client_name="Unit Test Client")
        storage.put_client(oauth_client)

        def _override():
            return (storage, oauth_client.client_id)

        for dep in (
            require_token,
            require_memories_read,
            require_memories_write,
            require_clients_read,
            require_clients_write,
        ):
            app.dependency_overrides[dep] = _override
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

    def test_create_oversized_returns_413(self, client):
        from unittest.mock import patch

        tc, storage, _ = client
        with patch.object(
            storage, "put_memory", side_effect=ValueError("Memory value is too large")
        ):
            resp = tc.post("/api/memories", json={"key": "big", "value": "x" * 1000})
        assert resp.status_code == 413
        assert "too large" in resp.json()["detail"]

    def test_update_oversized_returns_413(self, client):
        from unittest.mock import patch

        tc, storage, _ = client
        mid = tc.post("/api/memories", json={"key": "upd-big", "value": "small"}).json()[
            "memory_id"
        ]
        with patch.object(
            storage, "put_memory", side_effect=ValueError("Memory value is too large")
        ):
            resp = tc.patch(f"/api/memories/{mid}", json={"value": "x" * 1000})
        assert resp.status_code == 413

    def test_list_all(self, client):
        tc, *_ = client
        tc.post("/api/memories", json={"key": "a", "value": "1", "tags": ["x"]})
        tc.post("/api/memories", json={"key": "b", "value": "2", "tags": ["y"]})
        resp = tc.get("/api/memories")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data and "has_more" in data
        keys = {m["key"] for m in data["items"]}
        assert {"a", "b"}.issubset(keys)

    def test_list_filtered_by_tag(self, client):
        tc, *_ = client
        tc.post("/api/memories", json={"key": "tagged", "value": "v", "tags": ["filter-tag"]})
        tc.post("/api/memories", json={"key": "untagged", "value": "v", "tags": []})
        resp = tc.get("/api/memories", params={"tag": "filter-tag"})
        assert resp.status_code == 200
        keys = [m["key"] for m in resp.json()["items"]]
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
        data = resp.json()
        assert "items" in data and "has_more" in data
        assert len(data["items"]) >= 2

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
        data = resp.json()
        assert "items" in data and "has_more" in data
        assert isinstance(data["items"], list)

    def test_get_activity_custom_days(self, client):
        tc, *_ = client
        resp = tc.get("/api/activity", params={"days": 1})
        assert resp.status_code == 200

    def test_get_activity_invalid_days(self, client):
        tc, *_ = client
        resp = tc.get("/api/activity", params={"days": 0})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# _app_version() branches — covers api/main.py:33 and 36-37
# ---------------------------------------------------------------------------


class TestAppVersion:
    def test_returns_env_var_when_set(self):
        """Covers main.py line where APP_VERSION env var is returned."""
        from unittest.mock import patch

        from hive.api.main import _app_version

        with patch.dict(os.environ, {"APP_VERSION": "9.8.7"}):
            assert _app_version() == "9.8.7"

    def test_returns_dev_when_package_not_found(self):
        """Covers main.py PackageNotFoundError fallback to 'dev'."""
        import importlib.metadata
        from unittest.mock import patch

        from hive.api.main import _app_version

        env = {k: v for k, v in os.environ.items() if k != "APP_VERSION"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch(
                "hive.api.main.importlib.metadata.version",
                side_effect=importlib.metadata.PackageNotFoundError,
            ),
        ):
            assert _app_version() == "dev"


# ---------------------------------------------------------------------------
# Client create — invalid grant type → 400 (covers clients.py:51-52)
# ---------------------------------------------------------------------------


class TestClientCreateErrors:
    def test_create_invalid_grant_type_returns_400(self, client):
        tc, *_ = client
        resp = tc.post(
            "/api/clients",
            json={"client_name": "Bad App", "grant_types": ["password"]},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Memory upsert oversized → 413 (covers memories.py:68-69)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# require_token success path — covers api/_auth.py:31
# ---------------------------------------------------------------------------


class TestRequireTokenSuccessPath:
    def test_valid_jwt_reaches_endpoint(self):
        """Covers _auth.py require_scope — valid token reaches endpoint."""
        from datetime import datetime, timedelta, timezone

        from hive.auth.tokens import issue_jwt
        from hive.models import OAuthClient, Token
        from hive.storage import HiveStorage

        # Ensure the table name env var matches what we create, regardless of
        # what the combined test run has set (e.g. hive-integration in CI).
        old_table = os.environ.get("HIVE_TABLE_NAME")
        os.environ["HIVE_TABLE_NAME"] = "hive-unit-api"
        try:
            with mock_aws():
                _create_table()
                storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
                oauth_client = OAuthClient(client_name="Real Auth Client")
                storage.put_client(oauth_client)

                now = datetime.now(timezone.utc)
                token = Token(
                    client_id=oauth_client.client_id,
                    scope="memories:read memories:write clients:read clients:write",
                    issued_at=now,
                    expires_at=now + timedelta(hours=1),
                )
                storage.put_token(token)
                jwt = issue_jwt(token)

                from hive.api.main import app

                app.dependency_overrides.clear()
                from fastapi.testclient import TestClient

                tc = TestClient(app, raise_server_exceptions=False)
                resp = tc.get("/api/memories", headers={"Authorization": f"Bearer {jwt}"})
                assert resp.status_code == 200
        finally:
            if old_table is not None:
                os.environ["HIVE_TABLE_NAME"] = old_table
            else:
                os.environ.pop("HIVE_TABLE_NAME", None)

    async def test_require_token_valid_token(self):
        """Covers _auth.py:28-33 — require_token returns (storage, client_id) on valid token."""
        from datetime import datetime, timedelta, timezone

        from fastapi.security import HTTPAuthorizationCredentials

        from hive.api._auth import require_token
        from hive.auth.tokens import issue_jwt
        from hive.models import OAuthClient, Token
        from hive.storage import HiveStorage

        old_table = os.environ.get("HIVE_TABLE_NAME")
        os.environ["HIVE_TABLE_NAME"] = "hive-unit-api"
        try:
            with mock_aws():
                _create_table()
                storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
                oauth_client = OAuthClient(client_name="Direct Token Test")
                storage.put_client(oauth_client)

                now = datetime.now(timezone.utc)
                token = Token(
                    client_id=oauth_client.client_id,
                    scope="memories:read",
                    issued_at=now,
                    expires_at=now + timedelta(hours=1),
                )
                storage.put_token(token)
                jwt_str = issue_jwt(token)

                creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=jwt_str)
                result_storage, result_client_id = await require_token(
                    credentials=creds, storage=storage
                )
                assert result_client_id == oauth_client.client_id
        finally:
            if old_table is not None:
                os.environ["HIVE_TABLE_NAME"] = old_table
            else:
                os.environ.pop("HIVE_TABLE_NAME", None)

    async def test_require_token_invalid_jwt_raises_401(self):
        """Covers _auth.py:30-32 — invalid JWT raises HTTP 401."""
        from unittest.mock import MagicMock

        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        from hive.api._auth import require_token

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt")
        storage = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await require_token(credentials=creds, storage=storage)
        assert exc_info.value.status_code == 401


class TestMemoryUpsertOversized:
    def test_upsert_existing_oversized_returns_413(self, client):
        """POST with existing key hits upsert path; oversized raises 413."""
        from unittest.mock import patch

        tc, storage, _ = client
        # Create the memory first so upsert path is taken
        tc.post("/api/memories", json={"key": "upsert-big", "value": "small"})
        with patch.object(
            storage, "put_memory", side_effect=ValueError("Memory value is too large")
        ):
            resp = tc.post("/api/memories", json={"key": "upsert-big", "value": "x" * 1000})
        assert resp.status_code == 413


# ---------------------------------------------------------------------------
# Scope enforcement — covers api/_auth.py require_scope
# ---------------------------------------------------------------------------


def _scoped_client_fixture(scope: str):
    """Build a TestClient with a real token limited to the given scope."""
    from datetime import datetime, timedelta, timezone

    from hive.api.main import app
    from hive.auth.tokens import issue_jwt
    from hive.models import OAuthClient, Token
    from hive.storage import HiveStorage

    storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
    oauth_client = OAuthClient(client_name="Scope Test Client", scope=scope)
    storage.put_client(oauth_client)

    now = datetime.now(timezone.utc)
    token = Token(
        client_id=oauth_client.client_id,
        scope=scope,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    storage.put_token(token)
    jwt = issue_jwt(token)

    # Clear all dependency overrides so actual scope checks run
    app.dependency_overrides.clear()
    return TestClient(app, raise_server_exceptions=False), jwt


class TestScopeEnforcement:
    def test_read_scope_allows_get_memories(self):
        with mock_aws():
            _create_table()
            old = os.environ.get("HIVE_TABLE_NAME")
            os.environ["HIVE_TABLE_NAME"] = "hive-unit-api"
            try:
                tc, jwt = _scoped_client_fixture("memories:read")
                resp = tc.get("/api/memories", headers={"Authorization": f"Bearer {jwt}"})
                assert resp.status_code == 200
            finally:
                if old is not None:
                    os.environ["HIVE_TABLE_NAME"] = old
                else:
                    os.environ.pop("HIVE_TABLE_NAME", None)
                from hive.api.main import app

                app.dependency_overrides.clear()

    def test_read_scope_blocks_post_memories(self):
        with mock_aws():
            _create_table()
            old = os.environ.get("HIVE_TABLE_NAME")
            os.environ["HIVE_TABLE_NAME"] = "hive-unit-api"
            try:
                tc, jwt = _scoped_client_fixture("memories:read")
                resp = tc.post(
                    "/api/memories",
                    json={"key": "k", "value": "v"},
                    headers={"Authorization": f"Bearer {jwt}"},
                )
                assert resp.status_code == 403
            finally:
                if old is not None:
                    os.environ["HIVE_TABLE_NAME"] = old
                else:
                    os.environ.pop("HIVE_TABLE_NAME", None)
                from hive.api.main import app

                app.dependency_overrides.clear()

    def test_memories_scope_blocks_clients_endpoint(self):
        with mock_aws():
            _create_table()
            old = os.environ.get("HIVE_TABLE_NAME")
            os.environ["HIVE_TABLE_NAME"] = "hive-unit-api"
            try:
                tc, jwt = _scoped_client_fixture("memories:read memories:write")
                resp = tc.get("/api/clients", headers={"Authorization": f"Bearer {jwt}"})
                assert resp.status_code == 403
            finally:
                if old is not None:
                    os.environ["HIVE_TABLE_NAME"] = old
                else:
                    os.environ.pop("HIVE_TABLE_NAME", None)
                from hive.api.main import app

                app.dependency_overrides.clear()

    def test_clients_read_scope_allows_list_clients(self):
        with mock_aws():
            _create_table()
            old = os.environ.get("HIVE_TABLE_NAME")
            os.environ["HIVE_TABLE_NAME"] = "hive-unit-api"
            try:
                tc, jwt = _scoped_client_fixture("clients:read")
                resp = tc.get("/api/clients", headers={"Authorization": f"Bearer {jwt}"})
                assert resp.status_code == 200
            finally:
                if old is not None:
                    os.environ["HIVE_TABLE_NAME"] = old
                else:
                    os.environ.pop("HIVE_TABLE_NAME", None)
                from hive.api.main import app

                app.dependency_overrides.clear()
