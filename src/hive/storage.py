# Copyright (c) 2026 John Carter. All rights reserved.
"""
DynamoDB storage layer for Hive.

Single-table design — all entities share one table.
Table name is read from the HIVE_TABLE_NAME environment variable.

GSIs:
  TagIndex        — GSI2PK (TAG#{tag}), GSI2SK (memory_id) → list_memories(tag)
  ClientIndex     — GSI3PK (CLIENT#{client_id})            → client lookups
  ApiKeyHashIndex — key_hash (sparse, APIKEY# items only)  → API key auth lookups
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from hive.logging_config import get_logger
from hive.models import (
    ActivityEvent,
    ApiKey,
    AuthorizationCode,
    Invite,
    Memory,
    MemoryVersion,
    MgmtPendingState,
    OAuthClient,
    PendingAuth,
    Token,
    TokenType,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)

logger = get_logger("hive.storage")

TABLE_NAME = os.environ.get("HIVE_TABLE_NAME", "hive")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
DYNAMODB_ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT")

# Reusable DynamoDB filter expression fragments
_UID_FILTER = " AND owner_user_id = :uid"
_WSID_FILTER = " AND workspace_id = :wsid"
_PK_PREFIX_KEY = ":prefix"
_SK_PK_PREFIX_EXPR = "SK = :sk AND begins_with(PK, :prefix)"
_APIKEY_PK_PREFIX = "APIKEY#"

# Version retention
_VERSION_RETENTION_DAYS = int(os.environ.get("HIVE_VERSION_RETENTION_DAYS", "30"))

# How old a KEYCLAIM item with no backing memory must be before an if-absent
# create may treat it as a crashed-create orphan and take it over (#592).
# Generous enough to cover the slowest legitimate create (S3 routing of a
# large value + batched DynamoDB writes) plus cross-Lambda clock skew.
_KEYCLAIM_GRACE_SECONDS = int(os.environ.get("HIVE_KEYCLAIM_GRACE_SECONDS", "60"))

# Token lifetimes
ACCESS_TOKEN_TTL_SECONDS = 3600  # 1 hour
REFRESH_TOKEN_TTL_SECONDS = 86400 * 30  # 30 days
AUTH_CODE_TTL_SECONDS = 300  # 5 minutes
PENDING_AUTH_TTL_SECONDS = 600  # 10 minutes (enough for Google login flow)
MGMT_PENDING_STATE_TTL_SECONDS = 600  # 10 minutes (enough for Google login flow)


class VersionConflict(Exception):
    """Raised by put_memory when an optimistic-lock version check fails (#391).

    Carries the state the caller needs to compare-and-retry without an
    extra round-trip: the attempted version, the actual current value,
    and the actual current version.
    """

    def __init__(
        self,
        attempted_version: str,
        current_value: str | None,
        current_version: str | None,
    ) -> None:
        self.attempted_version = attempted_version
        self.current_value = current_value
        self.current_version = current_version
        super().__init__(f"Memory was updated since version {attempted_version!r}")


class AuthCodeAlreadyUsed(Exception):
    """Raised by ``mark_auth_code_used`` when the conditional write is rejected.

    Two conditions trip the conditional ``UpdateItem``:

    1. Another redemption raced ahead and flipped ``used`` to ``true``
       (the RFC 6749 §10.5 single-use case this fix exists for).
    2. No AUTHCODE item exists under the supplied key — the
       ``attribute_exists(PK)`` guard rejects forged / never-issued
       codes so callers can't mint tokens from arbitrary strings.

    Both are indistinguishable from the client's perspective: the
    token endpoint maps either to ``400 "Invalid or already-used
    code"``. The name stays narrow because concurrent redemption is
    the motivating case; the forged-code path is a defensive
    side-effect of the same condition.
    """


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_claim_timestamp(raw: Any) -> datetime:
    """Parse a KEYCLAIM item's ``created_at`` defensively.

    Claims are only ever written with an aware-UTC isoformat, but a
    malformed item must degrade to "reclaimable" (epoch — maximally old)
    rather than crash the reclaim path and leave its key permanently
    blocked by an unreclaimable claim. Naive datetimes are assumed UTC so
    the subtraction against the aware ``_now()`` can never raise.
    """
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _encode_cursor(last_evaluated_key: dict[str, Any]) -> str:
    """Encode a DynamoDB LastEvaluatedKey as an opaque base64 cursor."""
    return base64.urlsafe_b64encode(json.dumps(last_evaluated_key).encode()).decode()


def _decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode a base64 cursor back to a DynamoDB ExclusiveStartKey."""
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except Exception as exc:
        raise ValueError("Invalid pagination cursor") from exc
    if not isinstance(decoded, dict):
        raise ValueError("Invalid pagination cursor")
    return decoded


def _is_usertag_cursor(decoded: dict[str, Any]) -> bool:
    """Return True when the decoded cursor belongs to the USERTAG consistent path.

    USERTAG LastEvaluatedKeys have PK=USERTAG#{user_id}, making them naturally
    distinguishable from TagIndex GSI cursors which carry GSI2PK/GSI2SK fields.
    """
    return str(decoded.get("PK", "")).startswith("USERTAG#")


class HiveStorage:
    """All DynamoDB read/write operations for Hive."""

    def __init__(
        self,
        table_name: str | None = None,
        region: str | None = None,
        blob_store: Any = None,
        **kwargs: Any,
    ) -> None:
        # Read env vars at call time so tests can override them after import
        table_name = table_name or os.environ.get("HIVE_TABLE_NAME", "hive")
        region = region or os.environ.get("AWS_REGION", "us-east-1")
        # Auto-use DYNAMODB_ENDPOINT for local dev / integration tests
        kwargs.setdefault("endpoint_url", os.environ.get("DYNAMODB_ENDPOINT"))
        dynamodb = boto3.resource("dynamodb", region_name=region, **kwargs)
        self.table = dynamodb.Table(table_name)
        # Lazily-instantiated BlobStore — we only need it on the
        # text-large / binary path so tests that never exercise that
        # branch can leave HIVE_BLOBS_BUCKET unset. Inject a mock via
        # the ``blob_store`` kwarg in tests.
        self._blob_store_override = blob_store
        self._blob_store: Any = None

    @property
    def blob_store(self) -> Any:
        """Lazy BlobStore handle — constructed on first use."""
        if self._blob_store_override is not None:
            return self._blob_store_override
        # Import inline to avoid circular-import risk at module load.
        if self._blob_store is None:
            from hive.blob_store import BlobStore

            self._blob_store = BlobStore()
        return self._blob_store

    # ------------------------------------------------------------------
    # Memory CRUD
    # ------------------------------------------------------------------

    def put_memory(self, memory: Memory, *, expected_version: str | None = None) -> None:
        """Write (create or replace) a memory and all its tag items.

        When replacing an existing memory, the previous state is snapshotted
        as a VERSION item so it can be retrieved via list_memory_versions.

        If ``expected_version`` is provided, the META item is written with a
        conditional expression requiring the stored ``updated_at`` to match
        — supporting optimistic locking (#391). Raises ``VersionConflict``
        if the stored version has moved on since the caller read it.

        Large-memory routing (#497): text values over the inline
        threshold are uploaded to S3 and the META item stores only
        ``s3_uri`` + ``size_bytes``. The routing happens in-place on
        the passed ``memory`` so callers always see the persisted
        shape.
        """
        self._route_large_value(memory)
        existing_raw = self._get_memory_meta(memory.memory_id)
        if expected_version is not None:
            if existing_raw is None:
                raise VersionConflict(
                    attempted_version=expected_version,
                    current_value=None,
                    current_version=None,
                )
            current = Memory.from_dynamo(existing_raw)
            if current.version != expected_version:
                raise VersionConflict(
                    attempted_version=expected_version,
                    current_value=current.value,
                    current_version=current.version,
                )

        if existing_raw:
            old = Memory.from_dynamo(existing_raw)
            self._delete_tag_items(old)
            self.save_memory_version(old)

        meta_item = memory.to_dynamo_meta()
        tag_items = memory.to_dynamo_tag_items()
        user_tag_items = memory.to_dynamo_user_tag_items() if memory.owner_user_id else []
        try:
            if expected_version is not None:
                # Conditional put on the META item to close the TOCTOU window
                # between the read above and the write below. Tag items get
                # rewritten unconditionally — they carry no value state and
                # are rebuilt from the memory's tag list on every put.
                self.table.put_item(
                    Item=meta_item,
                    ConditionExpression=Attr("updated_at").eq(expected_version),
                )
                with self.table.batch_writer() as batch:
                    for tag_item in tag_items:
                        batch.put_item(Item=tag_item)
                    for user_tag_item in user_tag_items:
                        batch.put_item(Item=user_tag_item)
            else:
                with self.table.batch_writer() as batch:
                    batch.put_item(Item=meta_item)
                    for tag_item in tag_items:
                        batch.put_item(Item=tag_item)
                    for user_tag_item in user_tag_items:
                        batch.put_item(Item=user_tag_item)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            msg = exc.response["Error"]["Message"]
            if code == "ConditionalCheckFailedException":
                latest = self._get_memory_meta(memory.memory_id)
                latest_mem = Memory.from_dynamo(latest) if latest else None
                raise VersionConflict(
                    attempted_version=expected_version or "",
                    current_value=latest_mem.value if latest_mem else None,
                    current_version=latest_mem.version if latest_mem else None,
                ) from exc
            if code == "ValidationException" and "size" in msg.lower():
                raise ValueError(
                    "Memory value is too large to store (DynamoDB 400 KB item limit exceeded)."
                ) from exc
            raise

    def _route_large_value(self, memory: Memory) -> None:
        """Offload oversized text to S3, leaving a pointer in DynamoDB.

        Handles both initial writes and updates for text and text-large
        memories. Binary types (image/blob, arriving via #499) are expected
        to already carry an ``s3_uri`` — this router only handles the
        transparent-text path where a caller hands us a string and expects
        the right backend to be chosen automatically.
        """
        from hive.blob_store import INLINE_TEXT_THRESHOLD_BYTES, MAX_BLOB_SIZE_BYTES

        # Binary paths (image, blob) have their own upload lifecycle (#499).
        if memory.value_type not in ("text", "text-large"):
            return

        # A text-large memory fetched from DynamoDB has value="" (blob already
        # in S3). Re-route only when the caller has provided a new value (the
        # remember-update path). An empty value means the existing S3 object
        # is unchanged.
        if memory.value_type == "text-large":
            if not memory.value:
                return
            memory.value_type = "text"

        if memory.value is None:
            return

        encoded = memory.value.encode("utf-8")
        if len(encoded) > MAX_BLOB_SIZE_BYTES:
            raise ValueError(
                f"Value size {len(encoded)} bytes exceeds the maximum of "
                f"{MAX_BLOB_SIZE_BYTES} bytes."
            )
        if len(encoded) <= INLINE_TEXT_THRESHOLD_BYTES:
            # Inline path: unchanged. Capture size_bytes for the
            # forthcoming two-dimension quota (#500) even on the
            # small path so rollups are consistent.
            memory.size_bytes = len(encoded)
            return

        # Promote to text-large — write body to S3 under the
        # workspace-equivalent prefix (user id today, workspace id
        # post-#482).
        owner = memory.owner_user_id or memory.owner_client_id
        s3_uri = self.blob_store.put(
            owner=owner,
            memory_id=memory.memory_id,
            body=encoded,
            content_type="text/plain; charset=utf-8",
        )
        memory.value_type = "text-large"
        memory.s3_uri = s3_uri
        memory.size_bytes = len(encoded)
        memory.content_type = "text/plain; charset=utf-8"
        # Drop the inline value — DynamoDB only keeps the pointer.
        memory.value = ""

    def put_memory_if_absent(self, memory: Memory) -> bool:
        """Atomically create a memory only if its key is not already claimed.

        Key uniqueness lives on the KeyIndex GSI (``GSI1PK=KEY#{key}``), and
        neither a GSI nor a condition on the META item (whose PK is a fresh
        surrogate UUID) can enforce it. The atomic unit is therefore a
        dedicated key-claim item (``PK=KEYCLAIM#{key}``, ``SK=META``) written
        with a conditional ``PutItem`` (``attribute_not_exists(PK)``).
        DynamoDB serialises conditional writes on the same item, so exactly
        one of any number of concurrent callers wins the claim (#592).

        A lost conditional write is not automatically "exists": the holder
        is resolved via ``_reclaim_stale_key``, which distinguishes a claim
        backed by a live memory (return ``False``) from a stale one — a
        crashed create that never wrote its memory, or a memory that has
        since expired — which is cleared and re-claimed atomically. Claim
        lifetime is deliberately decoupled from the memory's TTL: liveness
        is decided at conflict time against the memory item itself, so a
        TTL later added, extended, or removed via ``remember``/the API can
        never strand or prematurely free the claim.

        Returns ``True`` when the claim and the memory write both succeed,
        ``False`` when the key is already claimed by a live (or in-flight)
        memory. If the memory write fails after a successful claim, the
        claim is rolled back and the error re-raised.

        Claims are released by ``delete_memory`` / ``delete_memories_by_tag``
        so a forgotten key can be re-created. Memories created through other
        paths (``remember``'s create branch, the management API) carry no
        claim; callers must pair this method with a ``get_memory_by_key``
        pre-check to preserve if-absent semantics against those.
        """
        if not self._try_claim_key(memory) and not self._reclaim_stale_key(memory):
            return False
        try:
            self.put_memory(memory)
        except Exception:
            # Roll back the claim so a failed create doesn't poison the key.
            self._release_key_claim(memory.key, memory.memory_id)
            raise
        return True

    def _try_claim_key(self, memory: Memory) -> bool:
        """Conditionally write the key-claim item for ``memory``.

        Returns ``True`` when the claim was won, ``False`` when another
        claim already holds the key. Any other DynamoDB error re-raises.
        """
        claim: dict[str, Any] = {
            "PK": f"KEYCLAIM#{memory.key}",
            "SK": "META",
            "key": memory.key,
            "memory_id": memory.memory_id,
            "created_at": _now().isoformat(),
        }
        try:
            self.table.put_item(
                Item=claim,
                ConditionExpression=Attr("PK").not_exists(),
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def _reclaim_stale_key(self, memory: Memory) -> bool:
        """After a lost claim, decide live-vs-stale and re-claim if stale.

        A claim is *stale* when its ``memory_id`` no longer resolves to a
        live memory: either the memory expired, or a previous create
        crashed between writing the claim and writing the memory. The
        latter is indistinguishable from an in-flight create, so a claim
        with no memory is only treated as stale once it is older than
        ``_KEYCLAIM_GRACE_SECONDS`` — younger claims are reported as
        "exists" to protect a concurrent creator mid-write.

        Both reads use ``ConsistentRead`` — deciding staleness from an
        eventually-consistent replica could miss a just-committed memory
        and clear a live claim. The stale claim is deleted *conditionally*
        on its observed ``memory_id`` so a claim that changed hands in the
        meantime is never cleared out from under its new owner; the
        conditional put is then retried exactly once. At most one of any
        number of concurrent reclaimers can pass the conditional delete,
        so single-create is preserved.
        """
        holder = (
            self.table.get_item(
                Key={"PK": f"KEYCLAIM#{memory.key}", "SK": "META"},
                ConsistentRead=True,
            )
        ).get("Item")
        if holder is not None:
            # Defensive .get — a malformed claim (no memory_id) must degrade
            # to "stale" rather than crash and leave its key blocked.
            holder_memory_id = holder.get("memory_id")
            meta = None
            if holder_memory_id is not None:
                meta = (
                    self.table.get_item(
                        Key={"PK": f"MEMORY#{holder_memory_id}", "SK": "META"},
                        ConsistentRead=True,
                    )
                ).get("Item")
            if meta is not None and not Memory.from_dynamo(meta).is_expired:
                return False  # a live memory holds the key
            if meta is None:
                claimed_at = _parse_claim_timestamp(holder.get("created_at"))
                if (_now() - claimed_at).total_seconds() < _KEYCLAIM_GRACE_SECONDS:
                    return False  # likely an in-flight create — don't steal it
            try:
                self.table.delete_item(
                    Key={"PK": f"KEYCLAIM#{memory.key}", "SK": "META"},
                    # Delete only the claim we observed: match its memory_id,
                    # or require the attribute still absent for a malformed
                    # claim, so one that changed hands is never cleared.
                    ConditionExpression=(
                        Attr("memory_id").eq(holder_memory_id)
                        if holder_memory_id is not None
                        else Attr("memory_id").not_exists()
                    ),
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    return False  # another caller re-claimed the key first
                raise
        # Claim cleared (or vanished between the lost put and the read) —
        # retry the conditional write exactly once.
        return self._try_claim_key(memory)

    def _release_key_claim(self, key: str, memory_id: str) -> None:
        """Best-effort delete of ``key``'s claim, only if ``memory_id`` owns it.

        The delete is conditional on the claim's ``memory_id`` matching the
        memory being deleted: if duplicate same-key memories exist (possible
        via the non-if-absent create paths, or historically from the
        pre-#592 race), deleting one of them must not clear the claim that
        belongs to the other, still-live memory. A failed condition is the
        expected no-op for memories that never held a claim.

        This conditionality cannot strand an orphaned claim: a claim whose
        memory is gone is reclaimed by ``_reclaim_stale_key`` on the next
        if-absent create once the grace period passes.

        Other failures are logged and swallowed (mirroring
        ``_delete_blob_if_needed``): by the time this runs the memory
        delete has already happened, so a throttled claim cleanup must not
        turn an otherwise-successful delete into an API/tool error.
        """
        try:
            self.table.delete_item(
                Key={"PK": f"KEYCLAIM#{key}", "SK": "META"},
                ConditionExpression=Attr("memory_id").eq(memory_id),
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return  # no claim, or the claim belongs to another memory
            logger.warning("Failed to release key claim for %r (non-fatal)", key, exc_info=True)

    def get_memory_by_id(self, memory_id: str) -> Memory | None:
        item = self._get_memory_meta(memory_id)
        if item is None:
            return None
        memory = Memory.from_dynamo(item)
        if memory.is_expired:
            return None
        return memory

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

    def record_recall(self, key: str) -> Memory | None:
        """Atomically increment ``recall_count`` and refresh ``last_accessed_at``
        on the memory with the given key, returning the updated Memory.

        Returns ``None`` if the key doesn't exist or the memory is expired.
        Does the work in a single DynamoDB ``update_item`` (with ``ALL_NEW``
        return values) so we don't pay two round-trips per recall.
        """
        resp = self.table.query(
            IndexName="KeyIndex",
            KeyConditionExpression=Key("GSI1PK").eq(f"KEY#{key}"),
            Limit=1,
        )
        items = resp.get("Items", [])
        if not items:
            return None
        memory_id = items[0]["memory_id"]
        now_iso = _now().isoformat()
        updated = self.table.update_item(
            Key={"PK": f"MEMORY#{memory_id}", "SK": "META"},
            UpdateExpression=("SET last_accessed_at = :now ADD recall_count :one"),
            ExpressionAttributeValues={":now": now_iso, ":one": Decimal("1")},
            ReturnValues="ALL_NEW",
        )
        # ALL_NEW always populates Attributes once the KeyIndex lookup above
        # has confirmed the item exists, so there's no "None" path to guard.
        memory = Memory.from_dynamo(updated["Attributes"])
        if memory.is_expired:
            return None
        return memory

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory and all its tag items. Returns True if found."""
        existing = self._get_memory_meta(memory_id)
        if existing is None:
            return False
        memory = Memory.from_dynamo(existing)
        self._delete_tag_items(memory)
        self.table.delete_item(Key={"PK": f"MEMORY#{memory_id}", "SK": "META"})
        self._delete_blob_if_needed(memory)
        self._release_key_claim(memory.key, memory.memory_id)
        return True

    # ------------------------------------------------------------------
    # Memory version history
    # ------------------------------------------------------------------

    def save_memory_version(self, memory: Memory) -> MemoryVersion:
        """Snapshot the current state of a memory as a VERSION item."""
        version = MemoryVersion.from_memory(memory)
        item = version.to_dynamo()
        # Set TTL so old versions are auto-pruned
        expires = _now() + timedelta(days=_VERSION_RETENTION_DAYS)
        item["ttl"] = int(expires.timestamp())
        self.table.put_item(Item=item)
        return version

    def list_memory_versions(self, memory_id: str) -> list[MemoryVersion]:
        """Return all version snapshots for a memory, newest first."""
        resp = self.table.query(
            KeyConditionExpression=Key("PK").eq(f"MEMORY#{memory_id}")
            & Key("SK").begins_with("VERSION#"),
            ScanIndexForward=False,
        )
        return [MemoryVersion.from_dynamo(item) for item in resp.get("Items", [])]

    def get_memory_version(self, memory_id: str, version_timestamp: str) -> MemoryVersion | None:
        """Fetch a specific version snapshot."""
        resp = self.table.get_item(
            Key={"PK": f"MEMORY#{memory_id}", "SK": f"VERSION#{version_timestamp}"}
        )
        item = resp.get("Item")
        if item is None:
            return None
        return MemoryVersion.from_dynamo(item)

    def hydrate_memory_ids(
        self, id_score_pairs: list[tuple[str, float]]
    ) -> list[tuple[Memory, float]]:
        """Fetch full Memory objects for a list of (memory_id, score) pairs.

        Pairs whose memory_id no longer exists in DynamoDB (deleted between the
        vector write and this lookup) are silently filtered out.  Result order
        mirrors the input order so relevance ranking is preserved.
        """
        results: list[tuple[Memory, float]] = []
        for memory_id, score in id_score_pairs:
            memory = self.get_memory_by_id(memory_id)
            if memory is not None:
                results.append((memory, score))
        return results

    def list_distinct_tags(self, owner_user_id: str) -> list[str]:
        """Return the sorted distinct tags across the user account's memories.

        Queries the strongly-consistent USERTAG items (PK=USERTAG#{user_id},
        SK=TAG#{tag}#MEMORY#{id}) so the result is account-scoped — matching the
        ``owner_user_id`` boundary used by list_memories / summarize_context
        (#666) — and reads-your-writes without TagIndex GSI propagation lag
        (#653). The base table is never scanned.
        """
        tags: set[str] = set()
        start_key: dict[str, Any] | None = None
        while True:
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": Key("PK").eq(f"USERTAG#{owner_user_id}")
                & Key("SK").begins_with("TAG#"),
                "ProjectionExpression": "SK",
                "ConsistentRead": True,
            }
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            resp = self.table.query(**kwargs)
            for item in resp.get("Items", []):
                sk = item.get("SK", "")
                # SK = TAG#{tag}#MEMORY#{memory_id}; rsplit isolates the tag even
                # if the tag itself contains '#'.
                tag = sk[len("TAG#") :].rsplit("#MEMORY#", 1)[0] if sk.startswith("TAG#") else ""
                if tag:
                    tags.add(tag)
            start_key = resp.get("LastEvaluatedKey")
            if not start_key:
                break
        return sorted(tags)

    def list_memories_by_tag(
        self,
        tag: str,
        limit: int = 100,
        cursor: str | None = None,
        owner_user_id: str | None = None,
        owner_client_id: str | None = None,
        workspace_id: str | None = None,
    ) -> tuple[list[Memory], str | None]:
        """Query for memories with a given tag.

        When ``owner_user_id`` is provided, the strongly-consistent USERTAG
        path is used: items live on the base table
        (PK=USERTAG#{user_id}, SK=TAG#{tag}#MEMORY#{id}) and support
        ConsistentRead=True, giving read-your-writes guarantees (#568).
        USERTAG cursors are detected by a ``PK`` starting with ``USERTAG#``
        in the decoded key; subsequent pages continue on the consistent path.

        When owner_user_id is absent (or the cursor belongs to the GSI path),
        the TagIndex GSI is used (eventually consistent). The ``workspace_id``
        filter is always applied in-memory on the hydrated results.

        Returns (memories, next_cursor). next_cursor is None when exhausted.
        """
        if owner_user_id is not None:
            decoded_cursor = _decode_cursor(cursor) if cursor else None
            if decoded_cursor is None or _is_usertag_cursor(decoded_cursor):
                return self._list_memories_by_tag_consistent(
                    tag=tag,
                    owner_user_id=owner_user_id,
                    owner_client_id=owner_client_id,
                    limit=limit,
                    workspace_id=workspace_id,
                    start_key=decoded_cursor,
                )

        kwargs: dict[str, Any] = {
            "IndexName": "TagIndex",
            "KeyConditionExpression": Key("GSI2PK").eq(f"TAG#{tag}"),
            "Limit": limit,
        }
        # TAG items carry owner_client_id, so when scoping by client filter them
        # server-side: other tenants' items are never hydrated via
        # get_memory_by_id (cheaper on the bulk-delete path) and never leave
        # DynamoDB — defense-in-depth for the cross-tenant guard
        # (GHSA-h9vh-rpcv-xqrr). The post-hydration owner check below stays as a
        # second line of defence against stale tag items.
        if owner_client_id is not None:
            kwargs["FilterExpression"] = Attr("owner_client_id").eq(owner_client_id)
        if cursor:
            kwargs["ExclusiveStartKey"] = _decode_cursor(cursor)

        resp = self.table.query(**kwargs)
        memories: list[Memory] = []
        for item in resp.get("Items", []):
            m = self.get_memory_by_id(item["memory_id"])
            if m is None:
                continue
            if owner_user_id is not None and m.owner_user_id != owner_user_id:
                continue
            if owner_client_id is not None and m.owner_client_id != owner_client_id:
                continue
            if workspace_id is not None and m.workspace_id != workspace_id:
                continue
            memories.append(m)

        lek = resp.get("LastEvaluatedKey")
        next_cursor = _encode_cursor(lek) if lek else None
        return memories, next_cursor

    def _list_memories_by_tag_consistent(
        self,
        tag: str,
        owner_user_id: str,
        owner_client_id: str | None = None,
        limit: int = 100,
        workspace_id: str | None = None,
        start_key: dict[str, Any] | None = None,
    ) -> tuple[list[Memory], str | None]:
        """Strongly-consistent tag query via USERTAG base-table items.

        Queries PK=USERTAG#{owner_user_id} with SK beginning with
        TAG#{tag}#MEMORY# using ConsistentRead=True. Returns immediately
        after the first write without waiting for GSI propagation (#568).
        Supports full cursor-based pagination via DynamoDB LastEvaluatedKey.
        """
        expected_pk = f"USERTAG#{owner_user_id}"
        expected_sk_prefix = f"TAG#{tag}#MEMORY#"
        if start_key is not None:
            sk = start_key.get("SK", "")
            if start_key.get("PK") != expected_pk or not (
                isinstance(sk, str) and sk.startswith(expected_sk_prefix)
            ):
                raise ValueError("Invalid pagination cursor")

        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(expected_pk)
            & Key("SK").begins_with(expected_sk_prefix),
            "ConsistentRead": True,
            "Limit": limit,
        }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key

        resp = self.table.query(**kwargs)
        memories: list[Memory] = []
        for item in resp.get("Items", []):
            m = self.get_memory_by_id(item["memory_id"])
            if m is None:
                continue
            # Defence-in-depth: META owner must still match — guards against
            # stale/corrupt USERTAG items pointing at a re-owned memory.
            if m.owner_user_id != owner_user_id:
                continue
            if owner_client_id is not None and m.owner_client_id != owner_client_id:
                continue
            if workspace_id is not None and m.workspace_id != workspace_id:
                continue
            memories.append(m)

        lek = resp.get("LastEvaluatedKey")
        next_cursor = _encode_cursor(lek) if lek else None
        return memories, next_cursor

    def list_all_memories(
        self,
        client_id: str | None = None,
        owner_user_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[Memory], str | None]:
        """Scan for all META memory items (optionally filtered by owner_client_id,
        owner_user_id, or workspace_id).

        Returns (memories, next_cursor). Use sparingly — prefer tag-based queries.

        Iterates DynamoDB scan pages until *limit* matching items are collected,
        avoiding the "Limit evaluates N items before filter" footgun that causes
        misses in single-table designs with mixed item types.
        """
        filter_expr = "SK = :sk AND begins_with(PK, :pk_prefix)"
        expr_vals: dict[str, Any] = {":sk": "META", ":pk_prefix": "MEMORY#"}
        if client_id:
            filter_expr += " AND owner_client_id = :cid"
            expr_vals[":cid"] = client_id
        if owner_user_id:
            filter_expr += _UID_FILTER
            expr_vals[":uid"] = owner_user_id
        if workspace_id:
            filter_expr += _WSID_FILTER
            expr_vals[":wsid"] = workspace_id

        start_key = _decode_cursor(cursor) if cursor else None
        memories: list[Memory] = []

        while True:
            kwargs: dict[str, Any] = {
                "FilterExpression": filter_expr,
                "ExpressionAttributeValues": expr_vals,
            }
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key

            resp = self.table.scan(**kwargs)
            for item in resp.get("Items", []):
                memories.append(Memory.from_dynamo(item))
                if len(memories) >= limit:
                    break

            lek = resp.get("LastEvaluatedKey")
            if len(memories) >= limit:
                last = memories[limit - 1]
                next_key = {"PK": f"MEMORY#{last.memory_id}", "SK": "META"}
                return memories[:limit], _encode_cursor(next_key)
            if lek is None:
                return memories, None
            start_key = lek

    def delete_memories_by_tag(
        self,
        tag: str,
        owner_user_id: str | None = None,
        owner_client_id: str | None = None,
        workspace_id: str | None = None,
    ) -> int:
        """Delete all memories with the given tag.

        Deletion is scoped to whichever owner filter is supplied
        (``owner_user_id``, ``owner_client_id``, and/or ``workspace_id``); only
        matching memories are deleted. Passing **no** filter deletes every
        memory with the tag across all owners, so a caller acting on behalf of
        a single tenant MUST pass its scope (``owner_client_id`` at minimum) to
        avoid cross-tenant deletion. Returns the count of memories deleted.
        """
        deleted = 0
        cursor: str | None = None
        while True:
            items, cursor = self.list_memories_by_tag(
                tag,
                limit=100,
                cursor=cursor,
                owner_user_id=owner_user_id,
                owner_client_id=owner_client_id,
                workspace_id=workspace_id,
            )
            for memory in items:
                self._delete_tag_items(memory)
                self.table.delete_item(Key={"PK": f"MEMORY#{memory.memory_id}", "SK": "META"})
                self._delete_blob_if_needed(memory)
                self._release_key_claim(memory.key, memory.memory_id)
                deleted += 1
            if cursor is None:
                break
        return deleted

    def iter_all_memories(
        self,
        owner_user_id: str | None = None,
        workspace_id: str | None = None,
        tag: str | None = None,
    ) -> Iterator[Memory]:
        """Yield all memories, optionally filtered by owner, workspace, or tag.

        For tag-filtered export, iterates TagIndex pages.
        For unfiltered export, scans all META items.
        This is a generator — use for streaming exports only.
        """
        if tag:
            cursor: str | None = None
            while True:
                items, cursor = self.list_memories_by_tag(
                    tag,
                    limit=100,
                    cursor=cursor,
                    owner_user_id=owner_user_id,
                    workspace_id=workspace_id,
                )
                yield from items
                if cursor is None:
                    break
        else:
            filter_expr = "SK = :sk AND begins_with(PK, :pk_prefix)"
            expr_vals: dict[str, Any] = {":sk": "META", ":pk_prefix": "MEMORY#"}
            if owner_user_id:
                filter_expr += _UID_FILTER
                expr_vals[":uid"] = owner_user_id
            if workspace_id:
                filter_expr += _WSID_FILTER
                expr_vals[":wsid"] = workspace_id
            start_key: dict[str, Any] | None = None
            while True:
                kwargs: dict[str, Any] = {
                    "FilterExpression": filter_expr,
                    "ExpressionAttributeValues": expr_vals,
                }
                if start_key:
                    kwargs["ExclusiveStartKey"] = start_key
                resp = self.table.scan(**kwargs)
                for item in resp.get("Items", []):
                    yield Memory.from_dynamo(item)
                start_key = resp.get("LastEvaluatedKey")
                if start_key is None:
                    break

    def iter_memories_for_export(
        self, owner_user_id: str, workspace_ids: list[str]
    ) -> Iterator[Memory]:
        """Yield memories the user authored anywhere plus every memory in
        the given (personal) workspaces, in a single table scan.

        Backs the GDPR export (#495): one pass with a server-side OR
        filter instead of one scan per criterion. This is a generator —
        use for streaming exports only.
        """
        filter_expr = f"{_SK_PK_PREFIX_EXPR} AND (owner_user_id = :uid"
        expr_vals: dict[str, Any] = {
            ":sk": "META",
            _PK_PREFIX_KEY: "MEMORY#",
            ":uid": owner_user_id,
        }
        if workspace_ids:
            placeholders = []
            for i, ws_id in enumerate(workspace_ids):
                key = f":wsid{i}"
                expr_vals[key] = ws_id
                placeholders.append(key)
            filter_expr += f" OR workspace_id IN ({', '.join(placeholders)})"
        filter_expr += ")"
        start_key: dict[str, Any] | None = None
        while True:
            kwargs: dict[str, Any] = {
                "FilterExpression": filter_expr,
                "ExpressionAttributeValues": expr_vals,
            }
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            resp = self.table.scan(**kwargs)
            for item in resp.get("Items", []):
                yield Memory.from_dynamo(item)
            start_key = resp.get("LastEvaluatedKey")
            if start_key is None:
                break

    # ------------------------------------------------------------------
    # OAuth Client management
    # ------------------------------------------------------------------

    def put_client(self, client: OAuthClient) -> None:
        self.table.put_item(Item=client.to_dynamo())

    def get_client(self, client_id: str) -> OAuthClient | None:
        resp = self.table.get_item(Key={"PK": f"CLIENT#{client_id}", "SK": "META"})
        item = resp.get("Item")
        return OAuthClient.from_dynamo(item) if item else None

    def bind_client_owner(self, client_id: str, user_id: str) -> bool:
        """Atomically set a client's ``owner_user_id`` iff it is currently unset.

        Returns ``True`` when this call performed the binding, ``False`` when the
        client was already owned (a concurrent first-bind won, or it was
        pre-owned, or the client no longer exists). Enforces first-bind-wins at
        the DynamoDB layer via a conditional write, closing the
        read-modify-write race in the OAuth callback — mirrors the single-use
        enforcement in :meth:`mark_auth_code_used`.
        """
        try:
            self.table.update_item(
                Key={"PK": f"CLIENT#{client_id}", "SK": "META"},
                UpdateExpression="SET owner_user_id = :uid",
                ConditionExpression="attribute_exists(PK) AND attribute_not_exists(owner_user_id)",
                ExpressionAttributeValues={":uid": user_id},
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def bind_client_workspace(self, client_id: str, workspace_id: str) -> bool:
        """Atomically set a client's ``workspace_id`` iff it is currently unset.

        Returns ``True`` when this call performed the binding, ``False`` when
        the client was already workspace-bound (a concurrent bind won, the
        client was registered with an explicit workspace, or it no longer
        exists).  First-bind-wins at the DynamoDB layer, mirroring
        :meth:`bind_client_owner` (#491).
        """
        try:
            self.table.update_item(
                Key={"PK": f"CLIENT#{client_id}", "SK": "META"},
                UpdateExpression="SET workspace_id = :wid",
                ConditionExpression="attribute_exists(PK) AND attribute_not_exists(workspace_id)",
                ExpressionAttributeValues={":wid": workspace_id},
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def delete_client(self, client_id: str) -> bool:
        resp = self.table.get_item(Key={"PK": f"CLIENT#{client_id}", "SK": "META"})
        if not resp.get("Item"):
            return False
        self.table.delete_item(Key={"PK": f"CLIENT#{client_id}", "SK": "META"})
        return True

    def list_clients(
        self,
        owner_user_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[OAuthClient], str | None]:
        filter_expr = "begins_with(PK, :prefix) AND SK = :sk"
        expr_vals: dict[str, Any] = {_PK_PREFIX_KEY: "CLIENT#", ":sk": "META"}
        if owner_user_id:
            filter_expr += _UID_FILTER
            expr_vals[":uid"] = owner_user_id
        if workspace_id:
            filter_expr += _WSID_FILTER
            expr_vals[":wsid"] = workspace_id

        start_key = _decode_cursor(cursor) if cursor else None
        clients: list[OAuthClient] = []

        while True:
            kwargs: dict[str, Any] = {
                "FilterExpression": filter_expr,
                "ExpressionAttributeValues": expr_vals,
            }
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key

            resp = self.table.scan(**kwargs)
            for item in resp.get("Items", []):
                clients.append(OAuthClient.from_dynamo(item))
                if len(clients) >= limit:
                    break

            lek = resp.get("LastEvaluatedKey")
            if len(clients) >= limit:
                last = clients[limit - 1]
                next_key = {"PK": f"CLIENT#{last.client_id}", "SK": "META"}
                return clients[:limit], _encode_cursor(next_key)
            if lek is None:
                return clients, None
            start_key = lek

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
        """Atomically mark an OAuth authorization code as redeemed.

        RFC 6749 §10.5 requires authorization codes to be single-use.
        Two concurrent `POST /oauth/token` requests with the same `code`
        used to both pass the `auth_code.used` pre-check in
        ``oauth.py`` before either could write back — the classic
        read-check-write TOCTOU. This now enforces single-use at the
        DynamoDB layer via a conditional write on ``used = false``;
        exactly one concurrent redeemer succeeds, the other raises
        :class:`AuthCodeAlreadyUsed`.

        The caller should have already validated the code's existence,
        client binding, redirect URI, expiry, and PKCE; this call is
        the commit point of the redemption pipeline.
        """
        try:
            self.table.update_item(
                Key={"PK": f"AUTHCODE#{code}", "SK": "META"},
                UpdateExpression="SET #u = :t",
                ConditionExpression="attribute_exists(PK) AND #u = :f",
                ExpressionAttributeNames={"#u": "used"},
                ExpressionAttributeValues={":t": True, ":f": False},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise AuthCodeAlreadyUsed(
                    "Authorization code has already been redeemed or does not exist"
                ) from exc
            raise

    # ------------------------------------------------------------------
    # Pending auth (PKCE state stored while user authenticates with Google)
    # ------------------------------------------------------------------

    def put_pending_auth(self, pending: PendingAuth) -> None:
        self.table.put_item(Item=pending.to_dynamo())

    def get_pending_auth(self, state: str) -> PendingAuth | None:
        resp = self.table.get_item(Key={"PK": f"PENDING#{state}", "SK": "META"})
        item = resp.get("Item")
        return PendingAuth.from_dynamo(item) if item else None

    def delete_pending_auth(self, state: str) -> None:
        self.table.delete_item(Key={"PK": f"PENDING#{state}", "SK": "META"})

    def create_pending_auth(
        self,
        client_id: str,
        redirect_uri: str,
        scope: str,
        code_challenge: str,
        code_challenge_method: str,
        original_state: str,
    ) -> PendingAuth:
        pending = PendingAuth(
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            original_state=original_state,
            expires_at=_now() + timedelta(seconds=PENDING_AUTH_TTL_SECONDS),
        )
        self.put_pending_auth(pending)
        return pending

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
        try:
            self.table.update_item(
                Key={"PK": f"TOKEN#{jti}", "SK": "META"},
                UpdateExpression="SET revoked = :t",
                ExpressionAttributeValues={":t": True},
                ConditionExpression="attribute_exists(PK)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return  # token already expired/deleted — nothing to revoke
            raise

    def revoke_all_tokens(self) -> int:
        """Mark every outstanding token as revoked.

        Used by the workspaces migration (#490) — existing tokens don't carry
        the ``workspace_id`` claim, so forcing a re-auth is the cheapest
        correct cutover. Returns the count of token rows processed (includes
        tokens that were already revoked before this call).
        """
        revoked = 0
        start_key: dict[str, Any] | None = None
        while True:
            kwargs: dict[str, Any] = {
                "FilterExpression": "SK = :sk AND begins_with(PK, :prefix)",
                "ExpressionAttributeValues": {":sk": "META", _PK_PREFIX_KEY: "TOKEN#"},
                "ProjectionExpression": "jti",
            }
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            resp = self.table.scan(**kwargs)
            for item in resp.get("Items", []):
                self.revoke_token(item["jti"])
                revoked += 1
            start_key = resp.get("LastEvaluatedKey")
            if start_key is None:
                break
        return revoked

    def delete_tokens_for_clients(self, client_ids: set[str]) -> int:
        """Hard-delete every outstanding token issued to the given clients.

        Used by account deletion (#588) and individual client deletion
        (#711) — tokens carry short TTLs, but a still-live access or
        refresh token must not keep working after its owner's account or
        client registration is gone. Token items are not projected into
        ClientIndex, so this walks the same ``TOKEN#`` scan as
        ``revoke_all_tokens`` and deletes matches outright: validation
        fails immediately on the missing item, and DynamoDB TTL has
        nothing left to clean up. The scan is strongly consistent so
        tokens minted just before the call cannot be missed, and matches
        are deleted by their scanned ``PK`` so a malformed row without a
        ``jti`` attribute cannot abort the sweep. The batch writer
        transparently chunks deletes to BatchWriteItem's 25-item limit
        and retries unprocessed items. Returns the number of tokens
        deleted.
        """
        if not client_ids:
            return 0
        deleted = 0
        start_key: dict[str, Any] | None = None
        with self.table.batch_writer() as batch:
            while True:
                kwargs: dict[str, Any] = {
                    "FilterExpression": _SK_PK_PREFIX_EXPR,
                    "ExpressionAttributeNames": {"#pk": "PK"},
                    "ExpressionAttributeValues": {":sk": "META", _PK_PREFIX_KEY: "TOKEN#"},
                    "ProjectionExpression": "#pk, client_id",
                    "ConsistentRead": True,
                }
                if start_key:
                    kwargs["ExclusiveStartKey"] = start_key
                resp = self.table.scan(**kwargs)
                for item in resp.get("Items", []):
                    if item.get("client_id") in client_ids:
                        batch.delete_item(Key={"PK": item["PK"], "SK": "META"})
                        deleted += 1
                start_key = resp.get("LastEvaluatedKey")
                if start_key is None:
                    break
        return deleted

    def create_access_token(
        self,
        client_id: str,
        scope: str,
        workspace_id: str | None = None,
        workspace_role: str | None = None,
    ) -> Token:
        """Issue and persist a standalone access token.

        Used by the non-rotating refresh-token grant (#693), which mints a
        fresh access token while keeping the caller's existing refresh token
        valid instead of rotating it.  ``workspace_id`` / ``workspace_role``
        stamp the workspace claims (#491) carried over from the refresh token.
        """
        now = _now()
        access = Token(
            client_id=client_id,
            scope=scope,
            token_type=TokenType.access,
            issued_at=now,
            expires_at=now + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS),
            workspace_id=workspace_id,
            workspace_role=workspace_role,
        )
        self.put_token(access)
        return access

    def create_token_pair(
        self,
        client_id: str,
        scope: str,
        workspace_id: str | None = None,
        workspace_role: str | None = None,
    ) -> tuple[Token, Token]:
        """Issue a new (access_token, refresh_token) pair.

        ``workspace_id`` / ``workspace_role`` stamp the workspace claims
        (#491) on both tokens so refresh grants can carry the scope through
        unchanged.
        """
        now = _now()
        access = Token(
            client_id=client_id,
            scope=scope,
            token_type=TokenType.access,
            issued_at=now,
            expires_at=now + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS),
            workspace_id=workspace_id,
            workspace_role=workspace_role,
        )
        refresh = Token(
            client_id=client_id,
            scope=scope,
            token_type=TokenType.refresh,
            issued_at=now,
            expires_at=now + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS),
            workspace_id=workspace_id,
            workspace_role=workspace_role,
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
    # Users (management UI identities)
    # ------------------------------------------------------------------

    def put_user(self, user: User) -> None:
        self.table.put_item(Item=user.to_dynamo())

    def get_user_by_id(self, user_id: str) -> User | None:
        resp = self.table.get_item(Key={"PK": f"USER#{user_id}", "SK": "META"})
        item = resp.get("Item")
        return User.from_dynamo(item) if item else None

    def get_user_by_email(self, email: str) -> User | None:
        """Look up a user by email using the UserEmailIndex GSI."""
        resp = self.table.query(
            IndexName="UserEmailIndex",
            KeyConditionExpression=Key("GSI4PK").eq(f"EMAIL#{email}"),
            Limit=1,
        )
        items = resp.get("Items", [])
        if not items:
            return None
        return self.get_user_by_id(items[0]["user_id"])

    def update_user_role(self, user_id: str, role: str) -> bool:
        resp = self.table.get_item(Key={"PK": f"USER#{user_id}", "SK": "META"})
        if not resp.get("Item"):
            return False
        self.table.update_item(
            Key={"PK": f"USER#{user_id}", "SK": "META"},
            UpdateExpression="SET #r = :role",
            ExpressionAttributeNames={"#r": "role"},
            ExpressionAttributeValues={":role": role},
        )
        return True

    def delete_user(self, user_id: str) -> bool:
        resp = self.table.get_item(Key={"PK": f"USER#{user_id}", "SK": "META"})
        if not resp.get("Item"):
            return False
        self.table.delete_item(Key={"PK": f"USER#{user_id}", "SK": "META"})
        return True

    def list_users(
        self,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[User], str | None]:
        filter_expr = "begins_with(PK, :prefix) AND SK = :sk"
        expr_vals: dict[str, Any] = {_PK_PREFIX_KEY: "USER#", ":sk": "META"}

        start_key = _decode_cursor(cursor) if cursor else None
        users: list[User] = []

        while True:
            kwargs: dict[str, Any] = {
                "FilterExpression": filter_expr,
                "ExpressionAttributeValues": expr_vals,
            }
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key

            resp = self.table.scan(**kwargs)
            for item in resp.get("Items", []):
                users.append(User.from_dynamo(item))
                if len(users) >= limit:
                    break

            lek = resp.get("LastEvaluatedKey")
            if len(users) >= limit:
                last = users[limit - 1]
                next_key = {"PK": f"USER#{last.user_id}", "SK": "META"}
                return users[:limit], _encode_cursor(next_key)
            if lek is None:
                return users, None
            start_key = lek

    # ------------------------------------------------------------------
    # Workspaces (#490) — tenancy root; replaces per-user scoping post-cutover
    # ------------------------------------------------------------------

    def put_workspace(self, workspace: Workspace) -> None:
        """Create or overwrite a workspace META item."""
        self.table.put_item(Item=workspace.to_dynamo())

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        resp = self.table.get_item(Key={"PK": f"WORKSPACE#{workspace_id}", "SK": "META"})
        item = resp.get("Item")
        return Workspace.from_dynamo(item) if item else None

    def delete_workspace(self, workspace_id: str) -> bool:
        """Delete the workspace META item and every MEMBER item under it.

        Returns True when the META item existed, False when it was already
        absent. Member items are deleted unconditionally even when META is
        absent — orphan members under a deleted workspace would still surface
        through the ``WorkspaceMemberIndex`` GSI and confuse per-user lists.
        """
        meta_resp = self.table.get_item(Key={"PK": f"WORKSPACE#{workspace_id}", "SK": "META"})
        meta_existed = bool(meta_resp.get("Item"))
        # Always clean up MEMBER rows to prevent orphaned WorkspaceMemberIndex entries.
        members = self.list_workspace_members(workspace_id)
        with self.table.batch_writer() as batch:
            for m in members:
                batch.delete_item(
                    Key={"PK": f"WORKSPACE#{workspace_id}", "SK": f"MEMBER#{m.user_id}"}
                )
            if meta_existed:
                batch.delete_item(Key={"PK": f"WORKSPACE#{workspace_id}", "SK": "META"})
        return meta_existed

    def rename_workspace(self, workspace_id: str, name: str) -> bool:
        """Update a workspace's display name. Returns False if missing."""
        try:
            self.table.update_item(
                Key={"PK": f"WORKSPACE#{workspace_id}", "SK": "META"},
                UpdateExpression="SET #n = :name",
                ConditionExpression="attribute_exists(PK)",
                ExpressionAttributeNames={"#n": "name"},
                ExpressionAttributeValues={":name": name},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def add_workspace_member(
        self,
        workspace_id: str,
        user_id: str,
        role: WorkspaceRole = WorkspaceRole.member,
    ) -> WorkspaceMember:
        """Insert a (workspace, user, role) binding. Overwrites if it exists."""
        member = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
        self.table.put_item(Item=member.to_dynamo())
        return member

    def get_workspace_member(self, workspace_id: str, user_id: str) -> WorkspaceMember | None:
        """Fetch a (workspace, user) membership row.

        Strongly consistent (#491): membership gates auth decisions — the
        OAuth-callback membership check, token-issuance role stamping, and
        the workspace-token endpoint — which often run moments after the
        MEMBER row was written (first-login provisioning). An eventually-
        consistent read could transiently miss that write and fail a
        legitimate login closed.
        """
        resp = self.table.get_item(
            Key={"PK": f"WORKSPACE#{workspace_id}", "SK": f"MEMBER#{user_id}"},
            ConsistentRead=True,
        )
        item = resp.get("Item")
        return WorkspaceMember.from_dynamo(item) if item else None

    def list_workspace_members(self, workspace_id: str) -> list[WorkspaceMember]:
        """List every member of a workspace (paginated partition query)."""
        members: list[WorkspaceMember] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(f"WORKSPACE#{workspace_id}")
            & Key("SK").begins_with("MEMBER#"),
        }
        while True:
            resp = self.table.query(**kwargs)
            members.extend(WorkspaceMember.from_dynamo(item) for item in resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if lek is None:
                break
            kwargs["ExclusiveStartKey"] = lek
        return members

    def remove_workspace_member(self, workspace_id: str, user_id: str) -> bool:
        """Delete a (workspace, user) binding. Returns True if it existed."""
        resp = self.table.get_item(
            Key={"PK": f"WORKSPACE#{workspace_id}", "SK": f"MEMBER#{user_id}"}
        )
        if not resp.get("Item"):
            return False
        self.table.delete_item(Key={"PK": f"WORKSPACE#{workspace_id}", "SK": f"MEMBER#{user_id}"})
        return True

    def update_workspace_member_role(
        self,
        workspace_id: str,
        user_id: str,
        role: WorkspaceRole,
    ) -> bool:
        """Change a member's role. Returns False if the membership is missing."""
        try:
            self.table.update_item(
                Key={"PK": f"WORKSPACE#{workspace_id}", "SK": f"MEMBER#{user_id}"},
                UpdateExpression="SET #r = :role",
                ConditionExpression="attribute_exists(PK)",
                ExpressionAttributeNames={"#r": "role"},
                ExpressionAttributeValues={":role": role.value},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def list_workspaces_for_user(self, user_id: str) -> list[Workspace]:
        """Return every workspace the user is a member of.

        Queries ``WorkspaceMemberIndex`` on ``USER#{user_id}`` to collect
        workspace ids, then fetches the META item for each. Ordering is
        stable by workspace_id (GSI5SK) so callers can rely on it for
        deterministic UI rendering.
        """
        kwargs: dict[str, Any] = {
            "IndexName": "WorkspaceMemberIndex",
            "KeyConditionExpression": Key("GSI5PK").eq(f"USER#{user_id}")
            & Key("GSI5SK").begins_with("WORKSPACE#"),
        }
        workspaces: list[Workspace] = []
        while True:
            resp = self.table.query(**kwargs)
            for item in resp.get("Items", []):
                ws = self.get_workspace(item["workspace_id"])
                if ws is not None:
                    workspaces.append(ws)
            lek = resp.get("LastEvaluatedKey")
            if lek is None:
                break
            kwargs["ExclusiveStartKey"] = lek
        return workspaces

    def get_personal_workspace(self, user_id: str) -> Workspace | None:
        """Return the user's Personal workspace, or None if they have none.

        Checks the deterministic ``personal-{user_id}`` id first (workspaces
        auto-created by the auth flows, #491) with a strongly-consistent
        ``get_item`` — first-login provisioning reads its own write moments
        later, so the default eventually-consistent read could transiently
        miss it. Falls back to the ``WorkspaceMemberIndex`` GSI for Personal
        workspaces created with random ids by the #490 migration.
        """
        resp = self.table.get_item(
            Key={"PK": f"WORKSPACE#personal-{user_id}", "SK": "META"},
            ConsistentRead=True,
        )
        item = resp.get("Item")
        if item:
            workspace = Workspace.from_dynamo(item)
            # Trust but verify: only ensure_personal_workspace writes this id
            # namespace, but a mis-created item squatting on the deterministic
            # key must never cross tenancy boundaries — apply the same
            # predicate as the GSI fallback below and fall through otherwise.
            if workspace.is_personal and workspace.owner_user_id == user_id:
                return workspace
        for workspace in self.list_workspaces_for_user(user_id):
            if workspace.is_personal and workspace.owner_user_id == user_id:
                return workspace
        return None

    def ensure_personal_workspace(self, user: User) -> Workspace:
        """Return the user's Personal workspace, creating it if absent (#491).

        New Personal workspaces use the deterministic id
        ``personal-{user_id}`` so concurrent first-logins converge on the same
        item (both puts are idempotent overwrites of the same keys) instead of
        racing the eventually-consistent GSI lookup into duplicates.

        The owner MEMBER row is verified on every call, not just at creation —
        a crash between the two writes (or a partial manual fix) must not
        leave a Personal workspace whose owner has no membership, since role
        resolution and the workspace-token endpoint depend on that row.
        Mirrors the MEMBER-row repair in ``scripts/migrate_workspaces.py``.
        The owner's role is likewise pinned to ``owner`` — a Personal
        workspace whose owner carries any other role would stamp inconsistent
        ``workspace_role`` claims across the login and workspace-token paths.
        """
        workspace = self.get_personal_workspace(user.user_id)
        if workspace is None:
            workspace = Workspace(
                workspace_id=f"personal-{user.user_id}",
                name=f"{user.email}'s Personal",
                owner_user_id=user.user_id,
                is_personal=True,
            )
            self.put_workspace(workspace)
        member = self.get_workspace_member(workspace.workspace_id, user.user_id)
        if member is None:
            self.add_workspace_member(workspace.workspace_id, user.user_id, WorkspaceRole.owner)
        elif member.role is not WorkspaceRole.owner:
            # Personal-workspace invariant: its owner is always role=owner.
            # update (not add) preserves the original joined_at.
            self.update_workspace_member_role(
                workspace.workspace_id, user.user_id, WorkspaceRole.owner
            )
        return workspace

    # ------------------------------------------------------------------
    # Workspace invites (#490) — pending invitations to join a workspace
    # ------------------------------------------------------------------

    def put_invite(self, invite: Invite) -> None:
        self.table.put_item(Item=invite.to_dynamo())

    def get_invite(self, invite_id: str) -> Invite | None:
        resp = self.table.get_item(Key={"PK": f"INVITE#{invite_id}", "SK": "META"})
        item = resp.get("Item")
        return Invite.from_dynamo(item) if item else None

    def delete_invite(self, invite_id: str) -> bool:
        resp = self.table.get_item(Key={"PK": f"INVITE#{invite_id}", "SK": "META"})
        if not resp.get("Item"):
            return False
        self.table.delete_item(Key={"PK": f"INVITE#{invite_id}", "SK": "META"})
        return True

    def claim_invite(self, invite_id: str) -> bool:
        """Atomically consume an invite via a conditional delete.

        Returns True when this caller performed the delete, False when the
        invite was already gone (never existed, TTL-expired out, or
        concurrently redeemed). DynamoDB serialises the conditional
        deletes, so exactly one of N concurrent claimants gets True —
        mirrors the conditional-write pattern used for auth-code
        redemption.
        """
        try:
            self.table.delete_item(
                Key={"PK": f"INVITE#{invite_id}", "SK": "META"},
                ConditionExpression="attribute_exists(PK)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def list_pending_invites_for_email(self, email: str) -> list[Invite]:
        """Return every non-expired invite targeting the given email.

        Scans the full table and filters to invite META items for the given
        email — acceptable volume for the invite-accept flow (user logs in,
        we surface pending invites).
        If invite volume grows we'd back this with a GSI.
        """
        scan_kwargs: dict[str, Any] = {
            "FilterExpression": "SK = :sk AND begins_with(PK, :prefix) AND email = :email",
            "ExpressionAttributeValues": {
                ":sk": "META",
                _PK_PREFIX_KEY: "INVITE#",
                ":email": email,
            },
        }
        invites: list[Invite] = []
        while True:
            resp = self.table.scan(**scan_kwargs)
            invites.extend(Invite.from_dynamo(item) for item in resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if lek is None:
                break
            scan_kwargs["ExclusiveStartKey"] = lek
        return [i for i in invites if not i.is_expired]

    def list_pending_invites_for_workspace(self, workspace_id: str) -> list[Invite]:
        """Return every non-expired invite for the given workspace."""
        scan_kwargs: dict[str, Any] = {
            "FilterExpression": "SK = :sk AND begins_with(PK, :prefix) AND workspace_id = :wsid",
            "ExpressionAttributeValues": {
                ":sk": "META",
                _PK_PREFIX_KEY: "INVITE#",
                ":wsid": workspace_id,
            },
        }
        invites: list[Invite] = []
        while True:
            resp = self.table.scan(**scan_kwargs)
            invites.extend(Invite.from_dynamo(item) for item in resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if lek is None:
                break
            scan_kwargs["ExclusiveStartKey"] = lek
        return [i for i in invites if not i.is_expired]

    # ------------------------------------------------------------------
    # Management pending state (nonce for management UI Google login)
    # ------------------------------------------------------------------

    def put_mgmt_pending_state(self, state: MgmtPendingState) -> None:
        self.table.put_item(Item=state.to_dynamo())

    def get_mgmt_pending_state(self, state: str) -> MgmtPendingState | None:
        resp = self.table.get_item(Key={"PK": f"MGMT_STATE#{state}", "SK": "META"})
        item = resp.get("Item")
        return MgmtPendingState.from_dynamo(item) if item else None

    def delete_mgmt_pending_state(self, state: str) -> None:
        self.table.delete_item(Key={"PK": f"MGMT_STATE#{state}", "SK": "META"})

    def create_mgmt_pending_state(self) -> MgmtPendingState:
        pending = MgmtPendingState(
            expires_at=_now() + timedelta(seconds=MGMT_PENDING_STATE_TTL_SECONDS),
        )
        self.put_mgmt_pending_state(pending)
        return pending

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

    def count_memories(
        self,
        owner_user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> int:
        filter_expr = "SK = :sk AND begins_with(PK, :prefix)"
        expr_vals: dict[str, Any] = {":sk": "META", _PK_PREFIX_KEY: "MEMORY#"}
        if owner_user_id:
            filter_expr += _UID_FILTER
            expr_vals[":uid"] = owner_user_id
        if workspace_id:
            filter_expr += _WSID_FILTER
            expr_vals[":wsid"] = workspace_id
        resp = self.table.scan(
            Select="COUNT",
            FilterExpression=filter_expr,
            ExpressionAttributeValues=expr_vals,
        )
        return resp.get("Count", 0)

    def count_clients(
        self,
        owner_user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> int:
        filter_expr = "SK = :sk AND begins_with(PK, :prefix)"
        expr_vals: dict[str, Any] = {":sk": "META", _PK_PREFIX_KEY: "CLIENT#"}
        if owner_user_id:
            filter_expr += _UID_FILTER
            expr_vals[":uid"] = owner_user_id
        if workspace_id:
            filter_expr += _WSID_FILTER
            expr_vals[":wsid"] = workspace_id
        resp = self.table.scan(
            Select="COUNT",
            FilterExpression=filter_expr,
            ExpressionAttributeValues=expr_vals,
        )
        return resp.get("Count", 0)

    def count_users(self) -> int:
        resp = self.table.scan(
            Select="COUNT",
            FilterExpression="SK = :sk AND begins_with(PK, :prefix)",
            ExpressionAttributeValues={":sk": "META", _PK_PREFIX_KEY: "USER#"},
        )
        return resp.get("Count", 0)

    def sum_storage_bytes(
        self,
        owner_user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> int:
        """Return the total stored bytes across all memories for the given
        user or workspace (or all memories if both are None)."""
        filter_expr = "SK = :sk AND begins_with(PK, :prefix)"
        expr_vals: dict[str, Any] = {":sk": "META", _PK_PREFIX_KEY: "MEMORY#"}
        if owner_user_id:
            filter_expr += _UID_FILTER
            expr_vals[":uid"] = owner_user_id
        if workspace_id:
            filter_expr += _WSID_FILTER
            expr_vals[":wsid"] = workspace_id
        scan_kwargs: dict[str, Any] = {
            "FilterExpression": filter_expr,
            "ExpressionAttributeValues": expr_vals,
            "ProjectionExpression": "#sb",
            "ExpressionAttributeNames": {"#sb": "size_bytes"},
        }
        total = 0
        resp = self.table.scan(**scan_kwargs)
        while True:
            total += sum(int(item.get("size_bytes", 0)) for item in resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if last_key is None:
                break
            resp = self.table.scan(**scan_kwargs, ExclusiveStartKey=last_key)
        return total

    def update_user_limits(
        self,
        user_id: str,
        memory_limit: int | None,
        storage_bytes_limit: int | None,
    ) -> bool:
        """Set per-user quota overrides. Pass None to remove an override (revert to system default)."""
        set_parts: list[str] = []
        remove_parts: list[str] = []
        expr_vals: dict[str, Any] = {}

        if memory_limit is not None:
            set_parts.append("memory_limit = :ml")
            expr_vals[":ml"] = memory_limit
        else:
            remove_parts.append("memory_limit")

        if storage_bytes_limit is not None:
            set_parts.append("storage_bytes_limit = :sbl")
            expr_vals[":sbl"] = storage_bytes_limit
        else:
            remove_parts.append("storage_bytes_limit")

        parts: list[str] = []
        if set_parts:
            parts.append("SET " + ", ".join(set_parts))
        if remove_parts:
            parts.append("REMOVE " + ", ".join(remove_parts))

        update_kwargs: dict[str, Any] = {
            "Key": {"PK": f"USER#{user_id}", "SK": "META"},
            "UpdateExpression": " ".join(parts),
            "ConditionExpression": "attribute_exists(PK)",
        }
        if expr_vals:
            update_kwargs["ExpressionAttributeValues"] = expr_vals

        try:
            self.table.update_item(**update_kwargs)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    # ------------------------------------------------------------------
    # API Keys
    # ------------------------------------------------------------------

    def put_api_key(self, key: ApiKey) -> None:
        self.table.put_item(Item=key.to_dynamo())

    def get_api_key_by_id(self, key_id: str) -> ApiKey | None:
        resp = self.table.get_item(Key={"PK": f"APIKEY#{key_id}", "SK": "META"})
        item = resp.get("Item")
        return ApiKey.from_dynamo(item) if item else None

    def get_api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        """Look up an API key by its SHA-256 hash via the ApiKeyHashIndex GSI (#589).

        The index is sparse — keyed directly on the top-level ``key_hash``
        attribute, which only APIKEY# items carry — so a single-partition
        query replaces the previous full table scan on every API-key-
        authenticated request.

        If the query fails because the index is unavailable (still
        backfilling after deployment, or absent on a table that predates
        it), the lookup degrades gracefully to the legacy scan. The
        fallback is kept permanently as resilience, not as a transitional
        shim — auth must not hard-fail on index availability.
        """
        # Limit=1 with a server-side shape filter, paginating on
        # LastEvaluatedKey. DynamoDB applies Limit *before* the
        # FilterExpression, so a single non-paginated call could
        # false-negative if a foreign item ever carried the same key_hash
        # (sparse-index invariant breach); paginating restores the exact
        # legacy scan semantics. In the normal case — the partition holds
        # exactly one API key item — this is a single 1-item read.
        query_kwargs: dict[str, Any] = {
            "IndexName": "ApiKeyHashIndex",
            "KeyConditionExpression": Key("key_hash").eq(key_hash),
            "FilterExpression": Attr("SK").eq("META") & Attr("PK").begins_with(_APIKEY_PK_PREFIX),
            "Limit": 1,
        }
        try:
            while True:
                resp = self.table.query(**query_kwargs)
                items = resp.get("Items", [])
                if items:
                    return ApiKey.from_dynamo(items[0])
                last_key = resp.get("LastEvaluatedKey")
                if not last_key:
                    return None
                query_kwargs["ExclusiveStartKey"] = last_key
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code not in ("ValidationException", "ResourceNotFoundException"):
                raise
            # The full error message is logged so an unexpected fallback
            # cause (e.g. a genuine query bug rather than a backfilling
            # index) is immediately diagnosable. The code is deliberately
            # not narrowed by message substring — DynamoDB, DynamoDB Local
            # and moto phrase these messages differently, and the fallback
            # direction is fail-safe (a scan, the pre-GSI behaviour).
            logger.warning(
                "ApiKeyHashIndex unavailable (%s: %s) — falling back to table scan "
                "for API key lookup",
                code,
                exc.response["Error"].get("Message", ""),
            )
            return self._scan_api_key_by_hash(key_hash)

    def _scan_api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        """Legacy full-table-scan API key lookup — fallback for ApiKeyHashIndex.

        Paginates on ``LastEvaluatedKey``: a filtered Scan can return an
        empty page while matching items remain in later pages, and this is
        the resilience path for API key auth — it must not false-negative.
        """
        scan_kwargs: dict[str, Any] = {
            "FilterExpression": "begins_with(PK, :prefix) AND SK = :sk AND key_hash = :hash",
            "ExpressionAttributeValues": {
                _PK_PREFIX_KEY: _APIKEY_PK_PREFIX,
                ":sk": "META",
                ":hash": key_hash,
            },
        }
        while True:
            resp = self.table.scan(**scan_kwargs)
            items = resp.get("Items", [])
            if items:
                return ApiKey.from_dynamo(items[0])
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                return None
            scan_kwargs["ExclusiveStartKey"] = last_key

    def list_api_keys_for_user(self, owner_user_id: str) -> list[ApiKey]:
        scan_kwargs: dict[str, Any] = {
            "FilterExpression": "begins_with(PK, :prefix) AND SK = :sk AND owner_user_id = :uid",
            "ExpressionAttributeValues": {
                _PK_PREFIX_KEY: _APIKEY_PK_PREFIX,
                ":sk": "META",
                ":uid": owner_user_id,
            },
        }
        keys: list[ApiKey] = []
        while True:
            resp = self.table.scan(**scan_kwargs)
            keys.extend(ApiKey.from_dynamo(item) for item in resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                return keys
            scan_kwargs["ExclusiveStartKey"] = last_key

    def delete_api_key(self, key_id: str) -> bool:
        resp = self.table.get_item(Key={"PK": f"APIKEY#{key_id}", "SK": "META"})
        if not resp.get("Item"):
            return False
        self.table.delete_item(Key={"PK": f"APIKEY#{key_id}", "SK": "META"})
        return True

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def increment_rate_limit_counter(
        self, client_id: str, window_key: str, ttl_seconds: int
    ) -> int:
        """Atomically increment a rate limit counter and return the new value.

        The counter item is created on first access. TTL is set only on the
        first write (``if_not_exists``) so DynamoDB TTL can clean up expired
        counters automatically.

        Args:
            client_id:   The OAuth client being rate-limited.
            window_key:  Window identifier, e.g. ``min#2026-04-12T10:30``.
            ttl_seconds: Seconds from now after which the item should expire.
        """
        import time

        pk = f"RATELIMIT#{client_id}#{window_key}"
        ttl_epoch = int(time.time()) + ttl_seconds
        resp = self.table.update_item(
            Key={"PK": pk, "SK": "META"},
            UpdateExpression="SET #ttl = if_not_exists(#ttl, :ttl) ADD #c :one",
            ExpressionAttributeNames={"#c": "count", "#ttl": "ttl"},
            ExpressionAttributeValues={":one": Decimal("1"), ":ttl": ttl_epoch},
            ReturnValues="UPDATED_NEW",
        )
        return int(resp["Attributes"]["count"])

    # ------------------------------------------------------------------
    # Audit log (separate from user activity log)
    # ------------------------------------------------------------------

    def log_audit_event(self, event: ActivityEvent) -> None:
        """Write an audit event to the immutable audit log (AUDIT# PK prefix).

        Audit events use a separate PK prefix from activity log events (LOG#)
        so they survive a user-requested activity-log purge. A DynamoDB TTL
        provides a hard retention horizon (``HIVE_AUDIT_RETENTION_DAYS``,
        default 365) so items age out automatically and we stay compliant
        with data-minimisation expectations.
        """
        item = event.to_dynamo()
        date_hour_str = event.timestamp.strftime("%Y-%m-%d#%H")
        item["PK"] = f"AUDIT#{date_hour_str}"
        retention_days = int(os.environ.get("HIVE_AUDIT_RETENTION_DAYS", "365"))
        item["ttl"] = int(event.timestamp.timestamp()) + retention_days * 86400
        self.table.put_item(Item=item)

    def get_audit_events_for_dates(
        self,
        dates: list[str],
        *,
        client_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[ActivityEvent]:
        """Fetch audit events across multiple dates, newest-first, capped at limit.

        Optional post-query filters on ``client_id`` and ``event_type`` keep
        the admin audit-log endpoint simple; the partition scan itself reads
        every hour-shard in parallel.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _query(pk: str) -> list[ActivityEvent]:
            resp = self.table.query(KeyConditionExpression=Key("PK").eq(pk))
            return [ActivityEvent.from_dynamo(i) for i in resp.get("Items", [])]

        pks = [f"AUDIT#{d}#{hour:02d}" for d in dates for hour in range(24)]
        events: list[ActivityEvent] = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(_query, pk): pk for pk in pks}
            for future in as_completed(futures):
                events.extend(future.result())

        if client_id is not None:
            events = [e for e in events if e.client_id == client_id]
        if event_type is not None:
            events = [e for e in events if e.event_type.value == event_type]

        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    # ------------------------------------------------------------------
    # Cost Explorer response cache (#578)
    # ------------------------------------------------------------------

    def get_cost_cache(self, query_hash: str) -> dict[str, Any] | None:
        """Return a cached Cost Explorer payload for ``query_hash``, or None.

        Best-effort by design: an absent, expired, corrupt, or unreadable
        cache entry returns None so the caller falls through to a live
        Cost Explorer call — a cache problem must never surface as a 500.

        Expiry is enforced on read because DynamoDB's TTL sweep is lazy
        (deletion can lag the ``ttl`` timestamp by up to ~48 h); the item
        uses the table's configured TTL attribute (``ttl``) so it is still
        physically removed eventually.
        """
        try:
            resp = self.table.get_item(Key={"PK": f"COST_CACHE#{query_hash}", "SK": "META"})
        except Exception:
            # Infrastructure failure — keep the stack trace, it's actionable.
            logger.warning("cost_cache_read_failed query_hash=%s", query_hash, exc_info=True)
            return None
        item = resp.get("Item")
        if not item:
            return None
        try:
            if int(item["ttl"]) <= int(_now().timestamp()):
                return None
            payload = json.loads(item["response"])
            if not isinstance(payload, dict):
                raise ValueError("cached cost payload is not a JSON object")
            return payload
        except Exception as exc:
            # Content-shape problem (missing ttl/response, bad JSON, wrong
            # type) — an expected miss, not an incident: log without a
            # traceback to keep dashboard-load noise and log cost down. The
            # entry self-heals when the fall-through CE call writes back.
            logger.warning("cost_cache_entry_invalid query_hash=%s error=%s", query_hash, exc)
            return None

    def put_cost_cache(
        self,
        query_hash: str,
        query_params: dict[str, Any],
        response: dict[str, Any],
        ttl_seconds: int,
    ) -> None:
        """Write a Cost Explorer payload to the cache (best-effort).

        The payload is stored as a JSON string (floats are not valid
        DynamoDB numbers) with ``ttl`` set to now + ``ttl_seconds`` so the
        table's TTL config auto-expires stale entries. ``query_params`` is
        stored alongside for debugging only. Write failures are logged and
        swallowed — the caller already holds the live CE response.
        """
        now = _now()
        try:
            self.table.put_item(
                Item={
                    "PK": f"COST_CACHE#{query_hash}",
                    "SK": "META",
                    "query_params": json.dumps(query_params, sort_keys=True),
                    "response": json.dumps(response),
                    "cached_at": now.isoformat(),
                    "ttl": int(now.timestamp()) + ttl_seconds,
                }
            )
        except Exception:
            logger.warning("cost_cache_write_failed query_hash=%s", query_hash, exc_info=True)

    # ------------------------------------------------------------------
    # Account deletion
    # ------------------------------------------------------------------

    def delete_user_data(self, user_id: str) -> dict[str, int]:
        """Delete all data owned by a user.

        Deletes all memories, OAuth clients, every outstanding token
        issued to those clients, and the user record. Tokens are
        hard-deleted rather than left to expire via their TTLs — a
        still-live access token must not outlive its owner's account
        (#588). Returns counts of deleted items.
        """
        deleted_memories = 0
        cursor: str | None = None
        while True:
            memories, cursor = self.list_all_memories(
                owner_user_id=user_id, limit=200, cursor=cursor
            )
            for memory in memories:
                self.delete_memory(memory.memory_id)
                deleted_memories += 1
            if cursor is None:
                break

        client_ids: list[str] = []
        cursor = None
        while True:
            clients, cursor = self.list_clients(owner_user_id=user_id, limit=200, cursor=cursor)
            client_ids.extend(client.client_id for client in clients)
            if cursor is None:
                break

        # First sweep: revoke everything outstanding while the client
        # records still exist — if anything below fails, a retry can
        # rediscover the clients via list_clients and finish the job.
        deleted_tokens = self.delete_tokens_for_clients(set(client_ids))

        # Close the mint path: /oauth/token authenticates the client via
        # get_client, so removing the client records stops a concurrent
        # refresh grant from issuing new tokens.
        deleted_clients = 0
        for client_id in client_ids:
            self.delete_client(client_id)
            deleted_clients += 1

        # Second sweep: catch tokens minted by grants in flight during
        # the first scan. With the clients gone nothing new can be
        # minted, so this sweep is final.
        deleted_tokens += self.delete_tokens_for_clients(set(client_ids))

        self.delete_user(user_id)

        return {
            "deleted_memories": deleted_memories,
            "deleted_clients": deleted_clients,
            "deleted_tokens": deleted_tokens,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _delete_blob_if_needed(self, memory: Memory) -> None:
        """Delete the S3 blob for a memory if one exists.

        Called after the DynamoDB item is already removed. Failures are
        logged as warnings and swallowed — the memory is already gone from
        DynamoDB so it's inaccessible regardless. The configured S3
        lifecycle rule only aborts incomplete multipart uploads; it does
        not clean up orphaned objects left behind by failed deletes.
        """
        if memory.s3_uri is None:
            return
        owner = memory.owner_user_id or memory.owner_client_id or ""
        try:
            self.blob_store.delete(owner=owner, memory_id=memory.memory_id)
        except Exception:
            logger.warning(
                "blob_delete_failed memory_id=%s s3_uri=%s",
                memory.memory_id,
                memory.s3_uri,
                exc_info=True,
            )

    def fetch_blob_value(self, memory: Memory) -> str:
        """Fetch the full text content from S3 for a ``text-large`` memory.

        Raises whatever the underlying blob store raises so the caller can
        decide whether to propagate or surface a user-facing fallback.
        """
        owner = memory.owner_user_id or memory.owner_client_id or ""
        data = self.blob_store.get(owner=owner, memory_id=memory.memory_id)
        return data.decode("utf-8")

    def fetch_blob_bytes(self, memory: Memory) -> bytes:
        """Fetch raw binary content from S3 for an ``image`` or ``blob`` memory.

        Raises whatever the underlying blob store raises so the caller can
        decide whether to propagate or surface a user-facing fallback.
        """
        owner = memory.owner_user_id or memory.owner_client_id or ""
        return self.blob_store.get(owner=owner, memory_id=memory.memory_id)

    def _get_memory_meta(self, memory_id: str) -> dict[str, Any] | None:
        resp = self.table.get_item(Key={"PK": f"MEMORY#{memory_id}", "SK": "META"})
        item: dict[str, Any] | None = resp.get("Item")  # type: ignore[assignment]
        return item

    def _delete_tag_items(self, memory: Memory) -> None:
        with self.table.batch_writer() as batch:
            for tag in memory.tags:
                batch.delete_item(Key={"PK": f"MEMORY#{memory.memory_id}", "SK": f"TAG#{tag}"})
                if memory.owner_user_id:
                    batch.delete_item(
                        Key={
                            "PK": f"USERTAG#{memory.owner_user_id}",
                            "SK": f"TAG#{tag}#MEMORY#{memory.memory_id}",
                        }
                    )
