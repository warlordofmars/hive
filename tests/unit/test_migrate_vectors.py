# Copyright (c) 2026 John Carter. All rights reserved.
"""Unit tests for scripts/migrate_vectors_to_user_index.py — the #666 re-index."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

os.environ.setdefault("HIVE_TABLE_NAME", "hive-test-migrate-vectors")
os.environ.setdefault("HIVE_VECTORS_BUCKET", "test-vectors-bucket")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

from hive.models import Memory
from scripts.migrate_vectors_to_user_index import MigrationStats, main, run


def _mem(**kwargs) -> Memory:
    defaults = {
        "key": "k",
        "value": "v",
        "owner_client_id": "client-1",
        "owner_user_id": "user-1",
    }
    defaults.update(kwargs)
    return Memory(**defaults)


def _run(memories, *, dry_run=False, blob_value="large body"):
    """Run the migration against mock storage/vector_store; return (stats, vs)."""
    storage = MagicMock()
    storage.iter_all_memories.return_value = iter(memories)
    storage.fetch_blob_value.return_value = blob_value
    vs = MagicMock()
    stats = run(dry_run=dry_run, storage=storage, vector_store=vs)
    return stats, vs, storage


def test_reindexes_embeddable_memories():
    mems = [_mem(key="a", owner_user_id="user-1"), _mem(key="b", owner_user_id="user-2")]
    stats, vs, _ = _run(mems)
    assert stats.memories_seen == 2
    assert stats.reindexed == 2
    assert vs.upsert_memory.call_count == 2
    upserted_keys = {c.args[0].key for c in vs.upsert_memory.call_args_list}
    assert upserted_keys == {"a", "b"}


def test_skips_memory_without_owner_user_id():
    stats, vs, _ = _run([_mem(owner_user_id=None)])
    assert stats.skipped_no_owner == 1
    assert stats.reindexed == 0
    vs.upsert_memory.assert_not_called()


def test_skips_non_embeddable_blob_and_image():
    mems = [_mem(value_type="image"), _mem(value_type="blob")]
    stats, vs, _ = _run(mems)
    assert stats.skipped_non_embeddable == 2
    assert stats.reindexed == 0
    vs.upsert_memory.assert_not_called()


def test_skips_redacted_memory():
    stats, vs, _ = _run([_mem(redacted_at=datetime.now(timezone.utc))])
    assert stats.skipped_redacted == 1
    assert stats.reindexed == 0
    vs.upsert_memory.assert_not_called()


def test_text_large_embeds_fetched_value():
    stats, vs, storage = _run(
        [_mem(value_type="text-large", value="")], blob_value="the full large text"
    )
    assert stats.reindexed == 1
    storage.fetch_blob_value.assert_called_once()
    upserted = vs.upsert_memory.call_args.args[0]
    assert upserted.value == "the full large text"


def test_dry_run_counts_but_does_not_write():
    stats, vs, storage = _run([_mem(), _mem(key="b")], dry_run=True)
    assert stats.reindexed == 2
    vs.upsert_memory.assert_not_called()
    storage.fetch_blob_value.assert_not_called()


def test_report_includes_all_counters():
    stats = MigrationStats(
        memories_seen=5,
        reindexed=3,
        skipped_no_owner=1,
        skipped_non_embeddable=1,
        skipped_redacted=0,
    )
    report = stats.report()
    for field in (
        "memories_seen=5",
        "reindexed=3",
        "skipped_no_owner=1",
        "skipped_non_embeddable=1",
        "skipped_redacted=0",
    ):
        assert field in report


def test_main_returns_zero_and_prints(capsys):
    with patch(
        "scripts.migrate_vectors_to_user_index.run",
        return_value=MigrationStats(memories_seen=2, reindexed=2),
    ) as mock_run:
        rc = main(["--dry-run"])
    assert rc == 0
    mock_run.assert_called_once_with(dry_run=True)
    assert "reindexed=2" in capsys.readouterr().out
