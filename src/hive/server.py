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

from datetime import datetime, timezone
from typing import Annotated

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from hive.auth.tokens import validate_bearer_token
from hive.models import ActivityEvent, EventType, Memory
from hive.storage import HiveStorage

mcp = FastMCP(
    name="Hive",
    instructions=(
        "Hive is a shared persistent memory server for Claude agents and teams. "
        "Use the memory tools to store, retrieve, and organise information across "
        "conversations and agent runs."
    ),
)

# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _auth(ctx: Context) -> tuple[HiveStorage, str]:
    """Validate Bearer token from context metadata; return (storage, client_id)."""
    storage = HiveStorage()
    auth_header: str | None = None

    # MCP clients pass HTTP headers in the request context metadata
    if ctx.request_context and ctx.request_context.meta:
        auth_header = ctx.request_context.meta.get("authorization") or ctx.request_context.meta.get(
            "Authorization"
        )

    try:
        token = validate_bearer_token(auth_header, storage)
    except ValueError as exc:
        raise ToolError(f"Unauthorized: {exc}") from exc

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
    storage, client_id = _auth(ctx)
    tags = tags or []

    # Check if a memory with this key already exists (update path)
    existing = storage.get_memory_by_key(key)

    if existing:
        existing.value = value
        existing.tags = tags
        existing.updated_at = datetime.now(timezone.utc)
        storage.put_memory(existing)
        event_type = EventType.memory_updated
        action = "Updated"
    else:
        memory = Memory(key=key, value=value, tags=tags, owner_client_id=client_id)
        storage.put_memory(memory)
        event_type = EventType.memory_created
        action = "Stored"

    storage.log_event(
        ActivityEvent(
            event_type=event_type,
            client_id=client_id,
            metadata={"key": key, "tags": tags},
        )
    )
    return f"{action} memory '{key}'."


@mcp.tool()
async def recall(
    key: Annotated[str, "Key of the memory to retrieve"],
    ctx: Context = None,  # type: ignore[assignment]
) -> str:
    """Retrieve a memory by its key."""
    storage, client_id = _auth(ctx)

    memory = storage.get_memory_by_key(key)
    if memory is None:
        raise ToolError(f"No memory found for key '{key}'.")

    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_recalled,
            client_id=client_id,
            metadata={"key": key},
        )
    )
    return memory.value


@mcp.tool()
async def forget(
    key: Annotated[str, "Key of the memory to delete"],
    ctx: Context = None,  # type: ignore[assignment]
) -> str:
    """Delete a memory by its key."""
    storage, client_id = _auth(ctx)

    existing = storage.get_memory_by_key(key)
    if existing is None:
        raise ToolError(f"No memory found for key '{key}'.")

    storage.delete_memory(existing.memory_id)
    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_deleted,
            client_id=client_id,
            metadata={"key": key},
        )
    )
    return f"Deleted memory '{key}'."


@mcp.tool()
async def list_memories(
    tag: Annotated[str, "Tag to filter memories by"],
    ctx: Context = None,  # type: ignore[assignment]
) -> list[dict]:
    """List all memories that have a specific tag."""
    storage, client_id = _auth(ctx)

    memories = storage.list_memories_by_tag(tag)
    storage.log_event(
        ActivityEvent(
            event_type=EventType.memory_listed,
            client_id=client_id,
            metadata={"tag": tag, "count": len(memories)},
        )
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
    storage, client_id = _auth(ctx)

    memories = storage.list_memories_by_tag(topic)

    if not memories:
        # Fallback: try as a key prefix scan isn't cheap; just report no memories
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
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point — run as a Lambda handler or local stdio server
# ---------------------------------------------------------------------------


def lambda_handler(event: dict, context: object) -> dict:
    """AWS Lambda + Function URL handler (HTTP mode)."""

    # Re-use FastAPI ASGI app via Mangum
    try:
        from mangum import Mangum
    except ImportError as exc:
        raise RuntimeError("mangum is required for Lambda deployment") from exc

    asgi_app = mcp.http_app()
    handler = Mangum(asgi_app, lifespan="off")
    return handler(event, context)


if __name__ == "__main__":
    mcp.run(transport="stdio")
