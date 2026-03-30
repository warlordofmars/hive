"""Unit tests for OAuth auth logic — fully mocked, no AWS deps."""

from __future__ import annotations

import hashlib
import base64
import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from hive.auth.dcr import register_client, SUPPORTED_GRANT_TYPES
from hive.auth.tokens import decode_jwt, issue_jwt, validate_bearer_token
from hive.models import (
    ClientRegistrationRequest,
    OAuthClient,
    OAuthClientType,
    Token,
    TokenType,
)


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
        from jose import JWTError

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
