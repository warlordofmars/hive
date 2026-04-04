# Copyright (c) 2026 John Carter. All rights reserved.
"""
Shared e2e fixtures.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets

import httpx
import pytest

API_URL = os.environ.get("HIVE_API_URL", "")


@pytest.fixture(scope="session")
async def live_token() -> str:
    """Issue a fresh access token via DCR + PKCE against the deployed API."""
    if not API_URL:
        pytest.skip("HIVE_API_URL not set")

    async with httpx.AsyncClient(base_url=API_URL) as http:
        reg = await http.post(
            "/oauth/register",
            json={"client_name": "E2E Session Client", "redirect_uris": ["http://localhost/cb"]},
        )
        reg.raise_for_status()
        client_id = reg.json()["client_id"]

        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

        auth = await http.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "http://localhost/cb",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        location = auth.headers.get("location", "")
        if "accounts.google.com" in location:
            pytest.skip("Google OAuth required — cannot complete token flow in CI without bypass")
        code = location.split("code=")[1].split("&")[0]

        token_resp = await http.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost/cb",
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        token_resp.raise_for_status()
        return token_resp.json()["access_token"]


def issue_token_sync() -> str:
    """Synchronous version for use in non-async fixtures."""
    if not API_URL:
        pytest.skip("HIVE_API_URL not set")

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    with httpx.Client(base_url=API_URL, follow_redirects=False) as http:
        reg = http.post(
            "/oauth/register",
            json={"client_name": "E2E UI Client", "redirect_uris": ["http://localhost/cb"]},
        )
        reg.raise_for_status()
        client_id = reg.json()["client_id"]

        auth = http.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "http://localhost/cb",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        location = auth.headers.get("location", "")
        if "accounts.google.com" in location:
            pytest.skip("Google OAuth required — cannot complete token flow in CI without bypass")
        code = location.split("code=")[1].split("&")[0]

        token_resp = http.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost/cb",
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        token_resp.raise_for_status()
        return token_resp.json()["access_token"]
