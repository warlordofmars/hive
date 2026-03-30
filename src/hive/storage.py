"""
DynamoDB storage layer for Hive.

Single-table design — all entities share one table.
Table name is read from the HIVE_TABLE_NAME environment variable.

GSIs:
  TagIndex    — GSI2PK (TAG#{tag}), GSI2SK (memory_id)  → list_memories(tag)
  ClientIndex — GSI3PK (CLIENT#{client_id})              → client lookups
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from hive.models import (
    ActivityEvent,
    AuthorizationCode,
    EventType,
    Memory,
    OAuthClient,
    Token,
    TokenType,
)

TABLE_NAME = os.environ.get("HIVE_TABLE_NAME", "hive")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Token lifetimes
ACCESS_TOKEN_TTL_SECONDS = 3600           # 1 hour
REFRESH_TOKEN_TTL_SECONDS = 86400 * 30   # 30 days
AUTH_CODE_TTL_SECONDS = 300              # 5 minutes


def _now() -> datetime:
    return datetime.now(timezone.utc)


class HiveStorage:
    """All DynamoDB read/write operations for Hive."""

    def __init__(self, table_name: str = TABLE_NAME, region: str = AWS_REGION, **kwargs: Any) -> None:
        dynamodb = boto3.resource("dynamodb", region_name=region, **kwargs)
        self.table = dynamodb.Table(table_name)

    # ------------------------------------------------------------------
    # Memory CRUD
    # ------------------------------------------------------------------

    def put_memory(self, memory: Memory) -> None:
        """Write (create or replace) a memory and all its tag items."""
        # First delete old tag items if the memory already exists
        existing_raw = self._get_memory_meta(memory.memory_id)
        if existing_raw:
            self._delete_tag_items(Memory.from_dynamo(existing_raw))

        with self.table.batch_writer() as batch:
            batch.put_item(Item=memory.to_dynamo_meta())
            for tag_item in memory.to_dynamo_tag_items():
                batch.put_item(Item=tag_item)

    def get_memory_by_id(self, memory_id: str) -> Memory | None:
        item = self._get_memory_meta(memory_id)
        if item is None:
            return None
        return Memory.from_dynamo(item)

    def get_memory_by_key(self, key: str) -> Memory | None:
        """Look up a memory by its human-readable key using GSI1."""
        resp = self.table.query(
            IndexName="KeyIndex",
            KeyConditionExpression=Key("GSI1PK").eq(f"KEY#{key}"),
            Limit=1,
        )
        items = resp.get("Items", [])
        if not items:
            return None
        # GSI items don't carry value; fetch the META item
        memory_id = items[0]["memory_id"]
        return self.get_memory_by_id(memory_id)

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory and all its tag items. Returns True if found."""
        existing = self._get_memory_meta(memory_id)
        if existing is None:
            return False
        memory = Memory.from_dynamo(existing)
        self._delete_tag_items(memory)
        self.table.delete_item(Key={"PK": f"MEMORY#{memory_id}", "SK": "META"})
        return True

    def list_memories_by_tag(self, tag: str) -> list[Memory]:
        """Query TagIndex GSI to find all memories with a given tag."""
        resp = self.table.query(
            IndexName="TagIndex",
            KeyConditionExpression=Key("GSI2PK").eq(f"TAG#{tag}"),
        )
        memories: list[Memory] = []
        for item in resp.get("Items", []):
            m = self.get_memory_by_id(item["memory_id"])
            if m is not None:
                memories.append(m)
        return memories

    def list_all_memories(self, client_id: str | None = None) -> list[Memory]:
        """Scan for all META items (optionally filtered by owner_client_id).
        Use sparingly — prefer tag-based queries in production.
        """
        filter_expr = Key("SK").eq("META")
        if client_id:
            resp = self.table.scan(
                FilterExpression="SK = :sk AND begins_with(PK, :pk_prefix) AND owner_client_id = :cid",
                ExpressionAttributeValues={
                    ":sk": "META",
                    ":pk_prefix": "MEMORY#",
                    ":cid": client_id,
                },
            )
        else:
            resp = self.table.scan(
                FilterExpression="SK = :sk AND begins_with(PK, :pk_prefix)",
                ExpressionAttributeValues={
                    ":sk": "META",
                    ":pk_prefix": "MEMORY#",
                },
            )
        return [Memory.from_dynamo(i) for i in resp.get("Items", []) if i["SK"] == "META" and i["PK"].startswith("MEMORY#")]

    # ------------------------------------------------------------------
    # OAuth Client management
    # ------------------------------------------------------------------

    def put_client(self, client: OAuthClient) -> None:
        self.table.put_item(Item=client.to_dynamo())

    def get_client(self, client_id: str) -> OAuthClient | None:
        resp = self.table.get_item(Key={"PK": f"CLIENT#{client_id}", "SK": "META"})
        item = resp.get("Item")
        return OAuthClient.from_dynamo(item) if item else None

    def delete_client(self, client_id: str) -> bool:
        resp = self.table.get_item(Key={"PK": f"CLIENT#{client_id}", "SK": "META"})
        if not resp.get("Item"):
            return False
        self.table.delete_item(Key={"PK": f"CLIENT#{client_id}", "SK": "META"})
        return True

    def list_clients(self) -> list[OAuthClient]:
        resp = self.table.scan(
            FilterExpression="begins_with(PK, :prefix) AND SK = :sk",
            ExpressionAttributeValues={":prefix": "CLIENT#", ":sk": "META"},
        )
        return [OAuthClient.from_dynamo(i) for i in resp.get("Items", [])]

    # ------------------------------------------------------------------
    # Authorization codes
    # ------------------------------------------------------------------

    def put_auth_code(self, code: AuthorizationCode) -> None:
        self.table.put_item(Item=code.to_dynamo())

    def get_auth_code(self, code: str) -> AuthorizationCode | None:
        resp = self.table.get_item(Key={"PK": f"AUTHCODE#{code}", "SK": "META"})
        item = resp.get("Item")
        return AuthorizationCode.from_dynamo(item) if item else None

    def mark_auth_code_used(self, code: str) -> None:
        self.table.update_item(
            Key={"PK": f"AUTHCODE#{code}", "SK": "META"},
            UpdateExpression="SET #u = :t",
            ExpressionAttributeNames={"#u": "used"},
            ExpressionAttributeValues={":t": True},
        )

    # ------------------------------------------------------------------
    # Tokens
    # ------------------------------------------------------------------

    def put_token(self, token: Token) -> None:
        self.table.put_item(Item=token.to_dynamo())

    def get_token(self, jti: str) -> Token | None:
        resp = self.table.get_item(Key={"PK": f"TOKEN#{jti}", "SK": "META"})
        item = resp.get("Item")
        return Token.from_dynamo(item) if item else None

    def revoke_token(self, jti: str) -> None:
        self.table.update_item(
            Key={"PK": f"TOKEN#{jti}", "SK": "META"},
            UpdateExpression="SET revoked = :t",
            ExpressionAttributeValues={":t": True},
        )

    def create_token_pair(self, client_id: str, scope: str) -> tuple[Token, Token]:
        """Issue a new (access_token, refresh_token) pair."""
        now = _now()
        access = Token(
            client_id=client_id,
            scope=scope,
            token_type=TokenType.access,
            issued_at=now,
            expires_at=now + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS),
        )
        refresh = Token(
            client_id=client_id,
            scope=scope,
            token_type=TokenType.refresh,
            issued_at=now,
            expires_at=now + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS),
        )
        self.put_token(access)
        self.put_token(refresh)
        return access, refresh

    def create_auth_code(
        self,
        client_id: str,
        redirect_uri: str,
        scope: str,
        code_challenge: str,
        code_challenge_method: str = "S256",
    ) -> AuthorizationCode:
        now = _now()
        code = AuthorizationCode(
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            expires_at=now + timedelta(seconds=AUTH_CODE_TTL_SECONDS),
        )
        self.put_auth_code(code)
        return code

    # ------------------------------------------------------------------
    # Activity log
    # ------------------------------------------------------------------

    def log_event(self, event: ActivityEvent) -> None:
        self.table.put_item(Item=event.to_dynamo())

    def get_events_for_date(self, date: str) -> list[ActivityEvent]:
        """Query activity log for a specific date (YYYY-MM-DD)."""
        resp = self.table.query(
            KeyConditionExpression=Key("PK").eq(f"LOG#{date}"),
        )
        return [ActivityEvent.from_dynamo(i) for i in resp.get("Items", [])]

    def get_events_for_dates(self, dates: list[str]) -> list[ActivityEvent]:
        events: list[ActivityEvent] = []
        for d in dates:
            events.extend(self.get_events_for_date(d))
        return sorted(events, key=lambda e: e.timestamp, reverse=True)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def count_memories(self) -> int:
        resp = self.table.scan(
            Select="COUNT",
            FilterExpression="SK = :sk AND begins_with(PK, :prefix)",
            ExpressionAttributeValues={":sk": "META", ":prefix": "MEMORY#"},
        )
        return resp.get("Count", 0)

    def count_clients(self) -> int:
        resp = self.table.scan(
            Select="COUNT",
            FilterExpression="SK = :sk AND begins_with(PK, :prefix)",
            ExpressionAttributeValues={":sk": "META", ":prefix": "CLIENT#"},
        )
        return resp.get("Count", 0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_memory_meta(self, memory_id: str) -> dict[str, Any] | None:
        resp = self.table.get_item(Key={"PK": f"MEMORY#{memory_id}", "SK": "META"})
        return resp.get("Item")  # type: ignore[return-value]

    def _delete_tag_items(self, memory: Memory) -> None:
        with self.table.batch_writer() as batch:
            for tag in memory.tags:
                batch.delete_item(Key={"PK": f"MEMORY#{memory.memory_id}", "SK": f"TAG#{tag}"})
