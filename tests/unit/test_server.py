# Copyright (c) 2026 John Carter. All rights reserved.
"""
Unit tests for the Hive MCP server tools (server.py).

Uses moto to mock DynamoDB and a fake FastMCP Context whose
request_context.meta carries the Bearer token — matching the fallback
path in _auth() used by integration tests and direct tool invocation.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("HIVE_TABLE_NAME", "hive-unit-server")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("HIVE_JWT_SECRET", "unit-test-secret")
os.environ.pop("DYNAMODB_ENDPOINT", None)


def _create_table(table_name: str = "hive-unit-server") -> None:
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


def _make_ctx(jwt: str) -> MagicMock:
    """Build a minimal mock Context that passes token via meta."""
    ctx = MagicMock()
    ctx.request_context.meta = {"Authorization": f"Bearer {jwt}"}
    return ctx


@pytest.fixture()
def server_env():
    """moto-backed storage + valid JWT for MCP tool tests."""
    with mock_aws():
        _create_table()
        # Override HIVE_TABLE_NAME for the duration of this fixture so that
        # HiveStorage() calls inside server._auth() use the right moto table.
        old_table = os.environ.get("HIVE_TABLE_NAME")
        os.environ["HIVE_TABLE_NAME"] = "hive-unit-server"
        try:
            from hive.auth.tokens import issue_jwt
            from hive.models import OAuthClient, Token
            from hive.storage import HiveStorage

            storage = HiveStorage(table_name="hive-unit-server", region="us-east-1")
            client = OAuthClient(client_name="MCP Test Client")
            storage.put_client(client)

            now = datetime.now(timezone.utc)
            token = Token(
                client_id=client.client_id,
                scope="memories:read memories:write",
                issued_at=now,
                expires_at=now + timedelta(hours=1),
            )
            storage.put_token(token)
            jwt = issue_jwt(token)

            yield storage, client.client_id, jwt
        finally:
            if old_table is not None:
                os.environ["HIVE_TABLE_NAME"] = old_table
            else:
                os.environ.pop("HIVE_TABLE_NAME", None)


# ---------------------------------------------------------------------------
# remember
# ---------------------------------------------------------------------------


class TestRemember:
    async def test_store_new_memory(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import remember

        result = await remember("my-key", "my-value", ["tag1"], ctx=_make_ctx(jwt))
        assert result == "Stored memory 'my-key'."
        assert storage.get_memory_by_key("my-key") is not None

    async def test_update_existing_memory(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import remember

        await remember("upd-key", "original", [], ctx=_make_ctx(jwt))
        result = await remember("upd-key", "updated", ["new-tag"], ctx=_make_ctx(jwt))
        assert result == "Updated memory 'upd-key'."
        m = storage.get_memory_by_key("upd-key")
        assert m is not None
        assert m.value == "updated"

    async def test_idempotent_no_change(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import remember

        await remember("same-key", "same-value", ["t"], ctx=_make_ctx(jwt))
        result = await remember("same-key", "same-value", ["t"], ctx=_make_ctx(jwt))
        assert result == "Memory 'same-key' unchanged."

    async def test_missing_auth_raises_tool_error(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import remember

        ctx = MagicMock()
        ctx.request_context.meta = {}
        with pytest.raises(ToolError, match="Unauthorized"):
            await remember("k", "v", [], ctx=ctx)

    async def test_oversized_value_raises_tool_error(self, server_env):
        from unittest.mock import patch

        from fastmcp.exceptions import ToolError

        from hive.server import remember

        storage, client_id, jwt = server_env
        with (
            patch.object(storage.__class__, "get_memory_by_key", return_value=None),
            patch.object(
                storage.__class__, "put_memory", side_effect=ValueError("Memory value is too large")
            ),
            pytest.raises(ToolError, match="too large"),
        ):
            await remember("big-key", "x" * 1000, [], ctx=_make_ctx(jwt))


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------


class TestRecall:
    async def test_recall_existing(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import recall, remember

        await remember("rec-key", "the-value", [], ctx=_make_ctx(jwt))
        result = await recall("rec-key", ctx=_make_ctx(jwt))
        assert result == "the-value"

    async def test_recall_nonexistent_raises(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import recall

        _, _, jwt = server_env
        with pytest.raises(ToolError, match="No memory found"):
            await recall("no-such-key", ctx=_make_ctx(jwt))


# ---------------------------------------------------------------------------
# forget
# ---------------------------------------------------------------------------


class TestForget:
    async def test_forget_existing(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import forget, remember

        await remember("del-key", "v", [], ctx=_make_ctx(jwt))
        result = await forget("del-key", ctx=_make_ctx(jwt))
        assert result == "Deleted memory 'del-key'."
        assert storage.get_memory_by_key("del-key") is None

    async def test_forget_nonexistent_raises(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import forget

        _, _, jwt = server_env
        with pytest.raises(ToolError, match="No memory found"):
            await forget("no-such-key", ctx=_make_ctx(jwt))


# ---------------------------------------------------------------------------
# list_memories
# ---------------------------------------------------------------------------


class TestListMemories:
    async def test_list_by_tag(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import list_memories, remember

        await remember("lst-a", "v1", ["alpha"], ctx=_make_ctx(jwt))
        await remember("lst-b", "v2", ["beta"], ctx=_make_ctx(jwt))
        result = await list_memories("alpha", ctx=_make_ctx(jwt))
        assert "items" in result and "has_more" in result
        keys = [m["key"] for m in result["items"]]
        assert "lst-a" in keys
        assert "lst-b" not in keys

    async def test_list_empty_tag_returns_empty(self, server_env):
        _, _, jwt = server_env
        from hive.server import list_memories

        result = await list_memories("nonexistent-tag", ctx=_make_ctx(jwt))
        assert result["items"] == []
        assert result["has_more"] is False


# ---------------------------------------------------------------------------
# summarize_context
# ---------------------------------------------------------------------------


class TestSummarizeContext:
    async def test_summarize_with_memories(self, server_env):
        _, _, jwt = server_env
        from hive.server import remember, summarize_context

        await remember("sum-a", "detail about foo", ["foo"], ctx=_make_ctx(jwt))
        await remember("sum-b", "more about foo", ["foo"], ctx=_make_ctx(jwt))
        result = await summarize_context("foo", ctx=_make_ctx(jwt))
        assert "foo" in result
        assert "sum-a" in result or "detail about foo" in result

    async def test_summarize_no_memories(self, server_env):
        _, _, jwt = server_env
        from hive.server import summarize_context

        result = await summarize_context("nonexistent-topic", ctx=_make_ctx(jwt))
        assert "No memories found" in result


# ---------------------------------------------------------------------------
# _app_version() branches — covers server.py:39 and 42-43
# ---------------------------------------------------------------------------


class TestServerAppVersion:
    def test_returns_env_var_when_set(self):
        """Covers server.py line where APP_VERSION env var is returned."""
        from unittest.mock import patch

        from hive.server import _app_version

        with patch.dict(os.environ, {"APP_VERSION": "1.2.3"}):
            assert _app_version() == "1.2.3"

    def test_returns_dev_when_package_not_found(self):
        """Covers server.py PackageNotFoundError fallback to 'dev'."""
        import importlib.metadata
        from unittest.mock import patch

        from hive.server import _app_version

        env = {k: v for k, v in os.environ.items() if k != "APP_VERSION"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch(
                "hive.server.importlib.metadata.version",
                side_effect=importlib.metadata.PackageNotFoundError,
            ),
        ):
            assert _app_version() == "dev"


# ---------------------------------------------------------------------------
# HTTP request path in _auth() — covers server.py:75-77
# ---------------------------------------------------------------------------


class TestAuthHttpPath:
    async def test_auth_reads_token_from_http_request(self, server_env):
        """When get_http_request() succeeds, auth header is read from it."""
        from unittest.mock import patch

        from hive.server import remember

        storage, client_id, jwt = server_env

        mock_request = MagicMock()
        mock_request.headers.get.side_effect = lambda key, *args: {
            "authorization": f"bearer {jwt}",
            "x-amzn-requestid": "test-req-123",
            "x-request-id": None,
        }.get(key.lower())

        # ctx has no meta so the HTTP path must succeed
        ctx = MagicMock()
        ctx.request_context = None

        with patch("hive.server.get_http_request", return_value=mock_request):
            result = await remember("http-path-key", "value", [], ctx=ctx)
        assert "http-path-key" in result


# ---------------------------------------------------------------------------
# update existing memory raises ValueError → ToolError — covers server.py:136-137
# ---------------------------------------------------------------------------


class TestRememberUpdateError:
    async def test_update_existing_oversized_raises_tool_error(self, server_env):
        """Covers the ValueError → ToolError path when updating an existing memory."""
        from unittest.mock import patch

        from fastmcp.exceptions import ToolError

        from hive.server import remember

        storage, client_id, jwt = server_env
        # Store memory first
        await remember("upd-err-key", "original", [], ctx=_make_ctx(jwt))

        with (
            patch.object(storage.__class__, "put_memory", side_effect=ValueError("too large")),
            pytest.raises(ToolError, match="too large"),
        ):
            await remember("upd-err-key", "updated-value", [], ctx=_make_ctx(jwt))


# ---------------------------------------------------------------------------
# list_memories with pagination cursor — covers server.py:288
# ---------------------------------------------------------------------------


class TestListMemoriesPagination:
    async def test_list_returns_next_cursor(self, server_env):
        """Covers server.py line that adds next_cursor to result dict."""
        from hive.server import list_memories, remember

        storage, client_id, jwt = server_env
        ctx = _make_ctx(jwt)
        # Store 3 memories with the same tag
        for i in range(3):
            await remember(f"pg-key-{i}", f"val-{i}", ["pagtest"], ctx=ctx)

        result = await list_memories("pagtest", limit=1, ctx=ctx)
        assert result["has_more"] is True
        assert "next_cursor" in result


# ---------------------------------------------------------------------------
# MCP tool scope enforcement — covers server.py _auth() required_scope check
# ---------------------------------------------------------------------------


def _make_limited_scope_jwt(storage, scope: str) -> str:
    """Issue a JWT with a restricted scope and store it in `storage`."""
    from hive.auth.tokens import issue_jwt
    from hive.models import OAuthClient, Token

    client = OAuthClient(client_name=f"Scope Test {scope}")
    storage.put_client(client)
    now = datetime.now(timezone.utc)
    token = Token(
        client_id=client.client_id,
        scope=scope,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    storage.put_token(token)
    return issue_jwt(token)


class TestMcpToolScopeEnforcement:
    async def test_remember_requires_write_scope(self, server_env):
        """remember() raises ToolError when token only has memories:read."""
        from fastmcp.exceptions import ToolError

        from hive.server import remember

        storage, _, _ = server_env
        read_only_jwt = _make_limited_scope_jwt(storage, "memories:read")
        with pytest.raises(ToolError, match="Insufficient scope"):
            await remember("scope-k", "v", [], ctx=_make_ctx(read_only_jwt))

    async def test_recall_requires_read_scope(self, server_env):
        """recall() raises ToolError when token only has memories:write."""
        from fastmcp.exceptions import ToolError

        from hive.server import recall

        storage, _, _ = server_env
        write_only_jwt = _make_limited_scope_jwt(storage, "memories:write")
        with pytest.raises(ToolError, match="Insufficient scope"):
            await recall("any-key", ctx=_make_ctx(write_only_jwt))

    async def test_forget_requires_write_scope(self, server_env):
        """forget() raises ToolError when token only has memories:read."""
        from fastmcp.exceptions import ToolError

        from hive.server import forget

        storage, _, _ = server_env
        read_only_jwt = _make_limited_scope_jwt(storage, "memories:read")
        with pytest.raises(ToolError, match="Insufficient scope"):
            await forget("any-key", ctx=_make_ctx(read_only_jwt))

    async def test_list_memories_requires_read_scope(self, server_env):
        """list_memories() raises ToolError when token only has memories:write."""
        from fastmcp.exceptions import ToolError

        from hive.server import list_memories

        storage, _, _ = server_env
        write_only_jwt = _make_limited_scope_jwt(storage, "memories:write")
        with pytest.raises(ToolError, match="Insufficient scope"):
            await list_memories("any-tag", ctx=_make_ctx(write_only_jwt))

    async def test_summarize_context_requires_read_scope(self, server_env):
        """summarize_context() raises ToolError when token only has memories:write."""
        from fastmcp.exceptions import ToolError

        from hive.server import summarize_context

        storage, _, _ = server_env
        write_only_jwt = _make_limited_scope_jwt(storage, "memories:write")
        with pytest.raises(ToolError, match="Insufficient scope"):
            await summarize_context("any-topic", ctx=_make_ctx(write_only_jwt))


# ---------------------------------------------------------------------------
# _OriginVerifyMiddleware
# ---------------------------------------------------------------------------


class TestOriginVerifyMiddleware:
    def _make_app(self):
        """Build a minimal Starlette app wrapped with _OriginVerifyMiddleware."""
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        from hive.server import _OriginVerifyMiddleware

        async def homepage(request: Request):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(_OriginVerifyMiddleware)
        return app

    def test_returns_403_when_secret_set_and_header_missing(self):
        """Middleware rejects requests without the X-Origin-Verify header."""
        from unittest.mock import patch

        from starlette.testclient import TestClient

        app = self._make_app()
        with patch("hive.server._origin_verify_secret", return_value="real-secret"):
            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.get("/")
        assert resp.status_code == 403

    def test_passes_through_when_header_correct(self):
        """Middleware allows requests that supply the correct X-Origin-Verify header."""
        from unittest.mock import patch

        from starlette.testclient import TestClient

        app = self._make_app()
        with patch("hive.server._origin_verify_secret", return_value="real-secret"):
            tc = TestClient(app, raise_server_exceptions=False)
            resp = tc.get("/", headers={"x-origin-verify": "real-secret"})
        assert resp.status_code == 200
