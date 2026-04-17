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
# ping
# ---------------------------------------------------------------------------


class TestPing:
    async def test_returns_ok_for_valid_token(self, server_env):
        _, _, jwt = server_env
        from hive.server import ping

        result = await ping(ctx=_make_ctx(jwt))
        assert result == "ok"

    async def test_missing_auth_raises_tool_error(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import ping

        ctx = MagicMock()
        ctx.request_context.meta = {}
        with pytest.raises(ToolError, match="Unauthorized"):
            await ping(ctx=ctx)


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

    async def test_auth_via_pydantic_meta_model(self, server_env):
        """The Pydantic Meta model path (model_extra) is exercised by production
        FastMCP; verify it works alongside the plain-dict path used in tests."""
        from mcp.types import RequestParams

        from hive.server import remember

        _, _, jwt = server_env
        meta = RequestParams.Meta.model_validate({"Authorization": f"Bearer {jwt}"})
        ctx = MagicMock()
        ctx.request_context.meta = meta
        result = await remember("pydantic-meta-key", "v", [], ctx=ctx)
        assert result == "Stored memory 'pydantic-meta-key'."

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

    async def test_value_at_limit_succeeds(self, server_env):
        from hive.server import DEFAULT_MAX_VALUE_BYTES, remember

        storage, _, jwt = server_env
        value = "x" * DEFAULT_MAX_VALUE_BYTES
        result = await remember("at-limit-key", value, [], ctx=_make_ctx(jwt))
        assert result == "Stored memory 'at-limit-key'."

    async def test_value_over_limit_raises_tool_error(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import DEFAULT_MAX_VALUE_BYTES, remember

        _, _, jwt = server_env
        actual = DEFAULT_MAX_VALUE_BYTES + 1
        expected = f"Value exceeds maximum size of {DEFAULT_MAX_VALUE_BYTES} bytes ({actual} bytes provided)"
        with pytest.raises(ToolError) as exc_info:
            await remember("over-limit-key", "x" * actual, [], ctx=_make_ctx(jwt))
        assert str(exc_info.value) == expected

    async def test_value_size_counts_utf8_bytes_not_chars(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import remember

        _, _, jwt = server_env
        # "€" is 3 bytes in UTF-8, so 5 chars = 15 bytes — exceeds 10 byte limit
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("HIVE_MAX_VALUE_BYTES", "10")
            with pytest.raises(ToolError, match="15 bytes provided"):
                await remember("euro-key", "€€€€€", [], ctx=_make_ctx(jwt))

    async def test_value_size_limit_env_override(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import remember

        _, _, jwt = server_env
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("HIVE_MAX_VALUE_BYTES", "5")
            with pytest.raises(ToolError, match="maximum size of 5 bytes"):
                await remember("custom-limit-key", "x" * 6, [], ctx=_make_ctx(jwt))
            # within the override limit is fine
            result = await remember("within-key", "x" * 5, [], ctx=_make_ctx(jwt))
            assert result == "Stored memory 'within-key'."

    async def test_remember_with_ttl_sets_expires_at(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import remember

        result = await remember("ttl-key", "ttl-val", [], ttl_seconds=3600, ctx=_make_ctx(jwt))
        assert result == "Stored memory 'ttl-key'."
        m = storage.get_memory_by_key("ttl-key")
        assert m is not None
        assert m.expires_at is not None

    async def test_remember_without_ttl_no_expires_at(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import remember

        await remember("no-ttl-key", "v", [], ctx=_make_ctx(jwt))
        m = storage.get_memory_by_key("no-ttl-key")
        assert m is not None
        assert m.expires_at is None

    async def test_idempotent_with_same_ttl(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import remember

        await remember("idem-ttl", "v", [], ttl_seconds=3600, ctx=_make_ctx(jwt))
        m1 = storage.get_memory_by_key("idem-ttl")
        assert m1 is not None
        # Second call with same value but no ttl should NOT be idempotent
        result = await remember("idem-ttl", "v", [], ttl_seconds=None, ctx=_make_ctx(jwt))
        assert result == "Updated memory 'idem-ttl'."
        m2 = storage.get_memory_by_key("idem-ttl")
        assert m2 is not None
        assert m2.expires_at is None


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
        # Agent attribution is surfaced on every item.
        assert result["items"][0]["owner_client_id"] == client_id

    async def test_list_empty_tag_returns_empty(self, server_env):
        _, _, jwt = server_env
        from hive.server import list_memories

        result = await list_memories("nonexistent-tag", ctx=_make_ctx(jwt))
        assert result["items"] == []
        assert result["has_more"] is False


# ---------------------------------------------------------------------------
# list_tags
# ---------------------------------------------------------------------------


class TestListTags:
    async def test_returns_sorted_distinct_tags(self, server_env):
        _, _, jwt = server_env
        from hive.server import list_tags, remember

        ctx = _make_ctx(jwt)
        await remember("a", "1", ["zebra", "alpha"], ctx=ctx)
        await remember("b", "2", ["alpha", "mango"], ctx=ctx)
        await remember("c", "3", [], ctx=ctx)

        result = await list_tags(ctx=ctx)
        assert result == {"tags": ["alpha", "mango", "zebra"], "count": 3}

    async def test_empty_when_no_memories(self, server_env):
        _, _, jwt = server_env
        from hive.server import list_tags

        result = await list_tags(ctx=_make_ctx(jwt))
        assert result == {"tags": [], "count": 0}

    async def test_scoped_to_caller_client(self, server_env):
        storage, client_id, jwt = server_env
        from hive.models import Memory
        from hive.server import list_tags, remember

        await remember("mine", "v", ["owned"], ctx=_make_ctx(jwt))
        # Write a memory belonging to a different client directly so we bypass auth
        storage.put_memory(
            Memory(key="theirs", value="v", tags=["not-mine"], owner_client_id="other-client")
        )

        result = await list_tags(ctx=_make_ctx(jwt))
        assert result["tags"] == ["owned"]

    async def test_requires_read_scope(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import list_tags

        storage, _, _ = server_env
        write_only_jwt = _make_limited_scope_jwt(storage, "memories:write")
        with pytest.raises(ToolError, match="Insufficient scope"):
            await list_tags(ctx=_make_ctx(write_only_jwt))


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


# ---------------------------------------------------------------------------
# search_memories MCP tool
# ---------------------------------------------------------------------------


def _make_mock_vector_store(pairs: list[tuple[str, float]] | None = None):
    """Return a mock VectorStore that returns the given (memory_id, score) pairs."""
    from unittest.mock import MagicMock

    vs = MagicMock()
    vs.search.return_value = pairs or []
    return vs


class TestSearchMemories:
    async def test_returns_results_with_scores(self, server_env):
        from unittest.mock import patch

        from hive.server import remember, search_memories

        storage, client_id, jwt = server_env
        ctx = _make_ctx(jwt)
        await remember("search-key", "some searchable content", ["t"], ctx=ctx)

        m = storage.get_memory_by_key("search-key")
        mock_vs = _make_mock_vector_store([(m.memory_id, 0.88)])

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await search_memories("searchable content", top_k=5, ctx=ctx)

        assert result["count"] == 1
        assert result["query"] == "searchable content"
        item = result["items"][0]
        assert item["key"] == "search-key"
        assert item["score"] == 0.88
        assert item["owner_client_id"] == client_id

    async def test_returns_empty_when_no_index(self, server_env):
        from unittest.mock import patch

        from hive.server import search_memories
        from hive.vector_store import VectorIndexNotFoundError

        _, _, jwt = server_env
        mock_vs = MagicMock()
        mock_vs.search.side_effect = VectorIndexNotFoundError("no index")

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await search_memories("anything", ctx=_make_ctx(jwt))

        assert result == {"items": [], "count": 0, "query": "anything"}

    async def test_caps_top_k_at_50(self, server_env):
        from unittest.mock import patch

        from hive.server import search_memories

        _, _, jwt = server_env
        mock_vs = _make_mock_vector_store([])

        with patch("hive.server._vector_store", return_value=mock_vs):
            await search_memories("q", top_k=999, ctx=_make_ctx(jwt))

        mock_vs.search.assert_called_once()
        assert mock_vs.search.call_args.kwargs["top_k"] == 50

    async def test_requires_read_scope(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import search_memories

        storage, _, _ = server_env
        write_only_jwt = _make_limited_scope_jwt(storage, "memories:write")
        with pytest.raises(ToolError, match="Insufficient scope"):
            await search_memories("q", ctx=_make_ctx(write_only_jwt))

    async def test_min_score_filters_low_ranked_results(self, server_env):
        from unittest.mock import patch

        from hive.server import remember, search_memories

        storage, _, jwt = server_env
        ctx = _make_ctx(jwt)
        await remember("hi-key", "high match", ["t"], ctx=ctx)
        await remember("lo-key", "low match", ["t"], ctx=ctx)
        hi = storage.get_memory_by_key("hi-key")
        lo = storage.get_memory_by_key("lo-key")
        mock_vs = _make_mock_vector_store([(hi.memory_id, 0.9), (lo.memory_id, 0.3)])

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await search_memories("anything", min_score=0.5, ctx=ctx)

        assert result["count"] == 1
        assert [item["key"] for item in result["items"]] == ["hi-key"]

    async def test_min_score_none_returns_all(self, server_env):
        from unittest.mock import patch

        from hive.server import remember, search_memories

        storage, _, jwt = server_env
        ctx = _make_ctx(jwt)
        await remember("a", "a", ["t"], ctx=ctx)
        await remember("b", "b", ["t"], ctx=ctx)
        a = storage.get_memory_by_key("a")
        b = storage.get_memory_by_key("b")
        mock_vs = _make_mock_vector_store([(a.memory_id, 0.9), (b.memory_id, 0.05)])

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await search_memories("q", ctx=ctx)

        assert result["count"] == 2

    async def test_min_score_all_below_threshold_returns_empty(self, server_env):
        from unittest.mock import patch

        from hive.server import remember, search_memories

        storage, _, jwt = server_env
        ctx = _make_ctx(jwt)
        await remember("only-key", "v", ["t"], ctx=ctx)
        m = storage.get_memory_by_key("only-key")
        mock_vs = _make_mock_vector_store([(m.memory_id, 0.2)])

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await search_memories("q", min_score=0.9, ctx=ctx)

        assert result == {"items": [], "count": 0, "query": "q"}

    async def test_filter_tags_requires_all_tags(self, server_env):
        from unittest.mock import patch

        from hive.server import remember, search_memories

        storage, _, jwt = server_env
        ctx = _make_ctx(jwt)
        await remember("a", "alpha", ["x", "y"], ctx=ctx)
        await remember("b", "beta", ["x"], ctx=ctx)
        await remember("c", "gamma", ["y"], ctx=ctx)
        a = storage.get_memory_by_key("a")
        b = storage.get_memory_by_key("b")
        c = storage.get_memory_by_key("c")
        mock_vs = _make_mock_vector_store(
            [(a.memory_id, 0.9), (b.memory_id, 0.8), (c.memory_id, 0.7)]
        )

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await search_memories("q", filter_tags=["x", "y"], ctx=ctx)

        # Only "a" has both x and y
        assert [item["key"] for item in result["items"]] == ["a"]
        assert result["count"] == 1

    async def test_filter_tags_none_returns_all(self, server_env):
        from unittest.mock import patch

        from hive.server import remember, search_memories

        storage, _, jwt = server_env
        ctx = _make_ctx(jwt)
        await remember("a", "v", ["x"], ctx=ctx)
        a = storage.get_memory_by_key("a")
        mock_vs = _make_mock_vector_store([(a.memory_id, 0.9)])

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await search_memories("q", ctx=ctx)

        assert result["count"] == 1

    async def test_filter_tags_requests_wider_candidate_pool(self, server_env):
        from unittest.mock import patch

        from hive.server import search_memories

        _, _, jwt = server_env
        mock_vs = _make_mock_vector_store([])

        with patch("hive.server._vector_store", return_value=mock_vs):
            await search_memories("q", top_k=5, filter_tags=["x"], ctx=_make_ctx(jwt))

        # When filter_tags is set, the vector search asks for the cap (50) so
        # we can still return up to top_k matches after post-filtering.
        assert mock_vs.search.call_args.kwargs["top_k"] == 50

    async def test_filter_tags_trims_to_top_k_after_filter(self, server_env):
        from unittest.mock import patch

        from hive.server import remember, search_memories

        storage, _, jwt = server_env
        ctx = _make_ctx(jwt)
        for i in range(5):
            await remember(f"k{i}", f"v{i}", ["x"], ctx=ctx)
        mems = [storage.get_memory_by_key(f"k{i}") for i in range(5)]
        mock_vs = _make_mock_vector_store(
            [(m.memory_id, 0.9 - i * 0.1) for i, m in enumerate(mems)]
        )

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await search_memories("q", top_k=2, filter_tags=["x"], ctx=ctx)

        assert result["count"] == 2
        assert [item["key"] for item in result["items"]] == ["k0", "k1"]

    async def test_min_score_clamped_to_unit_interval(self, server_env):
        from unittest.mock import patch

        from hive.server import remember, search_memories

        storage, _, jwt = server_env
        ctx = _make_ctx(jwt)
        await remember("key", "v", ["t"], ctx=ctx)
        m = storage.get_memory_by_key("key")
        mock_vs = _make_mock_vector_store([(m.memory_id, 1.0)])

        # min_score > 1.0 gets clamped to 1.0; a perfect score still matches
        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await search_memories("q", min_score=5.0, ctx=ctx)

        assert result["count"] == 1

        # min_score < 0.0 gets clamped to 0.0; everything passes
        mock_vs2 = _make_mock_vector_store([(m.memory_id, 0.0)])
        with patch("hive.server._vector_store", return_value=mock_vs2):
            result = await search_memories("q", min_score=-1.0, ctx=ctx)

        assert result["count"] == 1

    async def test_remember_dual_writes_to_vector_store(self, server_env):
        """remember() calls upsert_memory on the VectorStore for new memories."""
        from unittest.mock import MagicMock, patch

        from hive.server import remember

        _, _, jwt = server_env
        mock_vs = MagicMock()

        with patch("hive.server._vector_store", return_value=mock_vs):
            await remember("dual-write-key", "value", ["tag"], ctx=_make_ctx(jwt))

        mock_vs.upsert_memory.assert_called_once()

    async def test_remember_dual_writes_on_update(self, server_env):
        """remember() calls upsert_memory on the VectorStore when updating."""
        from unittest.mock import MagicMock, patch

        from hive.server import remember

        _, _, jwt = server_env
        mock_vs = MagicMock()

        with patch("hive.server._vector_store", return_value=mock_vs):
            await remember("upd-dw-key", "original", [], ctx=_make_ctx(jwt))
            await remember("upd-dw-key", "updated", ["x"], ctx=_make_ctx(jwt))

        assert mock_vs.upsert_memory.call_count == 2

    async def test_forget_deletes_from_vector_store(self, server_env):
        """forget() calls delete_memory on the VectorStore."""
        from unittest.mock import MagicMock, patch

        from hive.server import forget, remember

        _, _, jwt = server_env
        mock_vs = MagicMock()

        with patch("hive.server._vector_store", return_value=mock_vs):
            await remember("forget-dw-key", "v", [], ctx=_make_ctx(jwt))
            await forget("forget-dw-key", ctx=_make_ctx(jwt))

        mock_vs.delete_memory.assert_called_once()

    async def test_remember_vector_upsert_failure_is_non_fatal(self, server_env):
        """VectorStore errors during remember() are logged but do not raise."""
        from unittest.mock import MagicMock, patch

        from hive.server import remember

        _, _, jwt = server_env
        mock_vs = MagicMock()
        mock_vs.upsert_memory.side_effect = RuntimeError("no bucket")

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await remember("vec-fail-new", "v", [], ctx=_make_ctx(jwt))

        assert "Stored" in result

    async def test_remember_vector_upsert_failure_on_update_is_non_fatal(self, server_env):
        """VectorStore errors during remember() update are logged but do not raise."""
        from unittest.mock import MagicMock, patch

        from hive.server import remember

        _, _, jwt = server_env
        mock_vs = MagicMock()

        with patch("hive.server._vector_store", return_value=mock_vs):
            await remember("vec-fail-upd", "original", [], ctx=_make_ctx(jwt))

        mock_vs.upsert_memory.side_effect = RuntimeError("no bucket")
        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await remember("vec-fail-upd", "updated", [], ctx=_make_ctx(jwt))

        assert "Updated" in result

    async def test_forget_vector_delete_failure_is_non_fatal(self, server_env):
        """VectorStore errors during forget() are logged but do not raise."""
        from unittest.mock import MagicMock, patch

        from hive.server import forget, remember

        _, _, jwt = server_env
        mock_vs = MagicMock()
        mock_vs.delete_memory.side_effect = RuntimeError("no bucket")

        with patch("hive.server._vector_store", return_value=mock_vs):
            await remember("vec-fail-forget", "v", [], ctx=_make_ctx(jwt))
            result = await forget("vec-fail-forget", ctx=_make_ctx(jwt))

        assert "Deleted" in result

    async def test_search_vector_failure_returns_empty(self, server_env):
        """Unexpected VectorStore errors during search_memories() return empty results."""
        from unittest.mock import patch

        from hive.server import search_memories

        _, _, jwt = server_env
        mock_vs = MagicMock()
        mock_vs.search.side_effect = RuntimeError("no bucket")

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await search_memories("anything", ctx=_make_ctx(jwt))

        assert result == {"items": [], "count": 0, "query": "anything"}


# ---------------------------------------------------------------------------
# forget_all
# ---------------------------------------------------------------------------


class TestForgetAll:
    async def test_forget_all_deletes_tagged_memories(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import forget_all, remember

        await remember("fa-a", "v1", ["purge"], ctx=_make_ctx(jwt))
        await remember("fa-b", "v2", ["purge"], ctx=_make_ctx(jwt))
        await remember("fa-c", "v3", ["keep"], ctx=_make_ctx(jwt))
        result = await forget_all("purge", ctx=_make_ctx(jwt))
        assert "2" in result
        assert storage.get_memory_by_key("fa-a") is None
        assert storage.get_memory_by_key("fa-b") is None
        assert storage.get_memory_by_key("fa-c") is not None

    async def test_forget_all_zero_when_tag_missing(self, server_env):
        _, _, jwt = server_env
        from hive.server import forget_all

        result = await forget_all("no-such-tag", ctx=_make_ctx(jwt))
        assert "0" in result

    async def test_forget_all_requires_write_scope(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import forget_all

        storage, _, _ = server_env
        read_only_jwt = _make_limited_scope_jwt(storage, "memories:read")
        with pytest.raises(ToolError, match="Insufficient scope"):
            await forget_all("t", ctx=_make_ctx(read_only_jwt))


# ---------------------------------------------------------------------------
# memory_history
# ---------------------------------------------------------------------------


class TestMemoryHistory:
    async def test_memory_history_returns_versions(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import memory_history, remember

        await remember("hist-k", "v1", [], ctx=_make_ctx(jwt))
        await remember("hist-k", "v2", [], ctx=_make_ctx(jwt))
        result = await memory_history("hist-k", ctx=_make_ctx(jwt))
        assert len(result) == 1
        assert result[0]["value"] == "v1"

    async def test_memory_history_empty_for_new_memory(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import memory_history, remember

        await remember("new-hist", "v1", [], ctx=_make_ctx(jwt))
        result = await memory_history("new-hist", ctx=_make_ctx(jwt))
        assert result == []

    async def test_memory_history_raises_for_missing_key(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import memory_history

        _, _, jwt = server_env
        with pytest.raises(ToolError, match="No memory found"):
            await memory_history("no-such-key", ctx=_make_ctx(jwt))

    async def test_memory_history_requires_read_scope(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import memory_history

        storage, _, _ = server_env
        write_only_jwt = _make_limited_scope_jwt(storage, "memories:write")
        with pytest.raises(ToolError, match="Insufficient scope"):
            await memory_history("k", ctx=_make_ctx(write_only_jwt))


# ---------------------------------------------------------------------------
# restore_memory
# ---------------------------------------------------------------------------


class TestRestoreMemory:
    async def test_restore_memory_reverts_value(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import memory_history, remember, restore_memory

        await remember("rst-k", "v1", [], ctx=_make_ctx(jwt))
        await remember("rst-k", "v2", [], ctx=_make_ctx(jwt))
        versions = await memory_history("rst-k", ctx=_make_ctx(jwt))
        vts = versions[0]["version_timestamp"]
        result = await restore_memory("rst-k", vts, ctx=_make_ctx(jwt))
        assert "rst-k" in result
        m = storage.get_memory_by_key("rst-k")
        assert m is not None
        assert m.value == "v1"

    async def test_restore_memory_raises_for_missing_key(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import restore_memory

        _, _, jwt = server_env
        with pytest.raises(ToolError, match="No memory found"):
            await restore_memory("no-such-key", "ts", ctx=_make_ctx(jwt))

    async def test_restore_memory_raises_for_missing_version(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import remember, restore_memory

        _, _, jwt = server_env
        await remember("rv-k", "v", [], ctx=_make_ctx(jwt))
        with pytest.raises(ToolError, match="not found"):
            await restore_memory("rv-k", "bad-ts", ctx=_make_ctx(jwt))

    async def test_restore_memory_requires_write_scope(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import restore_memory

        storage, _, _ = server_env
        read_only_jwt = _make_limited_scope_jwt(storage, "memories:read")
        with pytest.raises(ToolError, match="Insufficient scope"):
            await restore_memory("k", "ts", ctx=_make_ctx(read_only_jwt))


# ---------------------------------------------------------------------------
# HiveTokenVerifier
# ---------------------------------------------------------------------------


class TestHiveTokenVerifier:
    async def test_valid_token_returns_access_token(self, server_env):
        from hive.server import HiveTokenVerifier

        _, client_id, jwt = server_env
        verifier = HiveTokenVerifier()
        result = await verifier.verify_token(jwt)
        assert result is not None
        assert result.client_id == client_id
        assert "memories:read" in result.scopes
        assert "memories:write" in result.scopes

    async def test_invalid_token_returns_none(self, server_env):
        from hive.server import HiveTokenVerifier

        verifier = HiveTokenVerifier()
        result = await verifier.verify_token("not-a-valid-token")
        assert result is None
