# Copyright (c) 2026 John Carter. All rights reserved.
"""
Integration test for #648 — the production Google OAuth callback must bind the
authenticated user to the DCR client.

This exercises the **real** callback path (``hive.auth.oauth.google_callback``),
*not* the ``HIVE_BYPASS_GOOGLE_AUTH`` shortcut. The bug lived precisely in that
divergence: e2e/CI ran in bypass mode (the one path that bound the user), so
tests stayed green while production clients were left with ``owner_user_id=None``
and ``list_memories`` / ``summarize_context`` permanently failed.

Only Google's network calls (token exchange + ID-token verification) are mocked;
storage, user upsert, client binding, token issuance and the MCP tools all run
against DynamoDB Local.
"""

from __future__ import annotations

import contextlib
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

DYNAMO_ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT")

pytestmark = pytest.mark.skipif(
    not DYNAMO_ENDPOINT,
    reason="DYNAMODB_ENDPOINT not set — skipping integration tests",
)


def _make_context(token_str: str):
    """Build a minimal MCP Context carrying an Authorization header."""
    ctx = MagicMock()
    ctx.request_context = MagicMock()
    ctx.request_context.meta = {"Authorization": f"Bearer {token_str}"}
    return ctx


@pytest.fixture(scope="module")
def google_oauth_setup():
    """DynamoDB Local table (with UserEmailIndex), created once per module.

    Module-scoped to match the other integration fixtures here and avoid
    repeated delete/create churn on the same table name; the tests use distinct
    clients/users/tags so they don't collide on the shared table.
    """
    import boto3

    table_name = "hive-oauth-user-binding"
    ddb = boto3.client(
        "dynamodb",
        endpoint_url=DYNAMO_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
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

    previous_table_name = os.environ.get("HIVE_TABLE_NAME")
    os.environ["HIVE_TABLE_NAME"] = table_name
    try:
        from hive.storage import HiveStorage

        storage = HiveStorage(
            table_name=table_name,
            region="us-east-1",
            endpoint_url=DYNAMO_ENDPOINT,
            aws_access_key_id="local",
            aws_secret_access_key="local",
        )
        yield storage
    finally:
        if previous_table_name is None:
            os.environ.pop("HIVE_TABLE_NAME", None)
        else:
            os.environ["HIVE_TABLE_NAME"] = previous_table_name


@pytest.mark.asyncio
async def test_real_google_callback_binds_user_and_unblocks_tools(google_oauth_setup):
    """End-to-end proof of the #648 fix: completing the real Google OAuth
    callback binds the verified user to the DCR client, and the two tools that
    were broken in production then succeed."""
    from hive.auth import oauth
    from hive.auth.tokens import issue_jwt
    from hive.models import OAuthClient, Token
    from hive.server import list_memories, remember, summarize_context

    storage = google_oauth_setup

    # A freshly DCR-registered public client — owner_user_id is None, exactly as
    # a real MCP client looks in production before any user logs in.
    client = OAuthClient(
        client_name="Real Google MCP Client",
        redirect_uris=["https://app.example.com/cb"],
    )
    storage.put_client(client)
    assert storage.get_client(client.client_id).owner_user_id is None

    # /oauth/authorize stores PKCE state before redirecting the browser to
    # Google; recreate that record so the callback has something to consume.
    pending = storage.create_pending_auth(
        client_id=client.client_id,
        redirect_uri="https://app.example.com/cb",
        scope="memories:read memories:write",
        code_challenge="challenge-value",
        code_challenge_method="S256",
        original_state="orig-state",
    )

    # Drive the REAL callback. Only Google's network calls are mocked.
    fake_claims = {"email": "prod-user@example.com", "email_verified": True, "sub": "g-sub-1"}
    with (
        patch("hive.auth.google.exchange_google_code", return_value="fake-id-token"),
        patch("hive.auth.google.verify_google_id_token", return_value=fake_claims),
        patch("hive.auth.google.is_email_allowed", return_value=True),
        patch("hive.auth.google.is_admin_email", return_value=False),
    ):
        resp = await oauth.google_callback(storage=storage, code="g-code", state=pending.state)

    assert resp.status_code == 302
    assert "code=" in resp.headers["location"]

    # #648: the callback must have upserted the user and bound it to the client.
    bound = storage.get_client(client.client_id)
    assert bound.owner_user_id is not None
    user = storage.get_user_by_email("prod-user@example.com")
    assert user is not None
    assert bound.owner_user_id == user.user_id

    # The bound client can now obtain a token and the two tools that previously
    # failed with "Client is not associated with a user account" must succeed.
    now = datetime.now(timezone.utc)
    token = Token(
        client_id=client.client_id,
        scope="memories:read memories:write",
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    storage.put_token(token)
    ctx = _make_context(issue_jwt(token))

    await remember(key="binding-proof", value="bound to user", tags=["issue648"], ctx=ctx)

    listed = await list_memories(tag="issue648", ctx=ctx)
    keys = [m["key"] for m in listed.structured_content["items"]]
    assert "binding-proof" in keys

    summary = await summarize_context(topic="issue648", ctx=ctx)
    assert "binding-proof" in summary.content[0].text


@pytest.mark.asyncio
async def test_callback_rejects_second_user_on_owned_client(google_oauth_setup):
    """Security guard for #648: once a client is bound, a *different* Google
    user authenticating through the same client is refused with 403 and the
    original owner is left unchanged — preventing token issuance that would let
    the second user reach the first user's memory scope (client-only tokens)."""
    from fastapi import HTTPException

    from hive.auth import oauth
    from hive.models import OAuthClient

    storage = google_oauth_setup
    client = OAuthClient(
        client_name="Shared Client",
        redirect_uris=["https://app.example.com/cb"],
    )
    storage.put_client(client)

    async def _callback_as(email: str):
        pending = storage.create_pending_auth(
            client_id=client.client_id,
            redirect_uri="https://app.example.com/cb",
            scope="memories:read memories:write",
            code_challenge="challenge-value",
            code_challenge_method="S256",
            original_state="orig-state",
        )
        claims = {"email": email, "email_verified": True, "sub": email}
        with (
            patch("hive.auth.google.exchange_google_code", return_value="fake-id-token"),
            patch("hive.auth.google.verify_google_id_token", return_value=claims),
            patch("hive.auth.google.is_email_allowed", return_value=True),
            patch("hive.auth.google.is_admin_email", return_value=False),
        ):
            return await oauth.google_callback(storage=storage, code="g-code", state=pending.state)

    resp = await _callback_as("owner@example.com")
    assert resp.status_code == 302
    owner_id = storage.get_client(client.client_id).owner_user_id
    assert owner_id is not None

    with pytest.raises(HTTPException) as exc:
        await _callback_as("intruder@example.com")
    assert exc.value.status_code == 403
    # The intruder never displaces the owner.
    assert storage.get_client(client.client_id).owner_user_id == owner_id
