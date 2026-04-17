# Copyright (c) 2026 John Carter. All rights reserved.
"""
Hive MCP Server — FastMCP tool definitions.

All tools validate the OAuth 2.1 Bearer token passed in the MCP request
context before performing any storage operation.

Tools:
  ping()                      — health check (auth-only, no storage access)
  remember(key, value, tags)  — store a memory
  recall(key)                 — retrieve a memory by key
  forget(key)                 — delete a memory by key
  list_memories(tag)          — list memories by tag
  list_tags()                 — list distinct tags for the caller's memories
  summarize_context(topic)    — synthesise memories into a summary
"""

from __future__ import annotations

import importlib.metadata
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken as FastMCPAccessToken
from fastmcp.server.auth import RemoteAuthProvider, TokenVerifier
from fastmcp.server.dependencies import get_http_request
from pydantic import AnyHttpUrl
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse as StarletteJSONResponse

from hive.auth.tokens import ISSUER, _origin_verify_secret, validate_bearer_token
from hive.logging_config import configure_logging, get_logger, new_request_id, set_request_context
from hive.metrics import emit_metric
from hive.models import ActivityEvent, EventType, Memory, MemorySearchResult
from hive.quota import QuotaExceeded, check_memory_quota
from hive.rate_limiter import RateLimitExceeded, check_rate_limit
from hive.storage import HiveStorage
from hive.vector_store import VectorIndexNotFoundError, VectorStore

configure_logging("mcp")
logger = get_logger("hive.server")

_MEMORIES_READ_SCOPE = "memories:read"

DEFAULT_MAX_VALUE_BYTES = 10 * 1024


def _max_value_bytes() -> int:
    """Max UTF-8 byte size of a memory value. Configurable via HIVE_MAX_VALUE_BYTES."""
    return int(os.environ.get("HIVE_MAX_VALUE_BYTES", str(DEFAULT_MAX_VALUE_BYTES)))


class HiveTokenVerifier(TokenVerifier):
    """Wraps Hive token validation for FastMCP's built-in auth middleware.

    Enables FastMCP to return HTTP 401 + WWW-Authenticate headers on
    unauthenticated requests, triggering the OAuth flow in clients like
    Claude Desktop.  The full validation (rate limit, scope) is still
    enforced per-tool by _auth().
    """

    async def verify_token(self, token: str) -> FastMCPAccessToken | None:
        try:
            validated = validate_bearer_token(f"Bearer {token}", HiveStorage())
            return FastMCPAccessToken(
                token=token,
                client_id=validated.client_id,
                scopes=validated.scope.split(),
                expires_at=int(validated.expires_at.timestamp()),
            )
        except ValueError:
            return None


class _OriginVerifyMiddleware(BaseHTTPMiddleware):
    """Reject requests missing the CloudFront X-Origin-Verify secret.

    Disabled when HIVE_ORIGIN_VERIFY_PARAM is not set (local dev / non-prod).
    """

    async def dispatch(self, request: StarletteRequest, call_next):  # type: ignore[override]
        expected = _origin_verify_secret()
        if (
            expected
            and expected != "CHANGE_ME_ON_FIRST_DEPLOY"
            and request.headers.get("x-origin-verify") != expected
        ):
            return StarletteJSONResponse(status_code=403, content={"detail": "Forbidden"})
        return await call_next(request)


def _app_version() -> str:
    if v := os.environ.get("APP_VERSION"):
        return v
    try:
        return importlib.metadata.version("hive")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


mcp = FastMCP(
    name="Hive",
    instructions=(
        f"Hive {_app_version()} — shared persistent memory server for Claude agents and teams. "
        "Use the memory tools to store, retrieve, and organise information across "
        "conversations and agent runs."
    ),
    auth=RemoteAuthProvider(
        token_verifier=HiveTokenVerifier(),
        authorization_servers=[AnyHttpUrl(ISSUER)],
        base_url=ISSUER,
        scopes_supported=["memories:read", "memories:write"],
        resource_name="Hive",
    ),
)

# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _auth(ctx: Context | None, required_scope: str | None = None) -> tuple[HiveStorage, str]:
    """Validate Bearer token; return (storage, client_id).

    Reads the Authorization header from the HTTP request when running under
    FastMCP's HTTP transport, falling back to ctx.request_context.meta for
    direct invocation (integration tests).  Also sets per-request logging
    context (request_id, client_id).

    If required_scope is given, raises ToolError if the token lacks that scope.
    """
    storage = HiveStorage()
    auth_header: str | None = None
    request_id = new_request_id()

    # HTTP transport (Lambda / local HTTP server)
    try:
        request = get_http_request()
        auth_header = request.headers.get("authorization")
        # Prefer the Lambda / ALB request ID for correlation with CloudWatch.
        request_id = (
            request.headers.get("x-amzn-requestid")
            or request.headers.get("x-request-id")
            or request_id
        )
    except RuntimeError:
        pass

    # Fallback: direct invocation or integration tests pass token via meta.
    # Tests inject a plain dict; FastMCP passes a Pydantic Meta model whose
    # extra fields live in model_extra rather than being dict-accessible.
    if not auth_header and ctx and ctx.request_context and ctx.request_context.meta:
        meta = ctx.request_context.meta
        if isinstance(meta, dict):
            meta_dict: dict[str, Any] = meta
        else:
            meta_dict = getattr(meta, "model_extra", None) or {}
        auth_header = meta_dict.get("Authorization") or meta_dict.get("authorization")

    try:
        token = validate_bearer_token(auth_header, storage)
    except ValueError as exc:
        raise ToolError(f"Unauthorized: {exc}") from exc

    if required_scope and required_scope not in set(token.scope.split()):
        raise ToolError(f"Insufficient scope: '{required_scope}' required")

    try:
        check_rate_limit(token.client_id, storage)
    except RateLimitExceeded as exc:
        raise ToolError(f"Rate limit exceeded. Retry after {exc.retry_after}s.") from exc

    set_request_context(request_id, token.client_id)
    return storage, token.client_id


def _vector_store() -> VectorStore:
    return VectorStore()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def ping(ctx: Context | None = None) -> str:
    """Lightweight health check — returns 'ok' when the Bearer token is valid.

    Performs no storage reads or writes. A successful call confirms both
    connectivity to the MCP server and that the caller's token is still valid.
    """
    _auth(ctx)
    await emit_metric("ToolInvocations", operation="ping")
    return "ok"


@mcp.tool()
async def remember(
    key: Annotated[str, "Unique key to store the memory under"],
    value: Annotated[
        str,
        f"Content of the memory. Maximum {_max_value_bytes()} bytes (UTF-8 encoded); "
        "configurable via HIVE_MAX_VALUE_BYTES.",
    ],
    tags: Annotated[list[str] | None, "Optional tags for categorisation"] = None,
    ttl_seconds: Annotated[
        int | None, "Seconds until the memory expires. None = never expires."
    ] = None,
    ctx: Context | None = None,
) -> str:
    """Store or update a memory with optional tags and optional TTL."""
    t0 = time.monotonic()
    storage, client_id = _auth(ctx, required_scope="memories:write")

    limit = _max_value_bytes()
    actual = len(value.encode("utf-8"))
    if actual > limit:
        await emit_metric("ToolErrors", operation="remember")
        raise ToolError(f"Value exceeds maximum size of {limit} bytes ({actual} bytes provided)")

    tags = tags or []
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        if ttl_seconds is not None
        else None
    )

    # Check if a memory with this key already exists (upsert path)
    existing = storage.get_memory_by_key(key)

    if existing:
        # Idempotent: skip write and log if nothing changed
        if (
            existing.value == value
            and set(existing.tags) == set(tags)
            and existing.expires_at == expires_at
        ):
            logger.info(
                "Memory unchanged",
                extra={
                    "tool": "remember",
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "status": "unchanged",
                },
            )
            return f"Memory '{key}' unchanged."
        existing.value = value
        existing.tags = tags
        existing.expires_at = expires_at
        existing.updated_at = datetime.now(timezone.utc)
        try:
            storage.put_memory(existing)
        except ValueError as exc:
            await emit_metric("ToolErrors", operation="remember")
            raise ToolError(str(exc)) from exc
        event_type = EventType.memory_updated
        action = "Updated"
        try:
            _vector_store().upsert_memory(existing)
        except Exception:
            logger.warning("Vector upsert failed (non-fatal)", exc_info=True)
    else:
        client = storage.get_client(client_id)
        owner_user_id = client.owner_user_id if client else None
        try:
            check_memory_quota(owner_user_id, storage)
        except QuotaExceeded as exc:
            raise ToolError(exc.detail) from exc
        memory = Memory(
            key=key, value=value, tags=tags, owner_client_id=client_id, expires_at=expires_at
        )
        try:
            storage.put_memory(memory)
        except ValueError as exc:
            await emit_metric("ToolErrors", operation="remember")
            raise ToolError(str(exc)) from exc
        event_type = EventType.memory_created
        action = "Stored"
        try:
            _vector_store().upsert_memory(memory)
        except Exception:
            logger.warning("Vector upsert failed (non-fatal)", exc_info=True)

    storage.log_event(
        ActivityEvent(
            event_type=event_type,
            client_id=client_id,
            metadata={"key": key, "tags": tags},
        )
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "%s memory '%s'",
        action,
        key,
        extra={
            "tool": "remember",
            "duration_ms": duration_ms,
            "status": "success",
        },
    )
    await emit_metric("ToolInvocations", operation="remember")
    await emit_metric(
        "StorageLatencyMs", value=float(duration_ms), unit="Milliseconds", operation="remember"
    )
    return f"{action} memory '{key}'."


@mcp.tool()
async def recall(
    key: Annotated[str, "Key of the memory to retrieve"],
    ctx: Context | None = None,
) -> str:
    """Retrieve a memory by its key."""
    t0 = time.monotonic()
    storage, client_id = _auth(ctx, required_scope=_MEMORIES_READ_SCOPE)

    memory = storage.get_memory_by_key(key)
    if memory is None:
        logger.warning(
            "Memory not found for key '%s'",
            key,
            extra={
                "tool": "recall",
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "status": "not_found",
            },
        )
        await emit_metric("ToolErrors", operation="recall")
        raise ToolError(f"No memory found for key '{key}'.")

    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_recalled,
            client_id=client_id,
            metadata={"key": key},
        )
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "Recalled memory '%s'",
        key,
        extra={
            "tool": "recall",
            "duration_ms": duration_ms,
            "status": "success",
        },
    )
    await emit_metric("ToolInvocations", operation="recall")
    await emit_metric(
        "StorageLatencyMs", value=float(duration_ms), unit="Milliseconds", operation="recall"
    )
    return memory.value


@mcp.tool()
async def forget(
    key: Annotated[str, "Key of the memory to delete"],
    ctx: Context | None = None,
) -> str:
    """Delete a memory by its key."""
    t0 = time.monotonic()
    storage, client_id = _auth(ctx, required_scope="memories:write")

    existing = storage.get_memory_by_key(key)
    if existing is None:
        logger.warning(
            "Memory not found for key '%s'",
            key,
            extra={
                "tool": "forget",
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "status": "not_found",
            },
        )
        await emit_metric("ToolErrors", operation="forget")
        raise ToolError(f"No memory found for key '{key}'.")

    storage.delete_memory(existing.memory_id)
    try:
        _vector_store().delete_memory(existing.memory_id, client_id)
    except Exception:
        logger.warning("Vector delete failed (non-fatal)", exc_info=True)
    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_deleted,
            client_id=client_id,
            metadata={"key": key},
        )
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "Deleted memory '%s'",
        key,
        extra={
            "tool": "forget",
            "duration_ms": duration_ms,
            "status": "success",
        },
    )
    await emit_metric("ToolInvocations", operation="forget")
    await emit_metric(
        "StorageLatencyMs", value=float(duration_ms), unit="Milliseconds", operation="forget"
    )
    return f"Deleted memory '{key}'."


@mcp.tool()
async def forget_all(
    tag: Annotated[str, "Tag of the memories to delete"],
    ctx: Context | None = None,
) -> str:
    """Delete all memories that have the given tag."""
    t0 = time.monotonic()
    storage, client_id = _auth(ctx, required_scope="memories:write")

    deleted = storage.delete_memories_by_tag(tag)
    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_deleted,
            client_id=client_id,
            metadata={"tag": tag, "count": deleted},
        )
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "Deleted %d memories with tag '%s'",
        deleted,
        tag,
        extra={
            "tool": "forget_all",
            "duration_ms": duration_ms,
            "status": "success",
        },
    )
    await emit_metric("ToolInvocations", operation="forget_all")
    await emit_metric(
        "StorageLatencyMs",
        value=float(duration_ms),
        unit="Milliseconds",
        operation="forget_all",
    )
    return f"Deleted {deleted} memories with tag '{tag}'."


@mcp.tool()
async def memory_history(
    key: Annotated[str, "Key of the memory to retrieve history for"],
    ctx: Context | None = None,
) -> list[dict[str, Any]]:
    """Return the version history of a memory (previous values before each overwrite)."""
    t0 = time.monotonic()
    storage, client_id = _auth(ctx, required_scope="memories:read")

    memory = storage.get_memory_by_key(key)
    if memory is None:
        raise ToolError(f"No memory found for key '{key}'.")
    versions = storage.list_memory_versions(memory.memory_id)
    duration_ms = int((time.monotonic() - t0) * 1000)
    await emit_metric("ToolInvocations", operation="memory_history")
    await emit_metric(
        "StorageLatencyMs",
        value=float(duration_ms),
        unit="Milliseconds",
        operation="memory_history",
    )
    return [
        {
            "version_timestamp": v.version_timestamp,
            "value": v.value,
            "tags": v.tags,
            "recorded_at": v.recorded_at.isoformat(),
        }
        for v in versions
    ]


@mcp.tool()
async def restore_memory(
    key: Annotated[str, "Key of the memory to restore"],
    version_timestamp: Annotated[str, "Version timestamp to restore (from memory_history)"],
    ctx: Context | None = None,
) -> str:
    """Restore a memory to a previous version."""
    t0 = time.monotonic()
    storage, client_id = _auth(ctx, required_scope="memories:write")

    memory = storage.get_memory_by_key(key)
    if memory is None:
        raise ToolError(f"No memory found for key '{key}'.")
    version = storage.get_memory_version(memory.memory_id, version_timestamp)
    if version is None:
        raise ToolError(f"Version '{version_timestamp}' not found for memory '{key}'.")

    memory.value = version.value
    memory.tags = version.tags
    memory.updated_at = datetime.now(timezone.utc)
    storage.put_memory(memory)
    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_updated,
            client_id=client_id,
            metadata={"key": key, "version_timestamp": version_timestamp},
        )
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    await emit_metric("ToolInvocations", operation="restore_memory")
    await emit_metric(
        "StorageLatencyMs",
        value=float(duration_ms),
        unit="Milliseconds",
        operation="restore_memory",
    )
    return f"Restored memory '{key}' to version '{version_timestamp}'."


@mcp.tool()
async def list_memories(
    tag: Annotated[str, "Tag to filter memories by"],
    limit: Annotated[int, "Maximum number of memories to return (1–500)"] = 100,
    cursor: Annotated[str | None, "Pagination cursor from a previous call"] = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """List memories that have a specific tag, with optional pagination."""
    t0 = time.monotonic()
    storage, client_id = _auth(ctx, required_scope=_MEMORIES_READ_SCOPE)

    limit = max(1, min(limit, 500))
    memories, next_cursor = storage.list_memories_by_tag(tag, limit=limit, cursor=cursor)
    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_listed,
            client_id=client_id,
            metadata={"tag": tag, "count": len(memories)},
        )
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "Listed %d memories for tag '%s'",
        len(memories),
        tag,
        extra={
            "tool": "list_memories",
            "duration_ms": duration_ms,
            "status": "success",
        },
    )
    await emit_metric("ToolInvocations", operation="list_memories")
    await emit_metric(
        "StorageLatencyMs", value=float(duration_ms), unit="Milliseconds", operation="list_memories"
    )
    result: dict[str, Any] = {
        "items": [{"key": m.key, "value": m.value, "tags": m.tags} for m in memories],
        "count": len(memories),
        "has_more": next_cursor is not None,
    }
    if next_cursor:
        result["next_cursor"] = next_cursor
    return result


@mcp.tool()
async def list_tags(ctx: Context | None = None) -> dict[str, Any]:
    """List all distinct tags currently in use across the caller's memories.

    Returns tags sorted alphabetically. Useful for discovering the tag
    namespace of an existing memory corpus before calling `list_memories`.
    """
    t0 = time.monotonic()
    storage, client_id = _auth(ctx, required_scope=_MEMORIES_READ_SCOPE)
    tags = storage.list_distinct_tags(client_id)
    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "Listed %d distinct tags",
        len(tags),
        extra={
            "tool": "list_tags",
            "duration_ms": duration_ms,
            "status": "success",
        },
    )
    await emit_metric("ToolInvocations", operation="list_tags")
    await emit_metric(
        "StorageLatencyMs", value=float(duration_ms), unit="Milliseconds", operation="list_tags"
    )
    return {"tags": tags, "count": len(tags)}


@mcp.tool()
async def summarize_context(
    topic: Annotated[str, "Topic or tag to summarise memories about"],
    ctx: Context | None = None,
) -> str:
    """
    Retrieve all memories related to a topic and return a synthesised summary.

    Memories are retrieved by tag matching the topic.  The summary lists each
    memory and then provides a combined overview paragraph.
    """
    t0 = time.monotonic()
    storage, client_id = _auth(ctx, required_scope=_MEMORIES_READ_SCOPE)

    memories, _ = storage.list_memories_by_tag(topic, limit=500)

    if not memories:
        logger.info(
            "No memories for topic '%s'",
            topic,
            extra={
                "tool": "summarize_context",
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "status": "empty",
            },
        )
        await emit_metric("ToolInvocations", operation="summarize_context")
        return f"No memories found for topic '{topic}'."

    lines = [f"## Memories tagged '{topic}'\n"]
    for m in memories:
        lines.append(f"**{m.key}**: {m.value}")

    lines.append(
        f"\n---\n*Summary: {len(memories)} memory/memories found for topic '{topic}'. "
        "Review the entries above for relevant context.*"
    )

    storage.log_event(
        ActivityEvent(
            event_type=EventType.context_summarized,
            client_id=client_id,
            metadata={"topic": topic, "memory_count": len(memories)},
        )
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "Summarized %d memories for topic '%s'",
        len(memories),
        topic,
        extra={
            "tool": "summarize_context",
            "duration_ms": duration_ms,
            "status": "success",
        },
    )
    await emit_metric("ToolInvocations", operation="summarize_context")
    await emit_metric(
        "StorageLatencyMs",
        value=float(duration_ms),
        unit="Milliseconds",
        operation="summarize_context",
    )
    return "\n".join(lines)


@mcp.tool()
async def search_memories(
    query: Annotated[str, "Natural language search query"],
    top_k: Annotated[int, "Maximum number of results to return (1–50)"] = 10,
    min_score: Annotated[
        float | None,
        "Minimum similarity score (0.0–1.0). Results below this threshold are "
        "excluded. None disables filtering.",
    ] = None,
    filter_tags: Annotated[
        list[str] | None,
        "Optional list of tags. Only memories carrying ALL of the given tags "
        "are returned. None disables filtering.",
    ] = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Search memories by semantic similarity to a natural language query.

    Returns memories ranked by relevance.  ``score`` ranges from 0.0 to 1.0
    where higher means more semantically similar to the query.
    """
    t0 = time.monotonic()
    storage, client_id = _auth(ctx, required_scope=_MEMORIES_READ_SCOPE)
    top_k = max(1, min(top_k, 50))
    threshold = max(0.0, min(1.0, min_score)) if min_score is not None else None
    required_tags = set(filter_tags) if filter_tags else None

    # When post-filtering by tags, request the full cap from the vector store
    # so we have headroom to still return up to top_k matches after filtering.
    search_top_k = 50 if required_tags else top_k

    try:
        pairs = _vector_store().search(query, client_id, top_k=search_top_k)
    except VectorIndexNotFoundError:
        return {"items": [], "count": 0, "query": query}
    except Exception:
        logger.warning("Vector search failed (non-fatal)", exc_info=True)
        return {"items": [], "count": 0, "query": query}

    if threshold is not None:
        pairs = [(mid, score) for mid, score in pairs if score >= threshold]

    results = storage.hydrate_memory_ids(pairs)

    if required_tags:
        results = [(m, s) for m, s in results if required_tags.issubset(m.tags)]

    results = results[:top_k]

    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_searched,
            client_id=client_id,
            metadata={"query": query, "result_count": len(results)},
        )
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "Searched memories for '%s', %d result(s)",
        query,
        len(results),
        extra={
            "tool": "search_memories",
            "duration_ms": duration_ms,
            "status": "success",
        },
    )
    await emit_metric("ToolInvocations", operation="search_memories")
    await emit_metric(
        "StorageLatencyMs",
        value=float(duration_ms),
        unit="Milliseconds",
        operation="search_memories",
    )
    return {
        "items": [
            MemorySearchResult.from_memory_and_score(m, score).model_dump() for m, score in results
        ],
        "count": len(results),
        "query": query,
    }


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

# Module-level ASGI app — used by uvicorn for local dev:
#   uvicorn hive.server:asgi_app --port 8002
# Uvicorn manages lifespan correctly (startup once, shutdown once).
asgi_app = mcp.http_app(stateless_http=True, json_response=True)


def lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:  # pragma: no cover
    """AWS Lambda + Function URL handler (HTTP mode).

    Creates a fresh ASGI app per Lambda container initialisation.
    FastMCP's StreamableHTTPSessionManager can only be started once per
    instance, so we cannot reuse the module-level asgi_app across warm
    Lambda invocations where Mangum re-runs the lifespan on each call.
    """
    try:
        from mangum import Mangum
    except ImportError as exc:
        raise RuntimeError("mangum is required for Lambda deployment") from exc

    _app = mcp.http_app(stateless_http=True, json_response=True)
    _app.add_middleware(_OriginVerifyMiddleware)
    handler = Mangum(_app, lifespan="on")
    return handler(event, context)  # type: ignore[arg-type]  # mangum stubs incomplete


if __name__ == "__main__":
    mcp.run(transport="stdio")
