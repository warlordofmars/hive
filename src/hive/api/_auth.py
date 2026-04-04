# Copyright (c) 2026 John Carter. All rights reserved.
"""Shared FastAPI auth dependency for management API routes."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from hive.auth.tokens import validate_bearer_token
from hive.storage import HiveStorage

_bearer = HTTPBearer()


def _get_storage() -> HiveStorage:
    return HiveStorage()


async def require_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    storage: HiveStorage = Depends(_get_storage),
) -> tuple[HiveStorage, str]:
    """
    FastAPI dependency that validates the Bearer token and returns
    (storage, client_id).  Raises HTTP 401 on failure.
    """
    try:
        token = validate_bearer_token(f"Bearer {credentials.credentials}", storage)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return storage, token.client_id
