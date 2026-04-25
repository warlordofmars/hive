# Copyright (c) 2026 John Carter. All rights reserved.
"""
One-shot migration to the workspaces tenancy model (#482, #490).

Before this migration the tenancy root is the user: every memory and OAuth
client carries an ``owner_user_id`` and no workspace concept exists. After
the migration:

1. Every user has a ``{email}'s Personal`` workspace where they are the sole
   owner.
2. Every memory's ``workspace_id`` points to the Personal workspace of its
   ``owner_user_id``.
3. Every OAuth client's ``workspace_id`` points to the Personal workspace of
   its ``owner_user_id``.
4. Every outstanding access/refresh token is revoked so callers re-auth with
   a fresh token that carries the ``workspace_id`` claim (wired by #491).

The migration is **idempotent** — re-running it on a partially-migrated
table is safe:

- Users that already own a Personal workspace are skipped.
- Memories / clients that already have a ``workspace_id`` are left alone.
- Token revocation is a no-op on already-revoked tokens.

Usage:

    uv run inv migrate-workspaces              # execute against HIVE_TABLE_NAME
    uv run inv migrate-workspaces --dry-run    # report only, no writes

Direct CLI:

    uv run python scripts/migrate_workspaces.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError

from hive.logging_config import get_logger
from hive.models import Workspace, WorkspaceRole
from hive.storage import HiveStorage

logger = get_logger("hive.migrate_workspaces")


@dataclass
class MigrationStats:
    """Per-phase counters so operators can sanity-check the run."""

    users_seen: int = 0
    workspaces_created: int = 0
    workspaces_skipped: int = 0
    memories_seen: int = 0
    memories_migrated: int = 0
    memories_skipped: int = 0
    clients_seen: int = 0
    clients_migrated: int = 0
    clients_skipped: int = 0
    tokens_revoked: int = 0

    def report(self) -> str:
        return (
            f"users_seen={self.users_seen} "
            f"workspaces_created={self.workspaces_created} "
            f"workspaces_skipped={self.workspaces_skipped} "
            f"memories_seen={self.memories_seen} "
            f"memories_migrated={self.memories_migrated} "
            f"memories_skipped={self.memories_skipped} "
            f"clients_seen={self.clients_seen} "
            f"clients_migrated={self.clients_migrated} "
            f"clients_skipped={self.clients_skipped} "
            f"tokens_revoked={self.tokens_revoked}"
        )


def _personal_workspace_name(email: str) -> str:
    """Display name used for every auto-created Personal workspace."""
    return f"{email}'s Personal"


def _find_personal_workspace(
    storage: HiveStorage, user_id: str, *, dry_run: bool = False
) -> Workspace | None:
    """Return the user's Personal workspace, or None if they have none yet.

    Checks via WorkspaceMemberIndex first (fast path). Falls back to a
    full-table scan of WORKSPACE META items owned by this user to recover
    from a prior partial run where the META row was written but the MEMBER
    row was not — which would cause ``list_workspaces_for_user`` (GSI-backed)
    to return nothing, making a naïve re-run create a duplicate workspace.
    When the slow-path scan finds an orphaned META and ``dry_run`` is False,
    the MEMBER row is repaired in place so subsequent lookups work correctly.
    In dry-run mode the repair is skipped so no writes occur.
    """
    for ws in storage.list_workspaces_for_user(user_id):
        if ws.is_personal and ws.owner_user_id == user_id:
            return ws
    # Slow-path: scan for orphaned WORKSPACE META (partial prior run).
    scan_kwargs: dict[str, Any] = {
        "FilterExpression": (
            "SK = :sk AND begins_with(PK, :prefix) AND owner_user_id = :uid"
        ),
        "ExpressionAttributeValues": {
            ":sk": "META",
            ":prefix": "WORKSPACE#",
            ":uid": user_id,
        },
    }
    while True:
        resp = storage.table.scan(**scan_kwargs)
        for item in resp.get("Items", []):
            ws = Workspace.from_dynamo(item)
            if ws.is_personal:
                if not dry_run:
                    # Repair the missing MEMBER row so GSI lookups work going forward.
                    storage.add_workspace_member(
                        workspace_id=ws.workspace_id,
                        user_id=user_id,
                        role=WorkspaceRole.owner,
                    )
                return ws
        lek = resp.get("LastEvaluatedKey")
        if lek is None:
            break
        scan_kwargs["ExclusiveStartKey"] = lek
    return None


def _iter_all_users(storage: HiveStorage) -> Iterator[Any]:
    """Yield every User, paginating through ``list_users``."""
    cursor: str | None = None
    while True:
        users, cursor = storage.list_users(limit=100, cursor=cursor)
        yield from users
        if cursor is None:
            return


def migrate_users(
    storage: HiveStorage,
    stats: MigrationStats,
    *,
    dry_run: bool,
) -> dict[str, str]:
    """Ensure every user has a Personal workspace.

    Returns a mapping of ``user_id → workspace_id`` that the memory/client
    passes use for the rewrite step.
    """
    user_to_workspace: dict[str, str] = {}
    for user in _iter_all_users(storage):
        stats.users_seen += 1
        existing = _find_personal_workspace(storage, user.user_id, dry_run=dry_run)
        if existing is not None:
            stats.workspaces_skipped += 1
            user_to_workspace[user.user_id] = existing.workspace_id
            continue
        ws = Workspace(
            name=_personal_workspace_name(user.email),
            owner_user_id=user.user_id,
            is_personal=True,
        )
        if not dry_run:
            storage.put_workspace(ws)
            storage.add_workspace_member(
                workspace_id=ws.workspace_id,
                user_id=user.user_id,
                role=WorkspaceRole.owner,
            )
        stats.workspaces_created += 1
        user_to_workspace[user.user_id] = ws.workspace_id
        logger.info(
            "Created personal workspace",
            extra={"user_id": user.user_id, "workspace_id": ws.workspace_id},
        )
    return user_to_workspace


def migrate_memories(
    storage: HiveStorage,
    user_to_workspace: dict[str, str],
    stats: MigrationStats,
    *,
    dry_run: bool,
) -> None:
    """Stamp every memory with the workspace_id that matches its owner_user_id.

    Memories missing ``owner_user_id`` (pre-v0.23 legacy rows) are skipped —
    they have no user attribution to map from.
    """
    # iter_all_memories() yields only META items across all users.
    for memory in storage.iter_all_memories():
        stats.memories_seen += 1
        if memory.workspace_id is not None:
            stats.memories_skipped += 1
            continue
        if memory.owner_user_id is None:
            stats.memories_skipped += 1
            continue
        workspace_id = user_to_workspace.get(memory.owner_user_id)
        if workspace_id is None:
            stats.memories_skipped += 1
            logger.warning(
                "Memory references unknown user; skipping",
                extra={
                    "memory_id": memory.memory_id,
                    "owner_user_id": memory.owner_user_id,
                },
            )
            continue
        if dry_run:
            stats.memories_migrated += 1
            continue
        try:
            storage.table.update_item(
                Key={"PK": f"MEMORY#{memory.memory_id}", "SK": "META"},
                UpdateExpression="SET workspace_id = :wsid",
                ExpressionAttributeValues={":wsid": workspace_id},
                ConditionExpression=(
                    "attribute_exists(PK) AND attribute_exists(SK)"
                    " AND attribute_not_exists(workspace_id)"
                ),
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                stats.memories_skipped += 1
                logger.warning(
                    "Memory missing or already stamped during migration; skipping",
                    extra={"memory_id": memory.memory_id},
                )
                continue
            raise
        stats.memories_migrated += 1


def migrate_clients(
    storage: HiveStorage,
    user_to_workspace: dict[str, str],
    stats: MigrationStats,
    *,
    dry_run: bool,
) -> None:
    """Stamp every OAuth client with the workspace_id of its owner_user_id.

    Clients without ``owner_user_id`` are pre-v0.22 legacy shells and stay
    unbound — the auth layer (#491) will refuse to mint tokens for them.
    """
    cursor: str | None = None
    while True:
        clients, cursor = storage.list_clients(limit=100, cursor=cursor)
        for client in clients:
            stats.clients_seen += 1
            if client.workspace_id is not None:
                stats.clients_skipped += 1
                continue
            if client.owner_user_id is None:
                stats.clients_skipped += 1
                continue
            workspace_id = user_to_workspace.get(client.owner_user_id)
            if workspace_id is None:
                stats.clients_skipped += 1
                logger.warning(
                    "Client references unknown user; skipping",
                    extra={
                        "client_id": client.client_id,
                        "owner_user_id": client.owner_user_id,
                    },
                )
                continue
            if dry_run:
                stats.clients_migrated += 1
                continue
            try:
                storage.table.update_item(
                    Key={"PK": f"CLIENT#{client.client_id}", "SK": "META"},
                    UpdateExpression="SET workspace_id = :wsid",
                    ExpressionAttributeValues={":wsid": workspace_id},
                    ConditionExpression=(
                        "attribute_exists(PK) AND attribute_exists(SK)"
                        " AND attribute_not_exists(workspace_id)"
                    ),
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    stats.clients_skipped += 1
                    logger.warning(
                        "Client missing or already stamped during migration; skipping",
                        extra={"client_id": client.client_id},
                    )
                    continue
                raise
            stats.clients_migrated += 1
        if cursor is None:
            break


def run(*, dry_run: bool = False, storage: HiveStorage | None = None) -> MigrationStats:
    """Execute the full migration. ``storage`` is injectable for tests."""
    store = storage if storage is not None else HiveStorage()
    stats = MigrationStats()
    logger.info("Starting workspace migration", extra={"dry_run": dry_run})

    user_to_workspace = migrate_users(store, stats, dry_run=dry_run)
    migrate_memories(store, user_to_workspace, stats, dry_run=dry_run)
    migrate_clients(store, user_to_workspace, stats, dry_run=dry_run)

    if dry_run:
        logger.info("Dry-run complete; skipping token revocation", extra=vars(stats))
    else:
        stats.tokens_revoked = store.revoke_all_tokens()

    logger.info("Workspace migration finished: %s", stats.report())
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate Hive to the workspaces model.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing.",
    )
    args = parser.parse_args(argv)
    stats = run(dry_run=args.dry_run)
    print(stats.report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
