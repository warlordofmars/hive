# Copyright (c) 2026 John Carter. All rights reserved.
"""
Integration tests for the FastMCP tools against DynamoDB Local.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

DYNAMO_ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT")

pytestmark = pytest.mark.skipif(
    not DYNAMO_ENDPOINT,
    reason="DYNAMODB_ENDPOINT not set — skipping integration tests",
)


def _make_context(token_str: str):
    """Build a minimal MCP Context with an Authorization header."""
    ctx = MagicMock()
    ctx.request_context = MagicMock()
    ctx.request_context.meta = {"Authorization": f"Bearer {token_str}"}
    return ctx


@pytest.fixture(scope="module")
def setup():
    """Set up DynamoDB Local table + a valid token for MCP tool calls."""
    from datetime import datetime, timedelta, timezone

    import boto3

    from hive.auth.tokens import issue_jwt
    from hive.models import OAuthClient, Token

    table_name = "hive-mcp-integration"
    ddb = boto3.client(
        "dynamodb",
        endpoint_url=DYNAMO_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    import contextlib

    with contextlib.suppress(Exception):
        ddb.delete_table(TableName=table_name)

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

    os.environ["HIVE_TABLE_NAME"] = table_name
    from hive.storage import HiveStorage

    storage = HiveStorage(
        table_name=table_name,
        region="us-east-1",
        endpoint_url=DYNAMO_ENDPOINT,
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )

    oauth_client = OAuthClient(client_name="MCP Test Client")
    storage.put_client(oauth_client)

    now = datetime.now(timezone.utc)
    token = Token(
        client_id=oauth_client.client_id,
        scope="memories:read memories:write",
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    storage.put_token(token)
    jwt_str = issue_jwt(token)
    return jwt_str


@pytest.mark.asyncio
class TestMCPTools:
    async def test_remember_and_recall(self, setup):
        from hive.server import recall, remember

        jwt = setup
        ctx = _make_context(jwt)
        result = await remember(key="greeting", value="Hello, Hive!", tags=["test"], ctx=ctx)
        assert "greeting" in result

        recalled = await recall(key="greeting", ctx=ctx)
        assert recalled == "Hello, Hive!"

    async def test_forget(self, setup):
        from fastmcp.exceptions import ToolError

        from hive.server import forget, recall, remember

        jwt = setup
        ctx = _make_context(jwt)
        await remember(key="temp", value="ephemeral", ctx=ctx)
        result = await forget(key="temp", ctx=ctx)
        assert "temp" in result

        with pytest.raises(ToolError):
            await recall(key="temp", ctx=ctx)

    async def test_list_memories(self, setup):
        from hive.server import list_memories, remember

        jwt = setup
        ctx = _make_context(jwt)
        await remember(key="list-a", value="A", tags=["listtest"], ctx=ctx)
        await remember(key="list-b", value="B", tags=["listtest"], ctx=ctx)

        result = await list_memories(tag="listtest", ctx=ctx)
        keys = [m["key"] for m in result["items"]]
        assert "list-a" in keys
        assert "list-b" in keys

    async def test_summarize_context(self, setup):
        from hive.server import remember, summarize_context

        jwt = setup
        ctx = _make_context(jwt)
        await remember(key="s1", value="Summary value 1", tags=["summary"], ctx=ctx)
        await remember(key="s2", value="Summary value 2", tags=["summary"], ctx=ctx)

        result = await summarize_context(topic="summary", ctx=ctx)
        assert "summary" in result.lower()
        assert "s1" in result or "s2" in result
