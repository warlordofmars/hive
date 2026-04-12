# Copyright (c) 2026 John Carter. All rights reserved.
"""
Unit tests for the Hive management API (FastAPI).

Uses moto to mock DynamoDB and overrides require_mgmt_user so tests don't
need a live Google OAuth flow.  Auth failure cases use the unauthed_client
fixture which leaves the override cleared.
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


_TEST_USER_ID = "test-user-123"
_TEST_ADMIN_ID = "test-admin-456"
_USER_CLAIMS = {
    "sub": _TEST_USER_ID,
    "role": "user",
    "email": "user@example.com",
    "display_name": "Test User",
}
_ADMIN_CLAIMS = {
    "sub": _TEST_ADMIN_ID,
    "role": "admin",
    "email": "admin@example.com",
    "display_name": "Admin User",
}


def _setup_app_overrides(app, storage, claims):
    """Override require_mgmt_user and all _storage deps to use the fixture's objects."""
    from hive.api import _auth as auth_mod
    from hive.api import clients as clients_mod
    from hive.api import memories as memories_mod
    from hive.api import stats as stats_mod
    from hive.api import users as users_mod

    def _override_mgmt_user():
        return claims

    def _override_storage():
        return storage

    app.dependency_overrides[auth_mod.require_mgmt_user] = _override_mgmt_user
    for mod in (memories_mod, clients_mod, stats_mod, users_mod):
        app.dependency_overrides[mod._storage] = _override_storage


@pytest.fixture()
def client():
    """TestClient authenticated as a regular (non-admin) management user."""
    with mock_aws():
        _create_table()
        from hive.api.main import app
        from hive.models import User
        from hive.storage import HiveStorage

        storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
        user = User(
            user_id=_TEST_USER_ID,
            email="user@example.com",
            display_name="Test User",
            role="user",
        )
        storage.put_user(user)

        _setup_app_overrides(app, storage, _USER_CLAIMS)
        yield TestClient(app), storage, _TEST_USER_ID
        app.dependency_overrides.clear()


@pytest.fixture()
def admin_client():
    """TestClient authenticated as an admin management user."""
    with mock_aws():
        _create_table()
        from hive.api.main import app
        from hive.models import User
        from hive.storage import HiveStorage

        storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
        admin = User(
            user_id=_TEST_ADMIN_ID,
            email="admin@example.com",
            display_name="Admin User",
            role="admin",
        )
        storage.put_user(admin)

        _setup_app_overrides(app, storage, _ADMIN_CLAIMS)
        yield TestClient(app), storage, _TEST_ADMIN_ID
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
# OpenAPI schema + protected docs endpoints
# ---------------------------------------------------------------------------


class TestOpenAPI:
    def test_openapi_schema_is_non_empty(self, admin_client):
        tc, *_ = admin_client
        resp = tc.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert schema.get("info", {}).get("title") == "Hive Management API"
        assert schema.get("paths"), "OpenAPI schema must define at least one path"

    def test_docs_accessible_by_admin(self, admin_client):
        tc, *_ = admin_client
        resp = tc.get("/docs")
        assert resp.status_code == 200
        assert b"swagger" in resp.content.lower()

    def test_redoc_accessible_by_admin(self, admin_client):
        tc, *_ = admin_client
        resp = tc.get("/redoc")
        assert resp.status_code == 200
        assert b"redoc" in resp.content.lower()

    def test_docs_forbidden_for_non_admin(self, client):
        tc, *_ = client
        resp = tc.get("/docs")
        assert resp.status_code == 403

    def test_redoc_forbidden_for_non_admin(self, client):
        tc, *_ = client
        resp = tc.get("/redoc")
        assert resp.status_code == 403

    def test_docs_requires_auth(self, unauthed_client):
        resp = unauthed_client.get("/docs")
        assert resp.status_code in (401, 403)

    def test_redoc_requires_auth(self, unauthed_client):
        resp = unauthed_client.get("/redoc")
        assert resp.status_code in (401, 403)


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

    def test_search_returns_results_with_scores(self, client):
        from unittest.mock import MagicMock

        from hive.api import memories as memories_mod
        from hive.api.main import app

        tc, storage, _ = client
        tc.post("/api/memories", json={"key": "srch-k", "value": "relevant text", "tags": []})
        m = storage.get_memory_by_key("srch-k")

        mock_vs = MagicMock()
        mock_vs.search.return_value = [(m.memory_id, 0.91)]
        app.dependency_overrides[memories_mod._vector_store] = lambda: mock_vs

        resp = tc.get("/api/memories", params={"search": "relevant"})

        del app.dependency_overrides[memories_mod._vector_store]
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        item = data["items"][0]
        assert item["key"] == "srch-k"
        assert item["score"] == 0.91

    def test_search_returns_empty_when_no_index(self, client):
        from unittest.mock import MagicMock

        from hive.api import memories as memories_mod
        from hive.api.main import app
        from hive.vector_store import VectorIndexNotFoundError

        tc, *_ = client
        mock_vs = MagicMock()
        mock_vs.search.side_effect = VectorIndexNotFoundError("no index")
        app.dependency_overrides[memories_mod._vector_store] = lambda: mock_vs

        resp = tc.get("/api/memories", params={"search": "anything"})

        del app.dependency_overrides[memories_mod._vector_store]
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "count": 0, "has_more": False, "next_cursor": None}

    def test_search_filters_by_owner_for_non_admin(self, client):
        """Non-admin users only see their own memories in search results."""
        from unittest.mock import MagicMock

        from hive.api import memories as memories_mod
        from hive.api.main import app
        from hive.models import Memory

        tc, storage, _ = client
        other_mem = Memory(
            key="other-k", value="v", owner_client_id="other", owner_user_id="other-user"
        )
        storage.put_memory(other_mem)
        own_mem = Memory(
            key="own-k", value="v", owner_client_id=_TEST_USER_ID, owner_user_id=_TEST_USER_ID
        )
        storage.put_memory(own_mem)

        mock_vs = MagicMock()
        mock_vs.search.return_value = [(other_mem.memory_id, 0.9), (own_mem.memory_id, 0.8)]
        app.dependency_overrides[memories_mod._vector_store] = lambda: mock_vs

        resp = tc.get("/api/memories", params={"search": "q"})

        del app.dependency_overrides[memories_mod._vector_store]
        assert resp.status_code == 200
        keys = [i["key"] for i in resp.json()["items"]]
        assert "own-k" in keys
        assert "other-k" not in keys


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

    def test_get_stats_admin_sees_all(self, admin_client):
        """Admin role passes owner_user_id=None so all items are counted."""
        tc, *_ = admin_client
        resp = tc.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_memories" in data
        assert "total_users" in data
        assert isinstance(data["total_users"], int)

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
# User endpoints
# ---------------------------------------------------------------------------


class TestUsers:
    def test_get_me_returns_current_user(self, client):
        tc, storage, user_id = client
        resp = tc.get("/api/users/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == user_id
        assert data["email"] == "user@example.com"
        assert data["role"] == "user"

    def test_get_me_user_not_in_storage_returns_404(self, client):
        tc, storage, user_id = client
        storage.delete_user(user_id)
        resp = tc.get("/api/users/me")
        assert resp.status_code == 404

    def test_list_users_admin_only(self, admin_client):
        tc, storage, admin_id = admin_client
        # seed a second user
        from hive.models import User

        u2 = User(email="other@example.com", display_name="Other")
        storage.put_user(u2)

        resp = tc.get("/api/users")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 2
        assert "items" in data

    def test_list_users_non_admin_returns_403(self, client):
        tc, *_ = client
        resp = tc.get("/api/users")
        assert resp.status_code == 403

    def test_delete_user_admin(self, admin_client):
        tc, storage, _ = admin_client
        from hive.models import User

        u = User(email="todelete@example.com", display_name="Gone")
        storage.put_user(u)
        resp = tc.delete(f"/api/users/{u.user_id}")
        assert resp.status_code == 204
        assert storage.get_user_by_id(u.user_id) is None

    def test_delete_user_not_found_returns_404(self, admin_client):
        tc, *_ = admin_client
        resp = tc.delete("/api/users/no-such-user")
        assert resp.status_code == 404

    def test_delete_user_non_admin_returns_403(self, client):
        tc, *_ = client
        resp = tc.delete(f"/api/users/{_TEST_USER_ID}")
        assert resp.status_code == 403


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
# Memory upsert oversized → 413 (covers memories.py upsert path)
# ---------------------------------------------------------------------------


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
# require_token / require_mgmt_user direct function tests
# ---------------------------------------------------------------------------


class TestRequireTokenPath:
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

    def test_valid_mgmt_jwt_reaches_endpoint(self):
        """Covers _auth.py require_mgmt_user — valid mgmt JWT reaches endpoint."""
        from hive.auth.tokens import issue_mgmt_jwt
        from hive.models import User
        from hive.storage import HiveStorage

        old_table = os.environ.get("HIVE_TABLE_NAME")
        os.environ["HIVE_TABLE_NAME"] = "hive-unit-api"
        try:
            with mock_aws():
                _create_table()
                storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
                user = User(email="mgmt@example.com", display_name="Mgmt User")
                storage.put_user(user)
                mgmt_jwt = issue_mgmt_jwt(user)

                from hive.api.main import app

                app.dependency_overrides.clear()
                tc = TestClient(app, raise_server_exceptions=False)
                resp = tc.get("/api/memories", headers={"Authorization": f"Bearer {mgmt_jwt}"})
                assert resp.status_code == 200
        finally:
            if old_table is not None:
                os.environ["HIVE_TABLE_NAME"] = old_table
            else:
                os.environ.pop("HIVE_TABLE_NAME", None)

    async def test_require_admin_non_admin_raises_403(self):
        """Covers _auth.py require_admin — non-admin role raises 403."""
        from fastapi import HTTPException

        from hive.api._auth import require_admin

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(claims={"sub": "u1", "role": "user"})
        assert exc_info.value.status_code == 403

    async def test_require_admin_admin_role_passes(self):
        """Covers _auth.py require_admin — admin role returns claims."""
        from hive.api._auth import require_admin

        claims = {"sub": "u1", "role": "admin"}
        result = require_admin(claims=claims)
        assert result == claims


# ---------------------------------------------------------------------------
# Multi-tenant access: ownership enforcement
# ---------------------------------------------------------------------------


class TestMultiTenantAccess:
    def test_non_admin_cannot_read_other_users_memory(self):
        """Non-admin user gets 404 trying to read another user's memory."""
        with mock_aws():
            _create_table()
            from hive.api import _auth as auth_mod
            from hive.api import memories as memories_mod
            from hive.api.main import app
            from hive.models import Memory, User
            from hive.storage import HiveStorage

            storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
            # Create two users
            owner = User(email="owner@example.com", display_name="Owner")
            caller = User(email="caller@example.com", display_name="Caller")
            storage.put_user(owner)
            storage.put_user(caller)

            # Owner's memory
            mem = Memory(
                key="secret",
                value="private",
                owner_user_id=owner.user_id,
                owner_client_id=owner.user_id,
            )
            storage.put_memory(mem)

            # Caller's claims
            caller_claims = {
                "sub": caller.user_id,
                "role": "user",
                "email": "caller@example.com",
            }
            app.dependency_overrides[auth_mod.require_mgmt_user] = lambda: caller_claims
            app.dependency_overrides[memories_mod._storage] = lambda: storage

            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.get(f"/api/memories/{mem.memory_id}")
            app.dependency_overrides.clear()
            assert resp.status_code == 404

    def test_admin_can_read_any_users_memory(self):
        """Admin user can read another user's memory."""
        with mock_aws():
            _create_table()
            from hive.api import _auth as auth_mod
            from hive.api import memories as memories_mod
            from hive.api.main import app
            from hive.models import Memory, User
            from hive.storage import HiveStorage

            storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
            owner = User(email="owner2@example.com", display_name="Owner2")
            admin = User(email="admin2@example.com", display_name="Admin2", role="admin")
            storage.put_user(owner)
            storage.put_user(admin)

            mem = Memory(
                key="admin-test",
                value="data",
                owner_user_id=owner.user_id,
                owner_client_id=owner.user_id,
            )
            storage.put_memory(mem)

            admin_claims = {
                "sub": admin.user_id,
                "role": "admin",
                "email": "admin2@example.com",
            }
            app.dependency_overrides[auth_mod.require_mgmt_user] = lambda: admin_claims
            app.dependency_overrides[memories_mod._storage] = lambda: storage

            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.get(f"/api/memories/{mem.memory_id}")
            app.dependency_overrides.clear()
            assert resp.status_code == 200

    def test_non_admin_cannot_overwrite_other_users_memory(self):
        """Non-admin POST with existing key owned by another user returns 404."""
        with mock_aws():
            _create_table()
            from hive.api import _auth as auth_mod
            from hive.api import memories as memories_mod
            from hive.api.main import app
            from hive.models import Memory, User
            from hive.storage import HiveStorage

            storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
            owner = User(email="owner3@example.com", display_name="Owner3")
            caller = User(email="caller3@example.com", display_name="Caller3")
            storage.put_user(owner)
            storage.put_user(caller)

            mem = Memory(
                key="owned-key",
                value="original",
                owner_user_id=owner.user_id,
                owner_client_id=owner.user_id,
            )
            storage.put_memory(mem)

            caller_claims = {
                "sub": caller.user_id,
                "role": "user",
                "email": "caller3@example.com",
            }
            app.dependency_overrides[auth_mod.require_mgmt_user] = lambda: caller_claims
            app.dependency_overrides[memories_mod._storage] = lambda: storage

            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.post("/api/memories", json={"key": "owned-key", "value": "steal"})
            app.dependency_overrides.clear()
            assert resp.status_code == 404

    def _make_owned_memory(self, storage, owner_user_id):
        from hive.models import Memory

        mem = Memory(
            key=f"mem-{owner_user_id[:8]}",
            value="data",
            owner_user_id=owner_user_id,
            owner_client_id=owner_user_id,
        )
        storage.put_memory(mem)
        return mem

    def _make_owned_client(self, storage, owner_user_id):
        from hive.models import OAuthClient

        c = OAuthClient(client_name="Owned Client", owner_user_id=owner_user_id)
        storage.put_client(c)
        return c

    def _caller_setup(self, storage):
        from hive.models import User

        owner = User(email="own@example.com", display_name="Owner")
        caller = User(email="call@example.com", display_name="Caller")
        storage.put_user(owner)
        storage.put_user(caller)
        caller_claims = {"sub": caller.user_id, "role": "user", "email": "call@example.com"}
        return owner, caller_claims

    def test_non_admin_cannot_update_other_users_memory(self):
        """PATCH memory owned by another user returns 404 (covers memories.py:154)."""
        with mock_aws():
            _create_table()
            from hive.api import _auth as auth_mod
            from hive.api import memories as memories_mod
            from hive.api.main import app
            from hive.storage import HiveStorage

            storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
            owner, caller_claims = self._caller_setup(storage)
            mem = self._make_owned_memory(storage, owner.user_id)

            app.dependency_overrides[auth_mod.require_mgmt_user] = lambda: caller_claims
            app.dependency_overrides[memories_mod._storage] = lambda: storage

            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.patch(f"/api/memories/{mem.memory_id}", json={"value": "new"})
            app.dependency_overrides.clear()
            assert resp.status_code == 404

    def test_non_admin_cannot_delete_other_users_memory(self):
        """DELETE memory owned by another user returns 404 (covers memories.py:187)."""
        with mock_aws():
            _create_table()
            from hive.api import _auth as auth_mod
            from hive.api import memories as memories_mod
            from hive.api.main import app
            from hive.storage import HiveStorage

            storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
            owner, caller_claims = self._caller_setup(storage)
            mem = self._make_owned_memory(storage, owner.user_id)

            app.dependency_overrides[auth_mod.require_mgmt_user] = lambda: caller_claims
            app.dependency_overrides[memories_mod._storage] = lambda: storage

            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.delete(f"/api/memories/{mem.memory_id}")
            app.dependency_overrides.clear()
            assert resp.status_code == 404

    def test_non_admin_cannot_read_other_users_client(self):
        """GET client owned by another user returns 404 (covers clients.py:98)."""
        with mock_aws():
            _create_table()
            from hive.api import _auth as auth_mod
            from hive.api import clients as clients_mod
            from hive.api.main import app
            from hive.storage import HiveStorage

            storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
            owner, caller_claims = self._caller_setup(storage)
            c = self._make_owned_client(storage, owner.user_id)

            app.dependency_overrides[auth_mod.require_mgmt_user] = lambda: caller_claims
            app.dependency_overrides[clients_mod._storage] = lambda: storage

            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.get(f"/api/clients/{c.client_id}")
            app.dependency_overrides.clear()
            assert resp.status_code == 404

    def test_non_admin_cannot_delete_other_users_client(self):
        """DELETE client owned by another user returns 404 (covers clients.py:113)."""
        with mock_aws():
            _create_table()
            from hive.api import _auth as auth_mod
            from hive.api import clients as clients_mod
            from hive.api.main import app
            from hive.storage import HiveStorage

            storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
            owner, caller_claims = self._caller_setup(storage)
            c = self._make_owned_client(storage, owner.user_id)

            app.dependency_overrides[auth_mod.require_mgmt_user] = lambda: caller_claims
            app.dependency_overrides[clients_mod._storage] = lambda: storage

            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.delete(f"/api/clients/{c.client_id}")
            app.dependency_overrides.clear()
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# require_scope direct tests and _storage() dep coverage
# ---------------------------------------------------------------------------


class TestRequireScope:
    async def test_valid_token_with_correct_scope_passes(self):
        """Covers _auth.py require_scope._dep success path (lines 50, 55)."""
        from datetime import datetime, timedelta, timezone

        from fastapi.security import HTTPAuthorizationCredentials

        from hive.api._auth import require_scope
        from hive.auth.tokens import issue_jwt
        from hive.models import OAuthClient, Token
        from hive.storage import HiveStorage

        old_table = os.environ.get("HIVE_TABLE_NAME")
        os.environ["HIVE_TABLE_NAME"] = "hive-unit-api"
        try:
            with mock_aws():
                _create_table()
                storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
                oauth_client = OAuthClient(client_name="Scope Test")
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
                dep = require_scope("memories:read")
                result_storage, result_client_id = await dep(credentials=creds, storage=storage)
                assert result_client_id == oauth_client.client_id
        finally:
            if old_table is not None:
                os.environ["HIVE_TABLE_NAME"] = old_table
            else:
                os.environ.pop("HIVE_TABLE_NAME", None)

    async def test_valid_token_insufficient_scope_raises_403(self):
        """Covers _auth.py require_scope._dep scope-check failure path (lines 50-54)."""
        from datetime import datetime, timedelta, timezone

        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        from hive.api._auth import require_scope
        from hive.auth.tokens import issue_jwt
        from hive.models import OAuthClient, Token
        from hive.storage import HiveStorage

        old_table = os.environ.get("HIVE_TABLE_NAME")
        os.environ["HIVE_TABLE_NAME"] = "hive-unit-api"
        try:
            with mock_aws():
                _create_table()
                storage = HiveStorage(table_name="hive-unit-api", region="us-east-1")
                oauth_client = OAuthClient(client_name="Limited Scope")
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
                dep = require_scope("memories:write")
                with pytest.raises(HTTPException) as exc_info:
                    await dep(credentials=creds, storage=storage)
                assert exc_info.value.status_code == 403
        finally:
            if old_table is not None:
                os.environ["HIVE_TABLE_NAME"] = old_table
            else:
                os.environ.pop("HIVE_TABLE_NAME", None)

    async def test_invalid_token_raises_401(self):
        """Covers _auth.py require_scope._dep invalid-token path (lines 45-49)."""
        from unittest.mock import MagicMock

        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        from hive.api._auth import require_scope

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad-token")
        storage = MagicMock()
        dep = require_scope("memories:read")
        with pytest.raises(HTTPException) as exc_info:
            await dep(credentials=creds, storage=storage)
        assert exc_info.value.status_code == 401

    def test_get_storage_dep_returns_hive_storage(self):
        """Covers _auth.py:19 — _get_storage() return statement."""
        with mock_aws():
            _create_table()
            from hive.api._auth import _get_storage

            result = _get_storage()
            assert result is not None

    def test_module_storage_deps_return_hive_storage(self):
        """Covers _storage() in clients, stats, users modules."""
        with mock_aws():
            _create_table()
            from hive.api.clients import _storage as clients_storage
            from hive.api.stats import _storage as stats_storage
            from hive.api.users import _storage as users_storage

            assert clients_storage() is not None
            assert stats_storage() is not None
            assert users_storage() is not None


# ---------------------------------------------------------------------------
# X-Origin-Verify middleware
# ---------------------------------------------------------------------------


class TestOriginVerifyMiddleware:
    def test_returns_403_when_secret_set_and_header_missing(self):
        """_verify_origin_secret returns 403 when expected secret is active and header absent."""
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from hive.api.main import app

        with patch("hive.auth.tokens._origin_verify_secret", return_value="real-secret"):
            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.get("/health")
        assert resp.status_code == 403

    def test_passes_through_when_header_correct(self):
        """_verify_origin_secret allows request when X-Origin-Verify matches."""
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from hive.api.main import app

        with patch("hive.auth.tokens._origin_verify_secret", return_value="real-secret"):
            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.get("/health", headers={"x-origin-verify": "real-secret"})
        assert resp.status_code == 200

    def test_passes_through_when_placeholder_secret(self):
        """Check is disabled when secret is the placeholder value."""
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from hive.api.main import app

        with patch(
            "hive.auth.tokens._origin_verify_secret", return_value="CHANGE_ME_ON_FIRST_DEPLOY"
        ):
            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.get("/health")
        assert resp.status_code == 200
