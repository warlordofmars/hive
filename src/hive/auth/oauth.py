"""
OAuth 2.1 Authorization Server endpoints for Hive.

Endpoints (mounted at /oauth in FastAPI):
  GET  /oauth/authorize   — show consent / redirect with code
  POST /oauth/token       — exchange code or refresh token for tokens
  POST /oauth/revoke      — revoke a token
  GET  /oauth/jwks        — public key set (HS256 → symmetric, for info only)
  GET  /.well-known/oauth-authorization-server  — discovery document
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from hive.auth.dcr import register_client
from hive.auth.tokens import ISSUER, issue_jwt
from hive.models import (
    ActivityEvent,
    ClientRegistrationRequest,
    EventType,
    TokenResponse,
)
from hive.storage import HiveStorage

router = APIRouter(tags=["oauth"])


# ---------------------------------------------------------------------------
# Dependency: shared storage instance
# ---------------------------------------------------------------------------


def get_storage() -> HiveStorage:  # noqa: D401
    return HiveStorage()


# ---------------------------------------------------------------------------
# Discovery document
# ---------------------------------------------------------------------------


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
async def oauth_metadata(request: Request) -> JSONResponse:
    base = str(request.base_url).rstrip("/")
    return JSONResponse(
        {
            "issuer": ISSUER,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "revocation_endpoint": f"{base}/oauth/revoke",
            "registration_endpoint": f"{base}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": [
                "none",
                "client_secret_post",
                "client_secret_basic",
            ],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["memories:read", "memories:write"],
        }
    )


# ---------------------------------------------------------------------------
# Dynamic Client Registration
# ---------------------------------------------------------------------------


@router.post("/oauth/register", status_code=201)
async def register(
    req: ClientRegistrationRequest,
    storage: HiveStorage = Depends(get_storage),
) -> JSONResponse:
    try:
        resp = register_client(req, storage)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    storage.log_event(
        ActivityEvent(
            event_type=EventType.client_registered,
            client_id=resp.client_id,
            metadata={"client_name": resp.client_name},
        )
    )
    return JSONResponse(resp.model_dump(), status_code=201)


# ---------------------------------------------------------------------------
# Authorization endpoint
# ---------------------------------------------------------------------------


@router.get("/oauth/authorize")
async def authorize(
    response_type: str,
    client_id: str,
    redirect_uri: str,
    state: str = "",
    scope: str = "memories:read memories:write",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    storage: HiveStorage = Depends(get_storage),
) -> RedirectResponse:
    # Validate client
    client = storage.get_client(client_id)
    if client is None:
        raise HTTPException(status_code=400, detail="Unknown client_id")
    if redirect_uri not in client.redirect_uris:
        raise HTTPException(status_code=400, detail="redirect_uri not registered")
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Only response_type=code is supported")
    if not code_challenge:
        raise HTTPException(status_code=400, detail="PKCE code_challenge is required")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="Only code_challenge_method=S256 is supported")

    auth_code = storage.create_auth_code(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )

    params = {"code": auth_code.code}
    if state:
        params["state"] = state
    return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=302)


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------


def _verify_pkce(code_verifier: str, stored_challenge: str) -> bool:
    digest = hashlib.sha256(code_verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return secrets.compare_digest(computed, stored_challenge)


@router.post("/oauth/token")
async def token(
    grant_type: str = Form(...),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
    code_verifier: str | None = Form(None),
    refresh_token: str | None = Form(None),
    request: Request = None,  # type: ignore[assignment]
    storage: HiveStorage = Depends(get_storage),
) -> JSONResponse:
    # --- Client authentication ---
    # Try HTTP Basic first, then form params
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode()
            basic_client_id, basic_secret = decoded.split(":", 1)
            client_id = client_id or basic_client_id
            client_secret = client_secret or basic_secret
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Invalid Basic auth header") from exc

    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")

    client = storage.get_client(client_id)
    if client is None:
        raise HTTPException(status_code=401, detail="Unknown client")

    # Confidential clients must present their secret
    if client.client_secret and not secrets.compare_digest(
        client.client_secret, client_secret or ""
    ):
        raise HTTPException(status_code=401, detail="Invalid client_secret")

    # --- Grant type dispatch ---
    if grant_type == "authorization_code":
        if not code or not code_verifier or not redirect_uri:
            raise HTTPException(
                status_code=400, detail="code, code_verifier and redirect_uri are required"
            )

        auth_code = storage.get_auth_code(code)
        if auth_code is None or auth_code.used:
            raise HTTPException(status_code=400, detail="Invalid or already-used code")
        if auth_code.client_id != client_id:
            raise HTTPException(status_code=400, detail="code was not issued to this client")
        if auth_code.redirect_uri != redirect_uri:
            raise HTTPException(status_code=400, detail="redirect_uri mismatch")
        if datetime.now(timezone.utc) > auth_code.expires_at:
            raise HTTPException(status_code=400, detail="Authorization code has expired")
        if not _verify_pkce(code_verifier, auth_code.code_challenge):
            raise HTTPException(status_code=400, detail="PKCE verification failed")

        storage.mark_auth_code_used(code)
        access, refresh = storage.create_token_pair(client_id, auth_code.scope)

    elif grant_type == "refresh_token":
        if not refresh_token:
            raise HTTPException(status_code=400, detail="refresh_token is required")

        # Refresh tokens are opaque JTIs stored in DynamoDB
        from jose import JWTError

        from hive.auth.tokens import decode_jwt

        try:
            claims = decode_jwt(refresh_token)
        except JWTError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid refresh_token: {exc}") from exc

        jti = claims.get("jti")
        stored = storage.get_token(jti) if jti else None
        if stored is None or not stored.is_valid or stored.token_type.value != "refresh":
            raise HTTPException(status_code=400, detail="Invalid or expired refresh_token")
        if stored.client_id != client_id:
            raise HTTPException(status_code=400, detail="refresh_token not issued to this client")

        # Rotate: revoke old refresh token, issue new pair
        storage.revoke_token(jti)
        access, refresh = storage.create_token_pair(client_id, stored.scope)

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported grant_type: {grant_type}")

    from hive.storage import ACCESS_TOKEN_TTL_SECONDS

    storage.log_event(
        ActivityEvent(
            event_type=EventType.token_issued,
            client_id=client_id,
            metadata={"grant_type": grant_type},
        )
    )

    return JSONResponse(
        TokenResponse(
            access_token=issue_jwt(access),
            refresh_token=issue_jwt(refresh),
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=access.scope,
        ).model_dump()
    )


# ---------------------------------------------------------------------------
# Token revocation endpoint (RFC 7009)
# ---------------------------------------------------------------------------


@router.post("/oauth/revoke")
async def revoke(
    token: str = Form(...),
    storage: HiveStorage = Depends(get_storage),
) -> Response:
    from jose import JWTError

    from hive.auth.tokens import decode_jwt

    try:
        claims = decode_jwt(token)
        jti = claims.get("jti")
        if jti:
            storage.revoke_token(jti)
            stored = storage.get_token(jti)
            if stored:
                storage.log_event(
                    ActivityEvent(
                        event_type=EventType.token_revoked,
                        client_id=stored.client_id,
                        metadata={"jti": jti},
                    )
                )
    except JWTError:
        pass  # Per RFC 7009: always return 200 even for invalid tokens

    return Response(status_code=200)
