# Copyright (c) 2026 John Carter. All rights reserved.
"""Unit tests for OAuth auth logic — fully mocked, no AWS deps."""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

from hive.auth.dcr import register_client
from hive.auth.tokens import decode_jwt, issue_jwt, validate_bearer_token
from hive.models import (
    ClientRegistrationRequest,
    Token,
)

os.environ.setdefault("HIVE_TABLE_NAME", "hive-unit-auth")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("HIVE_JWT_SECRET", "unit-test-secret")
os.environ.pop("DYNAMODB_ENDPOINT", None)

# ---------------------------------------------------------------------------
# DCR tests
# ---------------------------------------------------------------------------


class TestDCR:
    def _storage(self, client=None):
        s = MagicMock()
        s.get_client.return_value = client
        return s

    def test_register_public_client(self):
        storage = self._storage()
        req = ClientRegistrationRequest(
            client_name="Test Agent",
            redirect_uris=["http://localhost/cb"],
        )
        resp = register_client(req, storage)
        assert resp.client_id
        assert resp.client_secret is None
        assert resp.token_endpoint_auth_method == "none"
        storage.put_client.assert_called_once()

    def test_register_confidential_client(self):
        storage = self._storage()
        req = ClientRegistrationRequest(
            client_name="Server App",
            token_endpoint_auth_method="client_secret_post",
        )
        resp = register_client(req, storage)
        assert resp.client_secret is not None
        assert len(resp.client_secret) > 20

    def test_unsupported_grant_type_raises(self):
        storage = self._storage()
        req = ClientRegistrationRequest(
            client_name="Bad",
            grant_types=["password"],
        )
        with pytest.raises(ValueError, match="Unsupported grant_types"):
            register_client(req, storage)

    def test_unsupported_auth_method_raises(self):
        storage = self._storage()
        req = ClientRegistrationRequest(
            client_name="Bad",
            token_endpoint_auth_method="private_key_jwt",
        )
        with pytest.raises(ValueError, match="Unsupported token_endpoint_auth_method"):
            register_client(req, storage)


# ---------------------------------------------------------------------------
# Token tests
# ---------------------------------------------------------------------------


def _make_token(**kwargs) -> Token:
    now = datetime.now(timezone.utc)
    return Token(
        client_id="client-1",
        scope="memories:read",
        issued_at=now,
        expires_at=now + timedelta(hours=1),
        **kwargs,
    )


class TestTokenIssuance:
    def test_issue_and_decode(self):
        t = _make_token()
        jwt_str = issue_jwt(t)
        claims = decode_jwt(jwt_str)
        assert claims["jti"] == t.jti
        assert claims["sub"] == t.client_id
        assert claims["scope"] == t.scope

    def test_tampered_jwt_raises(self):
        from jose import JWTError

        t = _make_token()
        jwt_str = issue_jwt(t)
        tampered = jwt_str[:-4] + "XXXX"
        with pytest.raises(JWTError):
            decode_jwt(tampered)


class TestValidateBearerToken:
    def _storage_with_token(self, token: Token):
        s = MagicMock()
        s.get_token.return_value = token
        return s

    def test_valid_token(self):
        t = _make_token()
        storage = self._storage_with_token(t)
        jwt_str = issue_jwt(t)
        result = validate_bearer_token(f"Bearer {jwt_str}", storage)
        assert result.jti == t.jti

    def test_missing_header_raises(self):
        storage = MagicMock()
        with pytest.raises(ValueError, match="Missing"):
            validate_bearer_token(None, storage)

    def test_bad_scheme_raises(self):
        storage = MagicMock()
        with pytest.raises(ValueError, match="Bearer"):
            validate_bearer_token("Basic abc", storage)

    def test_revoked_token_raises(self):
        t = _make_token(revoked=True)
        storage = self._storage_with_token(t)
        jwt_str = issue_jwt(t)
        with pytest.raises(ValueError, match="revoked"):
            validate_bearer_token(f"Bearer {jwt_str}", storage)

    def test_expired_token_raises(self):
        now = datetime.now(timezone.utc)
        t = Token(
            client_id="c1",
            scope="s",
            issued_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
        # JWT exp check will fire before DynamoDB lookup for expired tokens

        jwt_str = issue_jwt(t)
        storage = MagicMock()
        with pytest.raises(ValueError):
            validate_bearer_token(f"Bearer {jwt_str}", storage)

    def test_token_not_in_storage_raises(self):
        t = _make_token()
        storage = MagicMock()
        storage.get_token.return_value = None
        jwt_str = issue_jwt(t)
        with pytest.raises(ValueError, match="not found"):
            validate_bearer_token(f"Bearer {jwt_str}", storage)


# ---------------------------------------------------------------------------
# OAuth 2.1 endpoint tests (FastAPI routes in auth/oauth.py)
# ---------------------------------------------------------------------------


def _create_table(table_name: str = "hive-unit-auth") -> None:
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


def _pkce_pair() -> tuple[str, str]:
    """Return (verifier, S256-challenge) pair."""
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


@pytest.fixture()
def oauth_client():
    """moto-backed app with a registered OAuth client that has a redirect_uri."""
    with mock_aws():
        _create_table()
        from fastapi.testclient import TestClient

        from hive.api.main import app
        from hive.auth.oauth import get_storage
        from hive.models import OAuthClient
        from hive.storage import HiveStorage

        storage = HiveStorage(table_name="hive-unit-auth", region="us-east-1")
        client = OAuthClient(
            client_name="Test OAuth App",
            redirect_uris=["https://app.example.com/cb"],
        )
        storage.put_client(client)

        app.dependency_overrides[get_storage] = lambda: storage
        tc = TestClient(app, raise_server_exceptions=False)
        yield tc, storage, client
        app.dependency_overrides.clear()


class TestOAuthDiscovery:
    def test_discovery_document(self, oauth_client):
        tc, *_ = oauth_client
        resp = tc.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200
        data = resp.json()
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "code_challenge_methods_supported" in data
        assert "S256" in data["code_challenge_methods_supported"]


class TestOAuthRegister:
    def test_register_public_client(self, oauth_client):
        tc, *_ = oauth_client
        resp = tc.post(
            "/oauth/register",
            json={
                "client_name": "My Agent",
                "redirect_uris": ["http://localhost/cb"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["client_id"]
        assert data["client_secret"] is None

    def test_register_invalid_grant_type_returns_400(self, oauth_client):
        tc, *_ = oauth_client
        resp = tc.post(
            "/oauth/register",
            json={"client_name": "Bad", "grant_types": ["password"]},
        )
        assert resp.status_code == 400


class TestOAuthAuthorize:
    def test_valid_authorize_redirects(self, oauth_client):
        tc, storage, client = oauth_client
        _, challenge = _pkce_pair()
        resp = tc.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client.client_id,
                "redirect_uri": "https://app.example.com/cb",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "xyz",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "code=" in location
        assert "state=xyz" in location

    def test_unknown_client_returns_400(self, oauth_client):
        tc, *_ = oauth_client
        _, challenge = _pkce_pair()
        resp = tc.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "no-such-client",
                "redirect_uri": "https://app.example.com/cb",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert resp.status_code == 400

    def test_unregistered_redirect_uri_returns_400(self, oauth_client):
        tc, storage, client = oauth_client
        _, challenge = _pkce_pair()
        resp = tc.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client.client_id,
                "redirect_uri": "https://evil.com/steal",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert resp.status_code == 400

    def test_missing_pkce_returns_400(self, oauth_client):
        tc, storage, client = oauth_client
        resp = tc.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client.client_id,
                "redirect_uri": "https://app.example.com/cb",
                "code_challenge": "",
            },
        )
        assert resp.status_code == 400

    def test_unsupported_response_type_returns_400(self, oauth_client):
        tc, storage, client = oauth_client
        _, challenge = _pkce_pair()
        resp = tc.get(
            "/oauth/authorize",
            params={
                "response_type": "token",
                "client_id": client.client_id,
                "redirect_uri": "https://app.example.com/cb",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert resp.status_code == 400


class TestOAuthToken:
    def _get_auth_code(self, tc, storage, client) -> str:
        """Drive authorize endpoint and return the code."""
        verifier, challenge = _pkce_pair()
        resp = tc.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client.client_id,
                "redirect_uri": "https://app.example.com/cb",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        location = resp.headers["location"]
        code = location.split("code=")[1].split("&")[0]
        return code, verifier

    def test_authorization_code_grant(self, oauth_client):
        tc, storage, client = oauth_client
        code, verifier = self._get_auth_code(tc, storage, client)
        resp = tc.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://app.example.com/cb",
                "client_id": client.client_id,
                "code_verifier": verifier,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["token_type"] == "Bearer"

    def test_invalid_pkce_verifier_rejected(self, oauth_client):
        tc, storage, client = oauth_client
        code, _ = self._get_auth_code(tc, storage, client)
        resp = tc.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://app.example.com/cb",
                "client_id": client.client_id,
                "code_verifier": "wrong-verifier",
            },
        )
        assert resp.status_code == 400

    def test_refresh_token_grant(self, oauth_client):
        tc, storage, client = oauth_client
        # First do a full auth code flow to get a refresh token
        code, verifier = self._get_auth_code(tc, storage, client)
        token_resp = tc.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://app.example.com/cb",
                "client_id": client.client_id,
                "code_verifier": verifier,
            },
        )
        refresh_token = token_resp.json()["refresh_token"]

        resp = tc.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client.client_id,
                "refresh_token": refresh_token,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["access_token"]

    def test_missing_client_id_returns_400(self, oauth_client):
        tc, *_ = oauth_client
        resp = tc.post(
            "/oauth/token",
            data={"grant_type": "authorization_code"},
        )
        assert resp.status_code == 400

    def test_unsupported_grant_type_returns_400(self, oauth_client):
        tc, storage, client = oauth_client
        resp = tc.post(
            "/oauth/token",
            data={"grant_type": "password", "client_id": client.client_id},
        )
        assert resp.status_code == 400

    def test_already_used_code_rejected(self, oauth_client):
        tc, storage, client = oauth_client
        code, verifier = self._get_auth_code(tc, storage, client)
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://app.example.com/cb",
            "client_id": client.client_id,
            "code_verifier": verifier,
        }
        tc.post("/oauth/token", data=data)  # first use — succeeds
        resp = tc.post("/oauth/token", data=data)  # second use — rejected
        assert resp.status_code == 400


class TestOAuthRevoke:
    def test_revoke_valid_token_returns_200(self, oauth_client):
        tc, storage, client = oauth_client
        # Issue a token directly
        now = datetime.now(timezone.utc)
        token = Token(
            client_id=client.client_id,
            scope="memories:read",
            issued_at=now,
            expires_at=now + timedelta(hours=1),
        )
        storage.put_token(token)
        jwt_str = issue_jwt(token)
        resp = tc.post("/oauth/revoke", data={"token": jwt_str})
        assert resp.status_code == 200

    def test_revoke_invalid_token_still_returns_200(self, oauth_client):
        """RFC 7009: revocation endpoint always returns 200."""
        tc, *_ = oauth_client
        resp = tc.post("/oauth/revoke", data={"token": "not-a-jwt"})
        assert resp.status_code == 200
