# Copyright (c) 2026 John Carter. All rights reserved.
"""
One-shot migration: re-index memory vectors per user account (#666).

Before this migration the S3 Vectors index is partitioned per OAuth client
(``client-{client_id}``). After #666 the vector store reads and writes per user
account (``user-{owner_user_id}``) so semantic search spans every DCR client of
the account, consistent with the tag/list read path.

Existing vectors live in the old ``client-*`` indexes and are invisible to the
new account-scoped search. This script rebuilds the ``user-*`` indexes from
DynamoDB — the authoritative store — by re-embedding each memory's text. Vectors
are derived data, so no information is lost (only Bedrock embedding cost).

It is **idempotent**: re-running re-embeds and overwrites the same vector keys.
Memories that can't or shouldn't be indexed are skipped:

- ``owner_user_id`` is None (legacy/pre-#648 rows) — no account index to target.
- ``value_type`` is ``image`` / ``blob`` — binary memories are never embedded.
- the memory is redacted — its vector is intentionally removed from search.

The old ``client-*`` indexes are left in place (orphaned, no longer queried);
delete them separately once you've confirmed the new indexes serve search.

Usage:

Direct CLI (preferred for production — set ``HIVE_TABLE_NAME``,
``HIVE_VECTORS_BUCKET`` and the appropriate ``AWS_*`` environment variables):

    uv run python scripts/migrate_vectors_to_user_index.py
    uv run python scripts/migrate_vectors_to_user_index.py --dry-run   # report only

Via invoke task (targets AWS by default — set ``DYNAMODB_ENDPOINT`` for local):

    uv run inv migrate-vectors
    uv run inv migrate-vectors --dry-run
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from hive.logging_config import get_logger
from hive.models import Memory
from hive.storage import HiveStorage
from hive.vector_store import VectorStore

logger = get_logger("hive.migrate_vectors")

# value_types that are stored as binary blobs and never embedded.
_NON_EMBEDDABLE_TYPES = {"image", "blob"}


@dataclass
class MigrationStats:
    """Per-phase counters so operators can sanity-check the run."""

    memories_seen: int = 0
    reindexed: int = 0
    skipped_no_owner: int = 0
    skipped_non_embeddable: int = 0
    skipped_redacted: int = 0

    def report(self) -> str:
        return (
            f"memories_seen={self.memories_seen} "
            f"reindexed={self.reindexed} "
            f"skipped_no_owner={self.skipped_no_owner} "
            f"skipped_non_embeddable={self.skipped_non_embeddable} "
            f"skipped_redacted={self.skipped_redacted}"
        )


def _resolve_text(storage: HiveStorage, memory: Memory) -> Memory:
    """Return a copy of ``memory`` whose ``value`` holds the full text to embed.

    Large text memories keep their body in S3 with a sentinel ``value``; fetch
    the real text so the embedding matches what ``remember`` would index.
    """
    if memory.value_type == "text-large":
        return memory.model_copy(update={"value": storage.fetch_blob_value(memory)})
    return memory


def reindex_memories(
    storage: HiveStorage,
    vector_store: VectorStore,
    stats: MigrationStats,
    *,
    dry_run: bool,
) -> None:
    """Re-embed every eligible memory into its account (``user-*``) index."""
    for memory in storage.iter_all_memories():
        stats.memories_seen += 1
        if memory.owner_user_id is None:
            stats.skipped_no_owner += 1
            continue
        if memory.value_type in _NON_EMBEDDABLE_TYPES:
            stats.skipped_non_embeddable += 1
            continue
        if memory.is_redacted:
            stats.skipped_redacted += 1
            continue
        if dry_run:
            stats.reindexed += 1
            continue
        vector_store.upsert_memory(_resolve_text(storage, memory))
        stats.reindexed += 1


def run(
    *,
    dry_run: bool = False,
    storage: HiveStorage | None = None,
    vector_store: VectorStore | None = None,
) -> MigrationStats:
    """Execute the migration. ``storage``/``vector_store`` are injectable for tests."""
    store = storage if storage is not None else HiveStorage()
    vstore = vector_store if vector_store is not None else VectorStore()
    stats = MigrationStats()
    logger.info("Starting vector re-index migration", extra={"dry_run": dry_run})
    reindex_memories(store, vstore, stats, dry_run=dry_run)
    logger.info("Vector re-index migration finished: %s", stats.report())
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-index Hive memory vectors per user account (#666)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be re-indexed without calling Bedrock or S3 Vectors.",
    )
    args = parser.parse_args(argv)
    stats = run(dry_run=args.dry_run)
    print(stats.report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
