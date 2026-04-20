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


def _make_ctx(jwt: str, *, progress_sink: list | None = None) -> MagicMock:
    """Build a minimal mock Context that passes token via meta.

    If ``progress_sink`` is provided, each ``report_progress`` call is
    appended to it so tests can assert on the emitted notifications.
    """
    from unittest.mock import AsyncMock

    ctx = MagicMock()
    ctx.request_context.meta = {"Authorization": f"Bearer {jwt}"}
    if progress_sink is not None:

        async def _capture(**kwargs):
            progress_sink.append(kwargs)

        ctx.report_progress = AsyncMock(side_effect=_capture)
    else:
        ctx.report_progress = AsyncMock()
    return ctx


def _text(r) -> str:
    """Extract text payload from a ToolResult (for string-returning tools)."""
    return r.content[0].text


def _body(r) -> dict:
    """Extract structured content from a ToolResult (for dict-returning tools)."""
    return r.structured_content


def _hive_meta(r) -> dict:
    """Extract the ``_meta.hive`` quota/rate-limit block from a ToolResult."""
    return r.meta["hive"]


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
        assert _text(result) == "ok"
        # Every tool response carries quota + rate-limit state under _meta.hive
        meta = _hive_meta(result)
        assert "memory_quota" in meta
        assert "rate_limit" in meta

    async def test_missing_auth_raises_tool_error(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import ping

        ctx = MagicMock()
        ctx.request_context.meta = {}
        with pytest.raises(ToolError, match="Unauthorized"):
            await ping(ctx=ctx)

    async def test_auth_rejection_emits_token_validation_failure_metric(self, server_env):
        """The AuthFailures CloudWatch alarm watches TokenValidationFailures —
        make sure the MCP auth path actually emits it on rejection."""
        from unittest.mock import AsyncMock, patch

        from fastmcp.exceptions import ToolError

        from hive.server import ping

        ctx = MagicMock()
        ctx.request_context.meta = {"Authorization": "Bearer totally-bogus"}
        mock_emit = AsyncMock()
        with (
            patch("hive.server.emit_metric", mock_emit),
            pytest.raises(ToolError, match="Unauthorized"),
        ):
            await ping(ctx=ctx)
        names_emitted = [call.args[0] for call in mock_emit.call_args_list]
        assert "TokenValidationFailures" in names_emitted

    async def test_rate_limit_emits_rate_limited_requests_metric(self, server_env):
        """#367 — the admin Dashboard reads the RateLimitedRequests metric to
        surface 429 pressure; the MCP auth path must actually emit it on
        RateLimitExceeded."""
        from unittest.mock import AsyncMock, patch

        from fastmcp.exceptions import ToolError

        from hive.rate_limiter import RateLimitExceeded
        from hive.server import ping

        _, _, jwt = server_env
        ctx = MagicMock()
        ctx.request_context.meta = {"Authorization": f"Bearer {jwt}"}
        mock_emit = AsyncMock()
        with (
            patch("hive.server.emit_metric", mock_emit),
            patch("hive.server.check_rate_limit", side_effect=RateLimitExceeded(retry_after=42)),
            pytest.raises(ToolError, match="Rate limit exceeded"),
        ):
            await ping(ctx=ctx)
        calls = [(c.args, c.kwargs) for c in mock_emit.call_args_list]
        # Aggregate emit + drill-down with endpoint/reason dimensions.
        assert (("RateLimitedRequests",), {}) in calls
        assert (
            ("RateLimitedRequests",),
            {"endpoint": "mcp", "reason": "rate_limit"},
        ) in calls


# ---------------------------------------------------------------------------
# remember
# ---------------------------------------------------------------------------


class TestRemember:
    async def test_store_new_memory(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import remember

        result = await remember("my-key", "my-value", ["tag1"], ctx=_make_ctx(jwt))
        assert _text(result) == "Stored memory 'my-key'."
        assert storage.get_memory_by_key("my-key") is not None

    async def test_update_existing_memory(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import remember

        await remember("upd-key", "original", [], ctx=_make_ctx(jwt))
        result = await remember("upd-key", "updated", ["new-tag"], ctx=_make_ctx(jwt))
        assert _text(result) == "Updated memory 'upd-key'."
        m = storage.get_memory_by_key("upd-key")
        assert m is not None
        assert m.value == "updated"

    async def test_idempotent_no_change(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import remember

        await remember("same-key", "same-value", ["t"], ctx=_make_ctx(jwt))
        result = await remember("same-key", "same-value", ["t"], ctx=_make_ctx(jwt))
        assert _text(result) == "Memory 'same-key' unchanged."

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
        assert _text(result) == "Stored memory 'pydantic-meta-key'."

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
        assert _text(result) == "Stored memory 'at-limit-key'."

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
            assert _text(result) == "Stored memory 'within-key'."

    async def test_remember_with_ttl_sets_expires_at(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import remember

        result = await remember("ttl-key", "ttl-val", [], ttl_seconds=3600, ctx=_make_ctx(jwt))
        assert _text(result) == "Stored memory 'ttl-key'."
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
        assert _text(result) == "Updated memory 'idem-ttl'."
        m2 = storage.get_memory_by_key("idem-ttl")
        assert m2 is not None
        assert m2.expires_at is None


# ---------------------------------------------------------------------------
# remember_if_absent
# ---------------------------------------------------------------------------


class TestRememberIfAbsent:
    async def test_writes_when_key_absent(self, server_env):
        storage, _, jwt = server_env
        from hive.server import remember_if_absent

        result = await remember_if_absent("ifa-new", "v", ["t"], ctx=_make_ctx(jwt))
        assert _text(result) == "Stored memory 'ifa-new'."
        m = storage.get_memory_by_key("ifa-new")
        assert m is not None
        assert m.value == "v"

    async def test_skips_when_key_exists(self, server_env):
        storage, _, jwt = server_env
        from hive.server import remember, remember_if_absent

        await remember("ifa-dupe", "original", ["old"], ctx=_make_ctx(jwt))
        result = await remember_if_absent("ifa-dupe", "new-value", ["new"], ctx=_make_ctx(jwt))
        assert _text(result) == "Memory 'ifa-dupe' already exists — not overwritten."
        m = storage.get_memory_by_key("ifa-dupe")
        assert m.value == "original"
        assert set(m.tags) == {"old"}

    async def test_sets_ttl_when_writing(self, server_env):
        storage, _, jwt = server_env
        from hive.server import remember_if_absent

        await remember_if_absent("ifa-ttl", "v", [], ttl_seconds=3600, ctx=_make_ctx(jwt))
        m = storage.get_memory_by_key("ifa-ttl")
        assert m.expires_at is not None

    async def test_oversized_value_raises(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import DEFAULT_MAX_VALUE_BYTES, remember_if_absent

        _, _, jwt = server_env
        with pytest.raises(ToolError, match="exceeds maximum size"):
            await remember_if_absent(
                "ifa-big", "x" * (DEFAULT_MAX_VALUE_BYTES + 1), ctx=_make_ctx(jwt)
            )

    async def test_storage_value_error_becomes_tool_error(self, server_env):
        from unittest.mock import patch

        from fastmcp.exceptions import ToolError

        from hive.server import remember_if_absent

        storage, _, jwt = server_env
        with (
            patch.object(storage.__class__, "get_memory_by_key", return_value=None),
            patch.object(
                storage.__class__,
                "put_memory",
                side_effect=ValueError("Memory value is too large"),
            ),
            pytest.raises(ToolError, match="too large"),
        ):
            await remember_if_absent("ifa-err", "v", ctx=_make_ctx(jwt))

    async def test_quota_exceeded_becomes_tool_error(self, server_env):
        from unittest.mock import patch

        from fastmcp.exceptions import ToolError

        from hive.quota import QuotaExceeded
        from hive.server import remember_if_absent

        _, _, jwt = server_env
        with (
            patch("hive.server.check_memory_quota", side_effect=QuotaExceeded("quota full")),
            pytest.raises(ToolError, match="quota full"),
        ):
            await remember_if_absent("ifa-q", "v", ctx=_make_ctx(jwt))

    async def test_vector_upsert_failure_is_non_fatal(self, server_env):
        from unittest.mock import MagicMock, patch

        from hive.server import remember_if_absent

        _, _, jwt = server_env
        mock_vs = MagicMock()
        mock_vs.upsert_memory.side_effect = RuntimeError("bedrock down")

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await remember_if_absent("ifa-vs-fail", "v", ctx=_make_ctx(jwt))

        assert _text(result) == "Stored memory 'ifa-vs-fail'."

    async def test_requires_write_scope(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import remember_if_absent

        storage, _, _ = server_env
        read_only_jwt = _make_limited_scope_jwt(storage, "memories:read")
        with pytest.raises(ToolError, match="Insufficient scope"):
            await remember_if_absent("ifa-scope", "v", ctx=_make_ctx(read_only_jwt))


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------


class TestRecall:
    async def test_recall_existing(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import recall, remember

        await remember("rec-key", "the-value", [], ctx=_make_ctx(jwt))
        result = await recall("rec-key", ctx=_make_ctx(jwt))
        assert _text(result) == "the-value"

    async def test_recall_nonexistent_raises(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import recall

        _, _, jwt = server_env
        with pytest.raises(ToolError, match="No memory found"):
            await recall("no-such-key", ctx=_make_ctx(jwt))

    async def test_recall_bumps_recall_count_and_last_accessed_at(self, server_env):
        storage, _, jwt = server_env
        from hive.server import recall, remember

        await remember("rec-counter", "v", [], ctx=_make_ctx(jwt))
        before = storage.get_memory_by_key("rec-counter")
        assert before.recall_count == 0
        assert before.last_accessed_at is None

        await recall("rec-counter", ctx=_make_ctx(jwt))
        after_first = storage.get_memory_by_key("rec-counter")
        assert after_first.recall_count == 1
        assert after_first.last_accessed_at is not None

        await recall("rec-counter", ctx=_make_ctx(jwt))
        after_second = storage.get_memory_by_key("rec-counter")
        assert after_second.recall_count == 2
        assert after_second.last_accessed_at >= after_first.last_accessed_at


# ---------------------------------------------------------------------------
# forget
# ---------------------------------------------------------------------------


class TestForget:
    async def test_forget_existing(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import forget, remember

        await remember("del-key", "v", [], ctx=_make_ctx(jwt))
        result = await forget("del-key", ctx=_make_ctx(jwt))
        assert _text(result) == "Deleted memory 'del-key'."
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
        body = _body(result)
        assert "items" in body and "has_more" in body
        keys = [m["key"] for m in body["items"]]
        assert "lst-a" in keys
        assert "lst-b" not in keys
        # Agent attribution is surfaced on every item.
        assert body["items"][0]["owner_client_id"] == client_id
        # Usage metrics are surfaced too; fresh memories have count=0, no access.
        assert body["items"][0]["recall_count"] == 0
        assert body["items"][0]["last_accessed_at"] is None

    async def test_list_memories_surfaces_recall_metrics_after_recall(self, server_env):
        _, _, jwt = server_env
        from hive.server import list_memories, recall, remember

        await remember("bumped", "v", ["alpha"], ctx=_make_ctx(jwt))
        await recall("bumped", ctx=_make_ctx(jwt))

        result = await list_memories("alpha", ctx=_make_ctx(jwt))
        item = next(x for x in _body(result)["items"] if x["key"] == "bumped")
        assert item["recall_count"] == 1
        assert item["last_accessed_at"] is not None

    async def test_list_empty_tag_returns_empty(self, server_env):
        _, _, jwt = server_env
        from hive.server import list_memories

        result = await list_memories("nonexistent-tag", ctx=_make_ctx(jwt))
        body = _body(result)
        assert body["items"] == []
        assert body["has_more"] is False


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
        assert _body(result) == {"tags": ["alpha", "mango", "zebra"], "count": 3}

    async def test_empty_when_no_memories(self, server_env):
        _, _, jwt = server_env
        from hive.server import list_tags

        result = await list_tags(ctx=_make_ctx(jwt))
        assert _body(result) == {"tags": [], "count": 0}

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
        assert _body(result)["tags"] == ["owned"]

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
        text = _text(result)
        assert "foo" in text
        assert "sum-a" in text or "detail about foo" in text

    async def test_summarize_no_memories(self, server_env):
        _, _, jwt = server_env
        from hive.server import summarize_context

        result = await summarize_context("nonexistent-topic", ctx=_make_ctx(jwt))
        assert "No memories found" in _text(result)

    async def test_summarize_uses_mcp_sampling_when_available(self, server_env):
        """When ctx.sample returns a result, the synthesised text replaces
        the concat fallback."""
        from unittest.mock import AsyncMock, MagicMock

        from hive.server import remember, summarize_context

        _, _, jwt = server_env
        await remember("s-a", "policy X says Y", ["sampled"], ctx=_make_ctx(jwt))

        ctx = _make_ctx(jwt)
        sampled = MagicMock()
        sampled.text = "SYNTHESISED BRIEFING OUTPUT"
        ctx.sample = AsyncMock(return_value=sampled)

        result = await summarize_context("sampled", ctx=ctx)
        assert _text(result) == "SYNTHESISED BRIEFING OUTPUT"
        # Client was asked with a system prompt + the memories inline.
        ctx.sample.assert_awaited_once()
        args, kwargs = ctx.sample.call_args
        assert "policy X says Y" in args[0]
        assert "system_prompt" in kwargs

    async def test_summarize_falls_back_when_sampling_raises(self, server_env):
        """If the client rejects sampling (or transport errors), the concat
        listing is returned — the tool never fails because sampling isn't
        supported."""
        from unittest.mock import AsyncMock

        from hive.server import remember, summarize_context

        _, _, jwt = server_env
        await remember("f-a", "raw detail one", ["fallback"], ctx=_make_ctx(jwt))

        ctx = _make_ctx(jwt)
        ctx.sample = AsyncMock(side_effect=RuntimeError("sampling not supported"))

        result = await summarize_context("fallback", ctx=ctx)
        text = _text(result)
        assert "raw detail one" in text  # concat fallback contains the verbatim values

    async def test_sampled_summary_empty_text_falls_back(self, server_env):
        """An empty/whitespace-only sampling response falls back to concat."""
        from unittest.mock import AsyncMock, MagicMock

        from hive.server import remember, summarize_context

        _, _, jwt = server_env
        await remember("e-a", "verbatim detail", ["empty"], ctx=_make_ctx(jwt))

        ctx = _make_ctx(jwt)
        sampled = MagicMock()
        sampled.text = "   "
        ctx.sample = AsyncMock(return_value=sampled)

        result = await summarize_context("empty", ctx=ctx)
        assert "verbatim detail" in _text(result)

    async def test_sampled_summary_handles_ctx_none(self):
        """Direct call to the helper with ctx=None returns the fallback verbatim."""
        from hive.server import _sampled_summary

        out = await _sampled_summary(None, "t", [], "FALLBACK_TEXT")
        assert out == "FALLBACK_TEXT"


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
        assert "http-path-key" in _text(result)


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
        body = _body(result)
        assert body["has_more"] is True
        assert "next_cursor" in body


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

        body = _body(result)
        assert body["count"] == 1
        assert body["query"] == "searchable content"
        item = body["items"][0]
        assert item["key"] == "search-key"
        # Hybrid re-ranking exposes the original semantic score alongside the
        # blended score — both "searchable" and "content" tokens match so the
        # blended score exceeds the raw 0.88.
        assert item["semantic_score"] == 0.88
        assert item["keyword_score"] == 1.0
        assert item["score"] >= 0.88
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

        assert _body(result) == {"items": [], "count": 0, "query": "anything"}

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

        body = _body(result)
        assert body["count"] == 1
        assert [item["key"] for item in body["items"]] == ["hi-key"]

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

        assert _body(result)["count"] == 2

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

        assert _body(result) == {"items": [], "count": 0, "query": "q"}

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

        body = _body(result)
        # Only "a" has both x and y
        assert [item["key"] for item in body["items"]] == ["a"]
        assert body["count"] == 1

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

        assert _body(result)["count"] == 1

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

        body = _body(result)
        assert body["count"] == 2
        assert [item["key"] for item in body["items"]] == ["k0", "k1"]

    async def test_min_score_clamped_to_unit_interval(self, server_env):
        from unittest.mock import patch

        from hive.server import remember, search_memories

        storage, _, jwt = server_env
        ctx = _make_ctx(jwt)
        # Disable recency weighting so floating-point decay against
        # updated_at doesn't push blended below 1.0 and mask the clamp test.
        await remember("key", "q", ["t"], ctx=ctx)
        m = storage.get_memory_by_key("key")
        mock_vs = _make_mock_vector_store([(m.memory_id, 1.0)])

        # min_score > 1.0 gets clamped to 1.0; with w_recency=0 blended = 1.0.
        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await search_memories("q", min_score=5.0, w_recency=0, ctx=ctx)

        assert _body(result)["count"] == 1

        # min_score < 0.0 gets clamped to 0.0; everything passes.
        mock_vs2 = _make_mock_vector_store([(m.memory_id, 0.0)])
        with patch("hive.server._vector_store", return_value=mock_vs2):
            result = await search_memories("q", min_score=-1.0, ctx=ctx)

        assert _body(result)["count"] == 1

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

        assert "Stored" in _text(result)

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

        assert "Updated" in _text(result)

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

        assert "Deleted" in _text(result)

    async def test_search_vector_failure_returns_empty(self, server_env):
        """Unexpected VectorStore errors during search_memories() return empty results."""
        from unittest.mock import patch

        from hive.server import search_memories

        _, _, jwt = server_env
        mock_vs = MagicMock()
        mock_vs.search.side_effect = RuntimeError("no bucket")

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await search_memories("anything", ctx=_make_ctx(jwt))

        assert _body(result) == {"items": [], "count": 0, "query": "anything"}


# ---------------------------------------------------------------------------
# relate_memories
# ---------------------------------------------------------------------------


class TestRelateMemories:
    async def test_returns_related_with_source_excluded(self, server_env):
        from unittest.mock import patch

        from hive.server import relate_memories, remember

        storage, _, jwt = server_env
        ctx = _make_ctx(jwt)
        await remember("source", "about cats and dogs", ["t"], ctx=ctx)
        await remember("a", "cats are great pets", ["t"], ctx=ctx)
        await remember("b", "dogs are great pets", ["t"], ctx=ctx)
        src = storage.get_memory_by_key("source")
        a = storage.get_memory_by_key("a")
        b = storage.get_memory_by_key("b")
        # Vector store also ranks the source highly; relate_memories must drop it.
        mock_vs = _make_mock_vector_store(
            [(src.memory_id, 0.99), (a.memory_id, 0.9), (b.memory_id, 0.8)]
        )

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await relate_memories("source", top_k=2, ctx=ctx)

        body = _body(result)
        keys = [item["key"] for item in body["items"]]
        assert keys == ["a", "b"]
        assert body["count"] == 2
        assert body["key"] == "source"

    async def test_uses_source_value_as_query(self, server_env):
        from unittest.mock import patch

        from hive.server import relate_memories, remember

        _, _, jwt = server_env
        ctx = _make_ctx(jwt)
        await remember("source", "unique search phrase", [], ctx=ctx)
        mock_vs = _make_mock_vector_store([])

        with patch("hive.server._vector_store", return_value=mock_vs):
            await relate_memories("source", ctx=ctx)

        assert mock_vs.search.call_args.args[0] == "unique search phrase"
        # top_k+1 requested so the source-memory drop still leaves headroom.
        assert mock_vs.search.call_args.kwargs["top_k"] == 6

    async def test_missing_key_raises_tool_error(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import relate_memories

        _, _, jwt = server_env
        with pytest.raises(ToolError, match="No memory found"):
            await relate_memories("nonexistent", ctx=_make_ctx(jwt))

    async def test_returns_empty_when_no_index(self, server_env):
        from unittest.mock import MagicMock, patch

        from hive.server import relate_memories, remember
        from hive.vector_store import VectorIndexNotFoundError

        _, _, jwt = server_env
        ctx = _make_ctx(jwt)
        await remember("src", "v", [], ctx=ctx)
        mock_vs = MagicMock()
        mock_vs.search.side_effect = VectorIndexNotFoundError("no index")

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await relate_memories("src", ctx=ctx)

        assert _body(result) == {"items": [], "count": 0, "key": "src"}

    async def test_returns_empty_on_vector_error(self, server_env):
        from unittest.mock import MagicMock, patch

        from hive.server import relate_memories, remember

        _, _, jwt = server_env
        ctx = _make_ctx(jwt)
        await remember("src", "v", [], ctx=ctx)
        mock_vs = MagicMock()
        mock_vs.search.side_effect = RuntimeError("bedrock down")

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await relate_memories("src", ctx=ctx)

        assert _body(result) == {"items": [], "count": 0, "key": "src"}

    async def test_top_k_clamped(self, server_env):
        from unittest.mock import patch

        from hive.server import relate_memories, remember

        _, _, jwt = server_env
        ctx = _make_ctx(jwt)
        await remember("src", "v", [], ctx=ctx)
        mock_vs = _make_mock_vector_store([])

        with patch("hive.server._vector_store", return_value=mock_vs):
            await relate_memories("src", top_k=999, ctx=ctx)

        # 50 cap + 1 headroom
        assert mock_vs.search.call_args.kwargs["top_k"] == 51

    async def test_requires_read_scope(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import relate_memories

        storage, _, _ = server_env
        write_only_jwt = _make_limited_scope_jwt(storage, "memories:write")
        with pytest.raises(ToolError, match="Insufficient scope"):
            await relate_memories("any", ctx=_make_ctx(write_only_jwt))


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
        assert "2" in _text(result)
        assert storage.get_memory_by_key("fa-a") is None
        assert storage.get_memory_by_key("fa-b") is None
        assert storage.get_memory_by_key("fa-c") is not None

    async def test_forget_all_zero_when_tag_missing(self, server_env):
        _, _, jwt = server_env
        from hive.server import forget_all

        result = await forget_all("no-such-tag", ctx=_make_ctx(jwt))
        assert "0" in _text(result)

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
        body = _body(result)
        assert body["count"] == 1
        assert len(body["versions"]) == 1
        assert body["versions"][0]["value"] == "v1"

    async def test_memory_history_empty_for_new_memory(self, server_env):
        storage, client_id, jwt = server_env
        from hive.server import memory_history, remember

        await remember("new-hist", "v1", [], ctx=_make_ctx(jwt))
        result = await memory_history("new-hist", ctx=_make_ctx(jwt))
        assert _body(result) == {"versions": [], "count": 0}

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
        vts = _body(versions)["versions"][0]["version_timestamp"]
        result = await restore_memory("rst-k", vts, ctx=_make_ctx(jwt))
        assert "rst-k" in _text(result)
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


class TestMcpToolAnnotations:
    """Every exposed MCP tool should carry a user-friendly title and
    annotations that let consent-aware clients (Claude Desktop, Claude Code)
    render destructive operations differently from read-only ones.
    """

    @pytest.mark.parametrize(
        "tool_name,title,read_only,destructive",
        [
            ("ping", "Ping", True, None),
            ("remember", "Remember", False, False),
            ("remember_if_absent", "Remember if absent", False, False),
            ("recall", "Recall", True, None),
            ("forget", "Forget", False, True),
            ("forget_all", "Forget all (by tag)", False, True),
            ("redact_memory", "Redact memory", False, True),
            ("memory_history", "Memory history", True, None),
            ("restore_memory", "Restore memory", False, False),
            ("list_memories", "List memories", True, None),
            ("list_tags", "List tags", True, None),
            ("summarize_context", "Summarise context", True, None),
            ("search_memories", "Search memories", True, None),
            ("relate_memories", "Relate memories", True, None),
        ],
    )
    async def test_title_and_hints(self, tool_name, title, read_only, destructive):
        from hive.server import mcp

        tool = await mcp.get_tool(tool_name)
        assert tool.title == title
        assert tool.annotations.readOnlyHint is read_only
        # destructiveHint is only set when meaningful.
        assert tool.annotations.destructiveHint is destructive
        # Every Hive tool is closed-world (our DynamoDB only).
        assert tool.annotations.openWorldHint is False


class TestRememberOptimisticLocking:
    """`remember(key, value, version=...)` rejects stale writes with a
    ToolError carrying the current state so the agent can reconcile."""

    async def test_version_match_updates_successfully(self, server_env):
        storage, _, jwt = server_env
        from hive.server import recall, remember

        await remember("lock-k", "v1", [], ctx=_make_ctx(jwt))
        m = storage.get_memory_by_key("lock-k")
        result = await remember("lock-k", "v2", [], version=m.version, ctx=_make_ctx(jwt))
        assert _text(result) == "Updated memory 'lock-k'."
        assert (await recall("lock-k", ctx=_make_ctx(jwt))).content[0].text == "v2"

    async def test_stale_version_raises_conflict(self, server_env):
        import json as _json

        from fastmcp.exceptions import ToolError

        from hive.server import remember

        storage, _, jwt = server_env
        await remember("lock-s", "v1", [], ctx=_make_ctx(jwt))
        m = storage.get_memory_by_key("lock-s")
        # A concurrent writer advances the version out from under us.
        await remember("lock-s", "concurrent", [], ctx=_make_ctx(jwt))

        with pytest.raises(ToolError) as exc_info:
            await remember("lock-s", "mine", [], version=m.version, ctx=_make_ctx(jwt))

        msg = str(exc_info.value)
        assert "Conflict" in msg
        # Tail of the message is a JSON payload with the conflict state.
        payload = _json.loads(msg[msg.index("{") :])
        assert payload["conflict"] is True
        assert payload["attempted_version"] == m.version
        assert payload["current_value"] == "concurrent"
        assert payload["current_version"] != m.version

    async def test_no_version_preserves_backwards_compat(self, server_env):
        """Unconditional upsert still works when version param is omitted."""
        storage, _, jwt = server_env
        from hive.server import remember

        await remember("lock-b", "v1", [], ctx=_make_ctx(jwt))
        result = await remember("lock-b", "v2", [], ctx=_make_ctx(jwt))
        assert _text(result) == "Updated memory 'lock-b'."
        assert storage.get_memory_by_key("lock-b").value == "v2"

    async def test_version_surfaces_in_recall_meta(self, server_env):
        storage, _, jwt = server_env
        from hive.server import recall, remember

        await remember("lock-r", "v1", [], ctx=_make_ctx(jwt))
        m = storage.get_memory_by_key("lock-r")
        result = await recall("lock-r", ctx=_make_ctx(jwt))
        meta = _hive_meta(result)
        assert meta["memory"]["key"] == "lock-r"
        assert meta["memory"]["version"] == m.version

    async def test_version_surfaces_in_list_memories_items(self, server_env):
        _, _, jwt = server_env
        from hive.server import list_memories, remember

        await remember("lock-l", "v1", ["locktag"], ctx=_make_ctx(jwt))
        result = await list_memories("locktag", ctx=_make_ctx(jwt))
        item = next(it for it in _body(result)["items"] if it["key"] == "lock-l")
        assert "version" in item
        assert item["version"]

    async def test_conflict_raced_put_surfaces_as_tool_error(self, server_env):
        """Covers the path where storage raises VersionConflict during the
        put (e.g. the narrow race between the pre-check read and the
        conditional write) — remember surfaces it as a ToolError."""
        from unittest.mock import patch

        from fastmcp.exceptions import ToolError

        from hive.server import remember
        from hive.storage import VersionConflict

        storage, _, jwt = server_env
        await remember("lock-r2", "v1", [], ctx=_make_ctx(jwt))
        m = storage.get_memory_by_key("lock-r2")

        with (
            patch.object(
                storage.__class__,
                "put_memory",
                side_effect=VersionConflict(
                    attempted_version=m.version,
                    current_value="raced-in",
                    current_version="newer",
                ),
            ),
            pytest.raises(ToolError, match="Conflict"),
        ):
            await remember("lock-r2", "v2", [], version=m.version, ctx=_make_ctx(jwt))


class TestRedactMemory:
    """`redact_memory` tombstones a memory's value while preserving the record (#400)."""

    async def test_redacts_existing_memory(self, server_env):
        storage, _, jwt = server_env
        from hive.server import redact_memory, remember

        await remember("secret", "the wifi password is 1234", ["pii"], ctx=_make_ctx(jwt))
        result = await redact_memory("secret", reason="pii leak", ctx=_make_ctx(jwt))
        assert _text(result) == "Redacted memory 'secret'."

        stored = storage.get_memory_by_key("secret")
        assert stored.is_redacted is True
        assert stored.value == "__redacted__"
        assert stored.redacted_at is not None

    async def test_recall_returns_sentinel_on_redacted(self, server_env):
        _, _, jwt = server_env
        from hive.server import recall, redact_memory, remember

        await remember("s", "raw secret", [], ctx=_make_ctx(jwt))
        await redact_memory("s", reason="gdpr", ctx=_make_ctx(jwt))

        result = await recall("s", ctx=_make_ctx(jwt))
        text = _text(result)
        assert "redacted" in text.lower()
        assert "raw secret" not in text

    async def test_list_memories_skips_redacted_by_default(self, server_env):
        _, _, jwt = server_env
        from hive.server import list_memories, redact_memory, remember

        ctx = _make_ctx(jwt)
        await remember("visible", "keep me", ["r"], ctx=ctx)
        await remember("hidden", "redact me", ["r"], ctx=ctx)
        await redact_memory("hidden", ctx=ctx)

        result = await list_memories("r", ctx=ctx)
        keys = [i["key"] for i in _body(result)["items"]]
        assert "visible" in keys
        assert "hidden" not in keys

    async def test_list_memories_include_redacted_surfaces_them(self, server_env):
        _, _, jwt = server_env
        from hive.server import list_memories, redact_memory, remember

        ctx = _make_ctx(jwt)
        await remember("visible", "keep me", ["r2"], ctx=ctx)
        await remember("hidden", "redact me", ["r2"], ctx=ctx)
        await redact_memory("hidden", ctx=ctx)

        result = await list_memories("r2", include_redacted=True, ctx=ctx)
        keys = [i["key"] for i in _body(result)["items"]]
        assert "visible" in keys
        assert "hidden" in keys

    async def test_search_memories_skips_redacted_by_default(self, server_env):
        from unittest.mock import patch

        from hive.server import redact_memory, remember, search_memories

        storage, _, jwt = server_env
        ctx = _make_ctx(jwt)
        await remember("a", "content about policy", ["t"], ctx=ctx)
        await remember("b", "content about privacy", ["t"], ctx=ctx)
        await redact_memory("b", ctx=ctx)

        a = storage.get_memory_by_key("a")
        b = storage.get_memory_by_key("b")
        mock_vs = _make_mock_vector_store([(a.memory_id, 0.9), (b.memory_id, 0.8)])

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await search_memories("content", ctx=ctx)

        keys = [i["key"] for i in _body(result)["items"]]
        assert "a" in keys
        assert "b" not in keys

    async def test_search_memories_include_redacted_surfaces_them(self, server_env):
        from unittest.mock import patch

        from hive.server import redact_memory, remember, search_memories

        storage, _, jwt = server_env
        ctx = _make_ctx(jwt)
        await remember("a", "content", ["t"], ctx=ctx)
        await remember("b", "content", ["t"], ctx=ctx)
        await redact_memory("b", ctx=ctx)

        a = storage.get_memory_by_key("a")
        b = storage.get_memory_by_key("b")
        mock_vs = _make_mock_vector_store([(a.memory_id, 0.9), (b.memory_id, 0.8)])

        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await search_memories("content", include_redacted=True, ctx=ctx)

        keys = [i["key"] for i in _body(result)["items"]]
        assert "a" in keys
        assert "b" in keys

    async def test_missing_key_raises(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import redact_memory

        _, _, jwt = server_env
        with pytest.raises(ToolError, match="No memory found"):
            await redact_memory("no-such-key", ctx=_make_ctx(jwt))

    async def test_double_redaction_is_idempotent(self, server_env):
        _, _, jwt = server_env
        from hive.server import redact_memory, remember

        await remember("dbl", "v", [], ctx=_make_ctx(jwt))
        await redact_memory("dbl", ctx=_make_ctx(jwt))
        result = await redact_memory("dbl", ctx=_make_ctx(jwt))
        assert "already redacted" in _text(result)

    async def test_audit_log_preserves_pre_redaction_value(self, server_env):
        storage, _, jwt = server_env
        from hive.models import EventType
        from hive.server import redact_memory, remember

        await remember("audit-r", "sensitive original value", [], ctx=_make_ctx(jwt))
        await redact_memory("audit-r", reason="accidental leak", ctx=_make_ctx(jwt))

        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        events = storage.get_audit_events_for_dates([today], event_type="memory_redacted")
        assert len(events) >= 1
        redaction = events[0]
        assert redaction.metadata["previous_value"] == "sensitive original value"
        assert redaction.metadata["reason"] == "accidental leak"
        assert redaction.event_type == EventType.memory_redacted

    async def test_vector_delete_failure_is_non_fatal(self, server_env):
        from unittest.mock import MagicMock, patch

        from hive.server import redact_memory, remember

        _, _, jwt = server_env
        await remember("vd", "v", [], ctx=_make_ctx(jwt))

        mock_vs = MagicMock()
        mock_vs.delete_memory.side_effect = RuntimeError("bucket down")
        with patch("hive.server._vector_store", return_value=mock_vs):
            result = await redact_memory("vd", ctx=_make_ctx(jwt))
        assert "Redacted" in _text(result)

    async def test_requires_write_scope(self, server_env):
        from fastmcp.exceptions import ToolError

        from hive.server import redact_memory

        storage, _, _ = server_env
        read_only_jwt = _make_limited_scope_jwt(storage, "memories:read")
        with pytest.raises(ToolError, match="Insufficient scope"):
            await redact_memory("any", ctx=_make_ctx(read_only_jwt))


class TestProgressNotifications:
    """Long-running tools emit MCP ``notifications/progress`` events so
    clients can render a progress indicator. Clients that don't support
    them must still get a usable result — emission is best-effort."""

    async def test_summarize_context_emits_progress(self, server_env):
        _, _, jwt = server_env
        from hive.server import remember, summarize_context

        sink: list = []
        ctx = _make_ctx(jwt, progress_sink=sink)
        await remember("p-a", "about foo", ["prog"], ctx=_make_ctx(jwt))
        await remember("p-b", "more about foo", ["prog"], ctx=_make_ctx(jwt))

        await summarize_context("prog", ctx=ctx)

        assert len(sink) >= 2
        progresses = [c["progress"] for c in sink]
        totals = {c["total"] for c in sink}
        assert progresses[0] == 0
        assert progresses[-1] == 1
        assert totals == {2}

    async def test_search_memories_emits_progress(self, server_env):
        from unittest.mock import patch

        from hive.server import remember, search_memories

        storage, _, jwt = server_env
        await remember("ps-a", "searchable content", ["t"], ctx=_make_ctx(jwt))
        m = storage.get_memory_by_key("ps-a")

        sink: list = []
        ctx = _make_ctx(jwt, progress_sink=sink)
        from unittest.mock import MagicMock as _MM

        mock_vs = _MM()
        mock_vs.search.return_value = [(m.memory_id, 0.9)]
        with patch("hive.server._vector_store", return_value=mock_vs):
            await search_memories("searchable", ctx=ctx)

        # 3 stages: before vector search, after hydrate, after ranking
        assert len(sink) == 3
        assert [c["progress"] for c in sink] == [0, 1, 2]
        assert {c["total"] for c in sink} == {3}

    async def test_progress_emission_is_non_fatal(self, server_env):
        """If ctx.report_progress raises (client doesn't support it), the
        tool still returns successfully — progress is advisory only."""
        from unittest.mock import AsyncMock

        from hive.server import remember, summarize_context

        _, _, jwt = server_env
        ctx = _make_ctx(jwt)
        ctx.report_progress = AsyncMock(side_effect=RuntimeError("client refused"))
        await remember("np-a", "v", ["np"], ctx=_make_ctx(jwt))

        result = await summarize_context("np", ctx=ctx)
        assert _text(result)  # still returned a usable summary

    async def test_report_progress_noop_when_ctx_is_none(self):
        """Direct call with ctx=None must not raise."""
        from hive.server import _report_progress

        await _report_progress(None, 0, 2, "no-ctx")


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


class TestMcpPrompts:
    """#447 — MCP Prompts for common Hive workflows.

    Each prompt is a pure template function; the tests exercise the
    rendering logic directly (string return) and also round-trip through
    ``FastMCP.render_prompt`` to confirm it registers as an advertised
    prompt with the expected argument schema.
    """

    @pytest.mark.asyncio
    async def test_list_prompts_exposes_four_workflows(self):
        from hive.server import mcp

        prompts = await mcp.list_prompts()
        names = sorted(p.name for p in prompts)
        assert names == [
            "forget-older-than",
            "recall-context",
            "remember-this",
            "what-do-you-know-about",
        ]
        # Every prompt carries a non-empty description so clients can
        # render a menu entry without re-deriving from the docstring.
        for p in prompts:
            assert p.description, f"missing description on {p.name}"

    def test_recall_context_template_names_topic_and_tool(self):
        from hive.server import recall_context_prompt

        out = recall_context_prompt("release checklist")
        assert "release checklist" in out
        # Must name the exact tool the agent should call — if we rename
        # the MCP tool, this test surfaces the prompt drift.
        assert "`summarize_context`" in out

    def test_what_do_you_know_about_calls_search_memories(self):
        from hive.server import what_do_you_know_about_prompt

        out = what_do_you_know_about_prompt("Stats tab")
        assert "Stats tab" in out
        assert "`search_memories`" in out
        # top_k must be explicit so agents don't fall back to whatever
        # default they implement.
        assert "top_k=10" in out

    def test_remember_this_renders_tags_when_provided(self):
        from hive.server import remember_this_prompt

        out = remember_this_prompt("release-cadence", "weekly", tags="ops,release")
        assert "release-cadence" in out
        assert "weekly" in out
        # tags list must survive verbatim, in canonical list form.
        assert "['ops', 'release']" in out
        assert "`remember`" in out

    def test_remember_this_trims_blank_tag_entries(self):
        from hive.server import remember_this_prompt

        # Blank entries between commas are dropped so clients sending
        # " , a , " don't produce an empty tag that write-through
        # validation would later reject.
        out = remember_this_prompt("k", "v", tags=" , a , ")
        assert "['a']" in out

    def test_remember_this_with_empty_tags_renders_empty_list(self):
        from hive.server import remember_this_prompt

        out = remember_this_prompt("k", "v", tags="")
        # No tag-specific keyword-arg drift: the prompt always includes
        # tags=... so the agent never forgets to pass the parameter.
        assert "tags=[]" in out

    def test_forget_older_than_names_list_and_forget_tools(self):
        from hive.server import forget_older_than_prompt

        out = forget_older_than_prompt(30)
        assert "30 days" in out
        assert "`list_memories`" in out
        assert "`forget`" in out
        # Safety: the template must explicitly forbid bulk-delete
        # without user confirmation.
        assert "confirmation" in out.lower() or "confirm" in out.lower()

    @pytest.mark.asyncio
    async def test_render_prompt_roundtrip_produces_user_message(self):
        from hive.server import mcp

        # End-to-end through FastMCP's render pipeline — confirms the
        # prompt is discoverable by name, accepts the declared arguments,
        # and wraps the string return as a single user-role message.
        result = await mcp.render_prompt("recall-context", {"topic": "ops"})
        assert len(result.messages) == 1
        msg = result.messages[0]
        assert msg.role == "user"
        assert "ops" in msg.content.text
