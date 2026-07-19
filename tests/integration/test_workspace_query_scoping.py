# Copyright (c) 2026 John Carter. All rights reserved.
"""
Integration tests for workspace scoping of the MCP query tools (#493)
against DynamoDB Local.

Two tokens share the same owner account but carry different workspace
claims — the strict case where only the workspace boundary (not the
account boundary) separates them. Writes made under workspace A must be
invisible from workspace B through every read path: list_memories,
list_tags, search_memories, and summarize_context; keyed recall stays
not-found; forget_all never crosses the boundary.

Usage:
  docker run -p 8080:8000 amazon/dynamodb-local
  DYNAMODB_ENDPOINT=http://localhost:8080 pytest tests/integration/
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

DYNAMO_ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT")

pytestmark = pytest.mark.skipif(
    not DYNAMO_ENDPOINT,
    reason="DYNAMODB_ENDPOINT not set — skipping integration tests",
)

_TABLE = "hive-integration-workspace-scoping"


def _make_context(token_str: str):
    """Build a minimal MCP Context with an Authorization header."""
    ctx = MagicMock()
    ctx.request_context = MagicMock()
    ctx.request_context.meta = {"Authorization": f"Bearer {token_str}"}
    return ctx


def _text(r) -> str:
    return r.content[0].text


def _body(r) -> dict:
    return r.structured_content


@pytest.fixture(scope="module")
def setup():
    """Two workspace-scoped tokens (same owner account) + storage."""
    import contextlib
    from datetime import datetime, timedelta, timezone

    import boto3

    from hive.auth.tokens import issue_jwt
    from hive.models import OAuthClient, Token

    ddb = boto3.client(
        "dynamodb",
        endpoint_url=DYNAMO_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    with contextlib.suppress(Exception):
        ddb.delete_table(TableName=_TABLE)

    ddb.create_table(
        TableName=_TABLE,
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
            {"AttributeName": "GSI5PK", "AttributeType": "S"},
            {"AttributeName": "GSI5SK", "AttributeType": "S"},
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
                "IndexName": "WorkspaceMemberIndex",
                "KeySchema": [
                    {"AttributeName": "GSI5PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI5SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    old_table = os.environ.get("HIVE_TABLE_NAME")
    os.environ["HIVE_TABLE_NAME"] = _TABLE
    from hive.storage import HiveStorage

    storage = HiveStorage(
        table_name=_TABLE,
        region="us-east-1",
        endpoint_url=DYNAMO_ENDPOINT,
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )

    owner = "ws-scoping-user"
    now = datetime.now(timezone.utc)
    jwts = {}
    for ws in ("ws-int-a", "ws-int-b"):
        client = OAuthClient(client_name=f"WS client {ws}", owner_user_id=owner, workspace_id=ws)
        storage.put_client(client)
        token = Token(
            client_id=client.client_id,
            scope="memories:read memories:write",
            issued_at=now,
            expires_at=now + timedelta(hours=1),
            workspace_id=ws,
            workspace_role="owner",
        )
        storage.put_token(token)
        jwts[ws] = issue_jwt(token)
    yield storage, jwts["ws-int-a"], jwts["ws-int-b"]

    # Restore the env var so later integration modules in the same process
    # keep their expected table binding.
    if old_table is not None:
        os.environ["HIVE_TABLE_NAME"] = old_table
    else:
        os.environ.pop("HIVE_TABLE_NAME", None)


@pytest.mark.asyncio
class TestWorkspaceQueryScoping:
    async def _seed(self, jwt_a, jwt_b):
        from hive.server import remember

        await remember("a-note", "alpha-secret", ["scoped"], ctx=_make_context(jwt_a))
        await remember("b-note", "bravo-secret", ["scoped"], ctx=_make_context(jwt_b))

    async def test_list_memories_is_mutually_invisible(self, setup):
        from hive.server import list_memories

        _, jwt_a, jwt_b = setup
        await self._seed(jwt_a, jwt_b)

        keys_a = {
            m["key"]
            for m in _body(await list_memories("scoped", ctx=_make_context(jwt_a)))["items"]
        }
        keys_b = {
            m["key"]
            for m in _body(await list_memories("scoped", ctx=_make_context(jwt_b)))["items"]
        }
        assert keys_a == {"a-note"}
        assert keys_b == {"b-note"}

    async def test_list_tags_is_mutually_invisible(self, setup):
        from hive.server import list_tags, remember

        _, jwt_a, jwt_b = setup
        await remember("a-tagged", "v", ["only-in-a"], ctx=_make_context(jwt_a))
        await remember("b-tagged", "v", ["only-in-b"], ctx=_make_context(jwt_b))

        tags_a = _body(await list_tags(ctx=_make_context(jwt_a)))["tags"]
        tags_b = _body(await list_tags(ctx=_make_context(jwt_b)))["tags"]
        assert "only-in-a" in tags_a and "only-in-b" not in tags_a
        assert "only-in-b" in tags_b and "only-in-a" not in tags_b

    async def test_summarize_context_is_mutually_invisible(self, setup):
        from hive.server import summarize_context

        _, jwt_a, jwt_b = setup
        await self._seed(jwt_a, jwt_b)

        text_a = _text(await summarize_context("scoped", ctx=_make_context(jwt_a)))
        text_b = _text(await summarize_context("scoped", ctx=_make_context(jwt_b)))
        assert "alpha-secret" in text_a and "bravo-secret" not in text_a
        assert "bravo-secret" in text_b and "alpha-secret" not in text_b

    async def test_search_memories_is_mutually_invisible(self, setup):
        """Even when the vector layer surfaces both candidates (e.g. pre-#493
        vectors carrying no workspace metadata), the authoritative DynamoDB
        check keeps foreign-workspace hits out of the results."""
        from hive.server import search_memories

        storage, jwt_a, jwt_b = setup
        await self._seed(jwt_a, jwt_b)
        mem_a = storage.get_memory_by_key("a-note")
        mem_b = storage.get_memory_by_key("b-note")

        mock_vs = MagicMock()
        mock_vs.search.return_value = [
            (mem_a.memory_id, 0.9),
            (mem_b.memory_id, 0.9),
        ]
        with patch("hive.server._vector_store", return_value=mock_vs):
            keys_a = {
                i["key"]
                for i in _body(await search_memories("secret", ctx=_make_context(jwt_a)))["items"]
            }
            keys_b = {
                i["key"]
                for i in _body(await search_memories("secret", ctx=_make_context(jwt_b)))["items"]
            }
        assert keys_a == {"a-note"}
        assert keys_b == {"b-note"}
        # Each query pushed its own workspace claim down to the vector filter.
        called_ws = [c.kwargs["workspace_id"] for c in mock_vs.search.call_args_list]
        assert called_ws == ["ws-int-a", "ws-int-b"]

    async def test_cross_workspace_recall_stays_not_found(self, setup):
        from fastmcp.exceptions import ToolError

        from hive.server import recall

        _, jwt_a, jwt_b = setup
        await self._seed(jwt_a, jwt_b)
        with pytest.raises(ToolError, match="No memory found for key 'a-note'"):
            await recall(key="a-note", ctx=_make_context(jwt_b))

    async def test_forget_all_never_crosses_the_boundary(self, setup):
        from hive.server import forget_all, remember

        storage, jwt_a, jwt_b = setup
        await remember("a-bulk", "v", ["bulk"], ctx=_make_context(jwt_a))
        await remember("b-bulk", "v", ["bulk"], ctx=_make_context(jwt_b))

        result = await forget_all(tag="bulk", ctx=_make_context(jwt_a))
        assert "Deleted 1 memories" in _text(result)
        assert storage.get_memory_by_key("a-bulk") is None
        assert storage.get_memory_by_key("b-bulk") is not None
