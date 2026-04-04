# Copyright (c) 2026 John Carter. All rights reserved.
"""
Integration tests for the OAuth 2.1 authorization flow.
Requires DYNAMODB_ENDPOINT env var (DynamoDB Local).
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets

import pytest

DYNAMO_ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT")

pytestmark = pytest.mark.skipif(
    not DYNAMO_ENDPOINT,
    reason="DYNAMODB_ENDPOINT not set — skipping integration tests",
)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from hive.api.main import app

    return TestClient(app, follow_redirects=False)


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class TestDCR:
    def test_register_public_client(self, client):
        resp = client.post(
            "/oauth/register",
            json={"client_name": "Test Agent", "redirect_uris": ["http://localhost/cb"]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["client_id"]
        assert data["client_secret"] is None

    def test_register_confidential_client(self, client):
        resp = client.post(
            "/oauth/register",
            json={
                "client_name": "Server App",
                "token_endpoint_auth_method": "client_secret_post",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["client_secret"] is not None

    def test_invalid_grant_type(self, client):
        resp = client.post(
            "/oauth/register",
            json={"client_name": "Bad", "grant_types": ["password"]},
        )
        assert resp.status_code == 400


class TestAuthorizationCodeFlow:
    def test_full_pkce_flow(self, client):
        # 1. Register client
        reg = client.post(
            "/oauth/register",
            json={
                "client_name": "PKCE Client",
                "redirect_uris": ["http://localhost/cb"],
            },
        )
        assert reg.status_code == 201
        client_id = reg.json()["client_id"]

        # 2. Authorization request
        verifier, challenge = _pkce_pair()
        auth_resp = client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "http://localhost/cb",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert auth_resp.status_code == 302
        location = auth_resp.headers["location"]
        code = location.split("code=")[1].split("&")[0]
        assert code

        # 3. Token exchange
        token_resp = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost/cb",
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        assert token_resp.status_code == 200
        token_data = token_resp.json()
        assert token_data["access_token"]
        assert token_data["refresh_token"]
        assert token_data["token_type"] == "Bearer"

    def test_invalid_pkce_verifier_rejected(self, client):
        reg = client.post(
            "/oauth/register",
            json={"client_name": "PKCE Fail", "redirect_uris": ["http://localhost/cb"]},
        )
        client_id = reg.json()["client_id"]

        _, challenge = _pkce_pair()
        auth_resp = client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "http://localhost/cb",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        code = auth_resp.headers["location"].split("code=")[1]

        # Wrong verifier
        token_resp = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost/cb",
                "client_id": client_id,
                "code_verifier": "wrong-verifier",
            },
        )
        assert token_resp.status_code == 400
