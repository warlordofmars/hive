# Copyright (c) 2026 John Carter. All rights reserved.
"""
Token issuance and validation for Hive OAuth 2.1.

Tokens are opaque JTIs stored in DynamoDB.  We use JWT only as a signed
envelope so Resource Servers can validate without a DynamoDB lookup on
every request — but we still persist tokens for revocation support.
"""

from __future__ import annotations

import functools
import os
import secrets
from typing import Any

from jose import JWTError, jwt

from hive.models import Token
from hive.storage import HiveStorage

JWT_ALGORITHM = "HS256"
# Normalize once at the source: a trailing slash on HIVE_ISSUER would otherwise
# produce double-slash discovery URLs (e.g. ".../oauth-authorization-server"
# endpoints built as f"{ISSUER}/oauth/token"), which trips strict clients (#647).
ISSUER = os.environ.get("HIVE_ISSUER", "https://hive.example.com").rstrip("/")


@functools.lru_cache(maxsize=1)
def _jwt_secret() -> str:
    """Return the JWT signing secret.

    Priority:
    1. HIVE_JWT_SECRET env var (tests / local dev)
    2. SSM Parameter /hive/jwt-secret (Lambda runtime)
    3. Random fallback (single-process local dev only)
    """
    if secret := os.environ.get("HIVE_JWT_SECRET"):
        return secret
    try:
        import boto3

        param_name = os.environ.get("HIVE_JWT_SECRET_PARAM", "/hive/jwt-secret")
        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
        return resp["Parameter"]["Value"]
    except Exception:
        return secrets.token_hex(32)


def issue_jwt(token: Token) -> str:
    """Encode a Token record as a signed JWT.

    Workspace claims (#491) are included only when the token carries them —
    legacy tokens minted before the workspace cutover stay claim-free and are
    resolved via :func:`resolve_workspace_scope` at validation time.
    """
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "sub": token.client_id,
        "jti": token.jti,
        "scope": token.scope,
        "iat": int(token.issued_at.timestamp()),
        "exp": int(token.expires_at.timestamp()),
        "token_type": token.token_type.value,
    }
    if token.workspace_id is not None:
        payload["workspace_id"] = token.workspace_id
    if token.workspace_role is not None:
        payload["workspace_role"] = token.workspace_role
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_jwt(token_str: str) -> dict[str, Any]:
    """Decode and verify a JWT. Raises JWTError on failure."""
    return jwt.decode(token_str, _jwt_secret(), algorithms=[JWT_ALGORITHM], issuer=ISSUER)


@functools.lru_cache(maxsize=1)
def _origin_verify_secret() -> str | None:
    """Return the expected X-Origin-Verify header value, or None if not configured.

    None disables the check (local dev / non-prod without WAF).
    """
    if secret := os.environ.get("HIVE_ORIGIN_VERIFY_SECRET"):
        return secret
    param_name = os.environ.get("HIVE_ORIGIN_VERIFY_PARAM")
    if not param_name:
        return None
    try:
        import boto3

        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=param_name, WithDecryption=False)
        return resp["Parameter"]["Value"]
    except Exception:
        return None


MGMT_JWT_TTL_SECONDS = 28800  # 8 hours


def issue_mgmt_jwt(
    user: Any,
    workspace_id: str | None = None,
    workspace_role: str | None = None,
) -> str:
    """Issue a short-lived management session JWT for a human user.

    Uses typ=mgmt to distinguish from MCP access tokens so neither can be
    replayed as the other.  ``workspace_id`` / ``workspace_role`` (#491) scope
    the session to one workspace; the UI re-issues the JWT via
    ``POST /api/account/workspace-token`` to switch.
    """
    import time

    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "sub": user.user_id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "typ": "mgmt",
        "iat": now,
        "exp": now + MGMT_JWT_TTL_SECONDS,
    }
    if workspace_id is not None:
        payload["workspace_id"] = workspace_id
    if workspace_role is not None:
        payload["workspace_role"] = workspace_role
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_mgmt_jwt(token_str: str) -> dict[str, Any]:
    """Decode a management JWT and enforce typ=mgmt.

    Raises JWTError if the token is invalid, expired, or not a management token
    (prevents MCP access tokens from being replayed on management endpoints).
    """
    claims = jwt.decode(token_str, _jwt_secret(), algorithms=[JWT_ALGORITHM], issuer=ISSUER)
    if claims.get("typ") != "mgmt":
        raise JWTError("Not a management token")
    return claims


_API_KEY_PREFIX = "hive_sk_"
# client_id prefix of the synthetic Token minted for API-key callers below.
_API_KEY_PREFIX_CLIENT = "apikey:"


def validate_bearer_token(authorization_header: str | None, storage: HiveStorage) -> Token:
    """
    Validate a Bearer token from an Authorization header.

    Supports two token types:
    - hive_sk_... API keys: looked up by SHA-256 hash in DynamoDB
    - JWT access tokens: validated cryptographically then confirmed in DynamoDB

    Returns a Token record (real or synthetic) if valid.
    Raises ValueError with a descriptive message on any failure.
    """
    import hashlib
    from datetime import timedelta

    if not authorization_header:
        raise ValueError("Missing Authorization header")
    parts = authorization_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ValueError("Authorization header must be 'Bearer <token>'")

    raw_token = parts[1]

    # --- API key path ---
    if raw_token.startswith(_API_KEY_PREFIX):
        key_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        api_key = storage.get_api_key_by_hash(key_hash)
        if api_key is None:
            raise ValueError("API key not found")
        if not api_key.is_valid:
            raise ValueError("API key has been revoked or has expired")
        # Synthesize a Token so callers need no changes
        return Token(
            jti=f"{_API_KEY_PREFIX_CLIENT}{api_key.key_id}",
            client_id=f"{_API_KEY_PREFIX_CLIENT}{api_key.key_id}",
            scope=api_key.scope,
            issued_at=api_key.created_at,
            expires_at=api_key.expires_at or (api_key.created_at + timedelta(days=3650)),
        )

    # --- JWT path ---
    try:
        claims = decode_jwt(raw_token)
    except JWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc

    jti = claims.get("jti")
    if not jti:
        raise ValueError("Token missing jti claim")

    token = storage.get_token(jti)
    if token is None:
        raise ValueError("Token not found")

    if not token.is_valid:
        raise ValueError("Token has been revoked or has expired")

    return token


# ---------------------------------------------------------------------------
# Workspace scope resolution (#491)
# ---------------------------------------------------------------------------


def resolve_client_workspace(storage: HiveStorage, client: Any) -> tuple[str | None, str | None]:
    """Resolve the (workspace_id, workspace_role) an OAuth client is bound to.

    Resolution order:

    1. Explicit ``client.workspace_id`` binding (DCR-provided or stamped at
       the OAuth callback / migration).  The role comes from the owner's
       membership record; ``None`` when the owner is unset or no longer a
       member — callers that mint new tokens must fail closed on that.
    2. Legacy fallback: the owner's Personal workspace (pre-migration
       clients).  The owner of a Personal workspace is always its ``owner``.
    3. ``(None, None)`` when the client is unbound to both a workspace and a
       user — pre-#648 legacy clients.
    """
    from hive.models import WorkspaceRole

    if client.workspace_id is not None:
        if client.owner_user_id is None:
            return client.workspace_id, None
        member = storage.get_workspace_member(client.workspace_id, client.owner_user_id)
        return client.workspace_id, (member.role.value if member else None)
    if client.owner_user_id is None:
        return None, None
    workspace = storage.get_personal_workspace(client.owner_user_id)
    if workspace is None:
        return None, None
    return workspace.workspace_id, WorkspaceRole.owner.value


def resolve_workspace_scope(storage: HiveStorage, token: Token) -> tuple[str | None, str | None]:
    """Resolve the (workspace_id, workspace_role) a validated token is scoped to.

    Claim-first: tokens minted after the workspace cutover (#491) carry the
    scope directly and cost no extra lookups.  Synthetic API-key tokens
    resolve to the key owner's Personal workspace (API keys are personal
    credentials).  Legacy OAuth tokens (no claim) fall back to the issuing
    client's binding via :func:`resolve_client_workspace`; a fully
    unresolvable caller yields ``(None, None)`` and downstream enforcement
    fails closed on any workspace-stamped resource.
    """
    from hive.models import WorkspaceRole

    if token.workspace_id is not None:
        return token.workspace_id, token.workspace_role
    if token.client_id.startswith(_API_KEY_PREFIX_CLIENT):
        api_key = storage.get_api_key_by_id(token.client_id[len(_API_KEY_PREFIX_CLIENT) :])
        if api_key is None:
            return None, None
        workspace = storage.get_personal_workspace(api_key.owner_user_id)
        if workspace is None:
            return None, None
        return workspace.workspace_id, WorkspaceRole.owner.value
    client = storage.get_client(token.client_id)
    if client is None:
        return None, None
    return resolve_client_workspace(storage, client)
