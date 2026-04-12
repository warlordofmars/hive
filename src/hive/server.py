# Copyright (c) 2026 John Carter. All rights reserved.
"""
Hive MCP Server — FastMCP tool definitions.

All tools validate the OAuth 2.1 Bearer token passed in the MCP request
context before performing any storage operation.

Tools:
  remember(key, value, tags)  — store a memory
  recall(key)                 — retrieve a memory by key
  forget(key)                 — delete a memory by key
  list_memories(tag)          — list memories by tag
  summarize_context(topic)    — synthesise memories into a summary
"""

from __future__ import annotations

import importlib.metadata
import os
import time
from datetime import datetime, timezone
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse as StarletteJSONResponse

from hive.auth.tokens import _origin_verify_secret, validate_bearer_token
from hive.logging_config import configure_logging, get_logger, new_request_id, set_request_context
from hive.metrics import emit_metric
from hive.models import ActivityEvent, EventType, Memory, MemorySearchResult
from hive.rate_limiter import RateLimitExceeded, check_rate_limit
from hive.storage import HiveStorage
from hive.vector_store import VectorIndexNotFoundError, VectorStore

configure_logging("mcp")
logger = get_logger("hive.server")

_MEMORIES_READ_SCOPE = "memories:read"


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

    # Fallback: direct invocation or integration tests pass token via meta
    if not auth_header and ctx and ctx.request_context and ctx.request_context.meta:
        meta: dict[str, Any] = ctx.request_context.meta  # type: ignore[assignment]
        auth_header = meta.get("Authorization") or meta.get("authorization")

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
async def remember(
    key: Annotated[str, "Unique key to store the memory under"],
    value: Annotated[str, "Content of the memory"],
    tags: Annotated[list[str] | None, "Optional tags for categorisation"] = None,
    ctx: Context | None = None,
) -> str:
    """Store or update a memory with optional tags."""
    t0 = time.monotonic()
    storage, client_id = _auth(ctx, required_scope="memories:write")
    tags = tags or []

    # Check if a memory with this key already exists (upsert path)
    existing = storage.get_memory_by_key(key)

    if existing:
        # Idempotent: skip write and log if nothing changed
        if existing.value == value and set(existing.tags) == set(tags):
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
        memory = Memory(key=key, value=value, tags=tags, owner_client_id=client_id)
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
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Search memories by semantic similarity to a natural language query.

    Returns memories ranked by relevance.  ``score`` ranges from 0.0 to 1.0
    where higher means more semantically similar to the query.
    """
    t0 = time.monotonic()
    storage, client_id = _auth(ctx, required_scope=_MEMORIES_READ_SCOPE)
    top_k = max(1, min(top_k, 50))

    try:
        pairs = _vector_store().search(query, client_id, top_k=top_k)
    except VectorIndexNotFoundError:
        return {"items": [], "count": 0, "query": query}
    except Exception:
        logger.warning("Vector search failed (non-fatal)", exc_info=True)
        return {"items": [], "count": 0, "query": query}

    results = storage.hydrate_memory_ids(pairs)

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
