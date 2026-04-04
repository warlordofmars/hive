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
from typing import Annotated

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request

from hive.auth.tokens import validate_bearer_token
from hive.logging_config import configure_logging, get_logger, new_request_id, set_request_context
from hive.models import ActivityEvent, EventType, Memory
from hive.storage import HiveStorage

configure_logging("mcp")
logger = get_logger("hive.server")


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


def _auth(ctx: Context) -> tuple[HiveStorage, str]:
    """Validate Bearer token; return (storage, client_id).

    Reads the Authorization header from the HTTP request when running under
    FastMCP's HTTP transport, falling back to ctx.request_context.meta for
    direct invocation (integration tests).  Also sets per-request logging
    context (request_id, client_id).
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
        meta: dict = ctx.request_context.meta  # type: ignore[assignment]
        auth_header = meta.get("Authorization") or meta.get("authorization")

    try:
        token = validate_bearer_token(auth_header, storage)
    except ValueError as exc:
        raise ToolError(f"Unauthorized: {exc}") from exc

    set_request_context(request_id, token.client_id)
    return storage, token.client_id


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def remember(
    key: Annotated[str, "Unique key to store the memory under"],
    value: Annotated[str, "Content of the memory"],
    tags: Annotated[list[str], "Optional tags for categorisation"] = None,  # type: ignore[assignment]
    ctx: Context = None,  # type: ignore[assignment]
) -> str:
    """Store or update a memory with optional tags."""
    t0 = time.monotonic()
    storage, client_id = _auth(ctx)
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
            raise ToolError(str(exc)) from exc
        event_type = EventType.memory_updated
        action = "Updated"
    else:
        memory = Memory(key=key, value=value, tags=tags, owner_client_id=client_id)
        try:
            storage.put_memory(memory)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        event_type = EventType.memory_created
        action = "Stored"

    storage.log_event(
        ActivityEvent(
            event_type=event_type,
            client_id=client_id,
            metadata={"key": key, "tags": tags},
        )
    )
    logger.info(
        "%s memory '%s'",
        action,
        key,
        extra={
            "tool": "remember",
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "status": "success",
        },
    )
    return f"{action} memory '{key}'."


@mcp.tool()
async def recall(
    key: Annotated[str, "Key of the memory to retrieve"],
    ctx: Context = None,  # type: ignore[assignment]
) -> str:
    """Retrieve a memory by its key."""
    t0 = time.monotonic()
    storage, client_id = _auth(ctx)

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
        raise ToolError(f"No memory found for key '{key}'.")

    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_recalled,
            client_id=client_id,
            metadata={"key": key},
        )
    )
    logger.info(
        "Recalled memory '%s'",
        key,
        extra={
            "tool": "recall",
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "status": "success",
        },
    )
    return memory.value


@mcp.tool()
async def forget(
    key: Annotated[str, "Key of the memory to delete"],
    ctx: Context = None,  # type: ignore[assignment]
) -> str:
    """Delete a memory by its key."""
    t0 = time.monotonic()
    storage, client_id = _auth(ctx)

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
        raise ToolError(f"No memory found for key '{key}'.")

    storage.delete_memory(existing.memory_id)
    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_deleted,
            client_id=client_id,
            metadata={"key": key},
        )
    )
    logger.info(
        "Deleted memory '%s'",
        key,
        extra={
            "tool": "forget",
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "status": "success",
        },
    )
    return f"Deleted memory '{key}'."


@mcp.tool()
async def list_memories(
    tag: Annotated[str, "Tag to filter memories by"],
    ctx: Context = None,  # type: ignore[assignment]
) -> list[dict]:
    """List all memories that have a specific tag."""
    t0 = time.monotonic()
    storage, client_id = _auth(ctx)

    memories = storage.list_memories_by_tag(tag)
    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_listed,
            client_id=client_id,
            metadata={"tag": tag, "count": len(memories)},
        )
    )
    logger.info(
        "Listed %d memories for tag '%s'",
        len(memories),
        tag,
        extra={
            "tool": "list_memories",
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "status": "success",
        },
    )
    return [{"key": m.key, "value": m.value, "tags": m.tags} for m in memories]


@mcp.tool()
async def summarize_context(
    topic: Annotated[str, "Topic or tag to summarise memories about"],
    ctx: Context = None,  # type: ignore[assignment]
) -> str:
    """
    Retrieve all memories related to a topic and return a synthesised summary.

    Memories are retrieved by tag matching the topic.  The summary lists each
    memory and then provides a combined overview paragraph.
    """
    t0 = time.monotonic()
    storage, client_id = _auth(ctx)

    memories = storage.list_memories_by_tag(topic)

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
    logger.info(
        "Summarized %d memories for topic '%s'",
        len(memories),
        topic,
        extra={
            "tool": "summarize_context",
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "status": "success",
        },
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

# Module-level ASGI app — used by uvicorn for local dev:
#   uvicorn hive.server:asgi_app --port 8002
# Uvicorn manages lifespan correctly (startup once, shutdown once).
asgi_app = mcp.http_app(stateless_http=True, json_response=True)


def lambda_handler(event: dict, context: object) -> dict:
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
    handler = Mangum(_app, lifespan="on")
    return handler(event, context)  # type: ignore[arg-type]


if __name__ == "__main__":
    mcp.run(transport="stdio")
