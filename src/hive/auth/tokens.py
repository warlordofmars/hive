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

from jose import JWTError, jwt

from hive.models import Token
from hive.storage import HiveStorage

JWT_ALGORITHM = "HS256"
ISSUER = os.environ.get("HIVE_ISSUER", "https://hive.example.com")


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
    """Encode a Token record as a signed JWT."""
    payload = {
        "iss": ISSUER,
        "sub": token.client_id,
        "jti": token.jti,
        "scope": token.scope,
        "iat": int(token.issued_at.timestamp()),
        "exp": int(token.expires_at.timestamp()),
        "token_type": token.token_type.value,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_jwt(token_str: str) -> dict:
    """Decode and verify a JWT. Raises JWTError on failure."""
    return jwt.decode(token_str, _jwt_secret(), algorithms=[JWT_ALGORITHM], issuer=ISSUER)


def validate_bearer_token(authorization_header: str | None, storage: HiveStorage) -> Token:
    """
    Validate a Bearer token from an Authorization header.

    Returns the Token record if valid.
    Raises ValueError with a descriptive message on any failure.
    """
    if not authorization_header:
        raise ValueError("Missing Authorization header")
    parts = authorization_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ValueError("Authorization header must be 'Bearer <token>'")

    raw_token = parts[1]

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
