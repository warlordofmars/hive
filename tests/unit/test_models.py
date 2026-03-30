"""Unit tests for Hive data models — no AWS deps."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from hive.models import (
    AuthorizationCode,
    Memory,
    OAuthClient,
    OAuthClientType,
    Token,
    TokenType,
)


class TestMemory:
    def test_default_fields(self):
        m = Memory(key="test", value="hello", owner_client_id="client-1")
        assert m.memory_id  # auto-generated UUID
        assert m.tags == []
        assert m.created_at.tzinfo == timezone.utc

    def test_to_dynamo_meta(self):
        m = Memory(key="foo", value="bar", tags=["t1"], owner_client_id="c1")
        item = m.to_dynamo_meta()
        assert item["PK"] == f"MEMORY#{m.memory_id}"
        assert item["SK"] == "META"
        assert item["key"] == "foo"
        assert item["value"] == "bar"
        assert item["tags"] == ["t1"]
        assert item["GSI1PK"] == "KEY#foo"

    def test_to_dynamo_tag_items(self):
        m = Memory(key="foo", value="bar", tags=["alpha", "beta"], owner_client_id="c1")
        tag_items = m.to_dynamo_tag_items()
        assert len(tag_items) == 2
        sks = {item["SK"] for item in tag_items}
        assert sks == {"TAG#alpha", "TAG#beta"}
        for item in tag_items:
            assert item["GSI2PK"] in {"TAG#alpha", "TAG#beta"}

    def test_from_dynamo_roundtrip(self):
        m = Memory(key="k", value="v", tags=["x"], owner_client_id="c1")
        item = m.to_dynamo_meta()
        m2 = Memory.from_dynamo(item)
        assert m2.memory_id == m.memory_id
        assert m2.key == m.key
        assert m2.value == m.value
        assert m2.tags == m.tags

    def test_no_tags_produces_no_tag_items(self):
        m = Memory(key="k", value="v", owner_client_id="c1")
        assert m.to_dynamo_tag_items() == []


class TestOAuthClient:
    def test_defaults(self):
        c = OAuthClient(client_name="Test App")
        assert c.client_id  # UUID
        assert c.client_type == OAuthClientType.public
        assert c.client_secret is None

    def test_to_dynamo(self):
        c = OAuthClient(client_name="App", client_secret="secret")
        item = c.to_dynamo()
        assert item["PK"] == f"CLIENT#{c.client_id}"
        assert item["SK"] == "META"
        assert item["client_secret"] == "secret"

    def test_from_dynamo_roundtrip(self):
        c = OAuthClient(client_name="App")
        item = c.to_dynamo()
        c2 = OAuthClient.from_dynamo(item)
        assert c2.client_id == c.client_id
        assert c2.client_name == c.client_name


class TestToken:
    def _make_token(self, **kwargs) -> Token:
        now = datetime.now(timezone.utc)
        return Token(
            client_id="c1",
            scope="memories:read",
            issued_at=now,
            expires_at=now + timedelta(hours=1),
            **kwargs,
        )

    def test_valid_token(self):
        t = self._make_token()
        assert t.is_valid
        assert not t.is_expired

    def test_expired_token(self):
        now = datetime.now(timezone.utc)
        t = Token(
            client_id="c1",
            scope="s",
            issued_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
        assert t.is_expired
        assert not t.is_valid

    def test_revoked_token(self):
        t = self._make_token(revoked=True)
        assert not t.is_valid

    def test_to_dynamo_ttl(self):
        t = self._make_token()
        item = t.to_dynamo()
        assert item["PK"] == f"TOKEN#{t.jti}"
        assert "ttl" in item
        assert isinstance(item["ttl"], int)

    def test_from_dynamo_roundtrip(self):
        t = self._make_token()
        item = t.to_dynamo()
        t2 = Token.from_dynamo(item)
        assert t2.jti == t.jti
        assert t2.client_id == t.client_id


class TestAuthorizationCode:
    def test_to_dynamo_ttl(self):
        now = datetime.now(timezone.utc)
        code = AuthorizationCode(
            client_id="c1",
            redirect_uri="http://localhost/cb",
            scope="s",
            code_challenge="abc",
            expires_at=now + timedelta(minutes=5),
        )
        item = code.to_dynamo()
        assert item["PK"] == f"AUTHCODE#{code.code}"
        assert item["ttl"] == int(code.expires_at.timestamp())

    def test_from_dynamo_roundtrip(self):
        now = datetime.now(timezone.utc)
        code = AuthorizationCode(
            client_id="c1",
            redirect_uri="http://localhost/cb",
            scope="s",
            code_challenge="abc",
            expires_at=now + timedelta(minutes=5),
        )
        item = code.to_dynamo()
        code2 = AuthorizationCode.from_dynamo(item)
        assert code2.code == code.code
        assert code2.code_challenge == code.code_challenge
