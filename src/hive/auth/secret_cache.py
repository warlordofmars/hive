# Copyright (c) 2026 John Carter. All rights reserved.
"""
Time-based (TTL) caching for auth secrets.

Replaces the previous ``functools.lru_cache(maxsize=1)`` on the secret
fetchers (#585): an unbounded cache meant SSM parameter rotations never took
effect in a warm Lambda without a cold start.  Cached values are re-fetched
once the TTL expires — default 300 seconds, overridable via the
``HIVE_SECRET_CACHE_TTL_SECONDS`` environment variable.

Failure semantics are fail-static: when a *refresh* fetch fails but a
previously fetched value exists, the stale value is served and a warning is
logged — an SSM blip must never take down token issuance or validation.
The optional ``fallback`` is used only when the *first* fetch fails (no
cached value exists yet); without a fallback the exception propagates.
This preserves each call site's original first-fetch failure behaviour.
"""

from __future__ import annotations

import functools
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any, Generic, Protocol, TypeVar

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 300.0
TTL_ENV_VAR = "HIVE_SECRET_CACHE_TTL_SECONDS"

T = TypeVar("T")


def _ttl_seconds() -> float:
    """Return the cache TTL, honouring the env override (default 300s)."""
    raw = os.environ.get(TTL_ENV_VAR)
    if not raw:
        return DEFAULT_TTL_SECONDS
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %ss", TTL_ENV_VAR, raw, DEFAULT_TTL_SECONDS)
        return DEFAULT_TTL_SECONDS


class _TtlCache(Generic[T]):
    """A zero-argument fetch function wrapped in a time-based cache.

    Exposes ``cache_clear()`` mirroring ``functools.lru_cache`` so existing
    test hooks keep working unchanged.
    """

    __name__: str  # set by functools.update_wrapper

    def __init__(self, fetch: Callable[[], T], fallback: Callable[[], T] | None) -> None:
        self._fetch = fetch
        self._fallback = fallback
        self._name = getattr(fetch, "__name__", repr(fetch))
        self._lock = threading.Lock()
        self._has_value = False
        self._value: T  # guarded by _has_value; assigned on first successful fetch
        self._fetched_at = 0.0
        functools.update_wrapper(self, fetch)

    def __call__(self) -> T:
        with self._lock:
            now = time.monotonic()
            if self._has_value and (now - self._fetched_at) < _ttl_seconds():
                return self._value
            try:
                value = self._fetch()
            except Exception:
                if self._has_value:
                    # Fail-static: serve the previous value rather than let an
                    # SSM blip break token issuance/validation.  Resetting the
                    # timestamp backs off retries by one TTL window.
                    logger.warning(
                        "Refresh of %s failed; serving previously cached value",
                        self._name,
                        exc_info=True,
                    )
                    self._fetched_at = now
                    return self._value
                if self._fallback is None:
                    raise
                logger.warning(
                    "Initial fetch of %s failed; using fallback value",
                    self._name,
                    exc_info=True,
                )
                value = self._fallback()
            self._value = value
            self._has_value = True
            self._fetched_at = now
            return value

    def cache_clear(self) -> None:
        """Drop the cached value so the next call re-fetches (test hook)."""
        with self._lock:
            self._has_value = False
            self._fetched_at = 0.0


class _Decorator(Protocol):
    """A decorator whose value type binds at application time."""

    def __call__(self, fetch: Callable[[], T]) -> _TtlCache[T]: ...


def ttl_cached(fallback: Callable[[], Any] | None = None) -> _Decorator:
    """Decorate a zero-argument secret fetcher with a TTL cache.

    ``fallback`` is invoked only when the very first fetch fails; its result
    is cached like a normal value so the process stays consistent until the
    next refresh window.  Refresh failures after a successful fetch always
    serve the stale value instead (fail-static).
    """

    def decorator(fetch: Callable[[], T]) -> _TtlCache[T]:
        return _TtlCache(fetch, fallback)

    return decorator
