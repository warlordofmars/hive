# Copyright (c) 2026 John Carter. All rights reserved.
"""
DynamoDB storage layer for Hive.

Single-table design — all entities share one table.
Table name is read from the HIVE_TABLE_NAME environment variable.

GSIs:
  TagIndex    — GSI2PK (TAG#{tag}), GSI2SK (memory_id)  → list_memories(tag)
  ClientIndex — GSI3PK (CLIENT#{client_id})              → client lookups
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from hive.models import (
    ActivityEvent,
    AuthorizationCode,
    Memory,
    OAuthClient,
    Token,
    TokenType,
)

TABLE_NAME = os.environ.get("HIVE_TABLE_NAME", "hive")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
DYNAMODB_ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT")

# Token lifetimes
ACCESS_TOKEN_TTL_SECONDS = 3600  # 1 hour
REFRESH_TOKEN_TTL_SECONDS = 86400 * 30  # 30 days
AUTH_CODE_TTL_SECONDS = 300  # 5 minutes


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode_cursor(last_evaluated_key: dict) -> str:
    """Encode a DynamoDB LastEvaluatedKey as an opaque base64 cursor."""
    return base64.urlsafe_b64encode(json.dumps(last_evaluated_key).encode()).decode()


def _decode_cursor(cursor: str) -> dict:
    """Decode a base64 cursor back to a DynamoDB ExclusiveStartKey."""
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except Exception as exc:
        raise ValueError(f"Invalid pagination cursor: {cursor!r}") from exc


class HiveStorage:
    """All DynamoDB read/write operations for Hive."""

    def __init__(
        self, table_name: str | None = None, region: str | None = None, **kwargs: Any
    ) -> None:
        # Read env vars at call time so tests can override them after import
        table_name = table_name or os.environ.get("HIVE_TABLE_NAME", "hive")
        region = region or os.environ.get("AWS_REGION", "us-east-1")
        # Auto-use DYNAMODB_ENDPOINT for local dev / integration tests
        kwargs.setdefault("endpoint_url", os.environ.get("DYNAMODB_ENDPOINT"))
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

        try:
            with self.table.batch_writer() as batch:
                batch.put_item(Item=memory.to_dynamo_meta())
                for tag_item in memory.to_dynamo_tag_items():
                    batch.put_item(Item=tag_item)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            msg = exc.response["Error"]["Message"]
            if code == "ValidationException" and "size" in msg.lower():
                raise ValueError(
                    "Memory value is too large to store (DynamoDB 400 KB item limit exceeded)."
                ) from exc
            raise

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

    def list_memories_by_tag(
        self,
        tag: str,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[Memory], str | None]:
        """Query TagIndex GSI to find memories with a given tag.

        Returns (memories, next_cursor). next_cursor is None when exhausted.
        """
        kwargs: dict[str, Any] = {
            "IndexName": "TagIndex",
            "KeyConditionExpression": Key("GSI2PK").eq(f"TAG#{tag}"),
            "Limit": limit,
        }
        if cursor:
            kwargs["ExclusiveStartKey"] = _decode_cursor(cursor)

        resp = self.table.query(**kwargs)
        memories: list[Memory] = []
        for item in resp.get("Items", []):
            m = self.get_memory_by_id(item["memory_id"])
            if m is not None:
                memories.append(m)

        lek = resp.get("LastEvaluatedKey")
        next_cursor = _encode_cursor(lek) if lek else None
        return memories, next_cursor

    def list_all_memories(
        self,
        client_id: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[Memory], str | None]:
        """Scan for all META memory items (optionally filtered by owner_client_id).

        Returns (memories, next_cursor). Use sparingly — prefer tag-based queries.
        """
        kwargs: dict[str, Any] = {
            "FilterExpression": "SK = :sk AND begins_with(PK, :pk_prefix)",
            "ExpressionAttributeValues": {":sk": "META", ":pk_prefix": "MEMORY#"},
            "Limit": limit,
        }
        if client_id:
            kwargs["FilterExpression"] += " AND owner_client_id = :cid"
            kwargs["ExpressionAttributeValues"][":cid"] = client_id
        if cursor:
            kwargs["ExclusiveStartKey"] = _decode_cursor(cursor)

        resp = self.table.scan(**kwargs)
        memories = [
            Memory.from_dynamo(i)
            for i in resp.get("Items", [])
            if i["SK"] == "META" and i["PK"].startswith("MEMORY#")
        ]
        lek = resp.get("LastEvaluatedKey")
        next_cursor = _encode_cursor(lek) if lek else None
        return memories, next_cursor

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

    def list_clients(
        self,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[OAuthClient], str | None]:
        kwargs: dict[str, Any] = {
            "FilterExpression": "begins_with(PK, :prefix) AND SK = :sk",
            "ExpressionAttributeValues": {":prefix": "CLIENT#", ":sk": "META"},
            "Limit": limit,
        }
        if cursor:
            kwargs["ExclusiveStartKey"] = _decode_cursor(cursor)

        resp = self.table.scan(**kwargs)
        clients = [OAuthClient.from_dynamo(i) for i in resp.get("Items", [])]
        lek = resp.get("LastEvaluatedKey")
        next_cursor = _encode_cursor(lek) if lek else None
        return clients, next_cursor

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
        """Query activity log for a specific date (YYYY-MM-DD).

        Queries all 24 hour-sharded partitions (LOG#{date}#{HH}) in parallel
        and merges results. Also queries the legacy LOG#{date} partition for
        backward compatibility with items written before the hour-sharding migration.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _query(pk: str) -> list[ActivityEvent]:
            resp = self.table.query(KeyConditionExpression=Key("PK").eq(pk))
            return [ActivityEvent.from_dynamo(i) for i in resp.get("Items", [])]

        # Build all partition keys: 24 hour shards + legacy unsharded key
        pks = [f"LOG#{date}#{hour:02d}" for hour in range(24)]
        pks.append(f"LOG#{date}")  # backward compat

        events: list[ActivityEvent] = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(_query, pk): pk for pk in pks}
            for future in as_completed(futures):
                events.extend(future.result())

        return events

    def get_events_for_dates(
        self,
        dates: list[str],
        limit: int = 100,
    ) -> list[ActivityEvent]:
        """Fetch events across multiple dates, sorted newest-first, capped at limit."""
        events: list[ActivityEvent] = []
        for d in dates:
            events.extend(self.get_events_for_date(d))
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

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
