"""Backups pin one revision and never become a live-ledger mutation path."""
import json
import os
import sqlite3

import pytest

from codex_usage.ledger_repair_snapshot import create_repair_snapshot, verify_repair_snapshot
from codex_usage.ledger_schema import open_ledger


def ledger(tmp_path):
    path = tmp_path / "live.sqlite3"
    with open_ledger(path) as connection:
        connection.commit()
    return path


def test_private_snapshot_and_independent_disposable_restore(tmp_path):
    source = ledger(tmp_path)
    original_bytes = source.read_bytes()
    receipt = create_repair_snapshot(source, tmp_path / "private" / "backup.sqlite3")
    facts = verify_repair_snapshot(receipt)
    assert facts["source_open_mode"] == "ro"
    if os.name == "posix":
        assert receipt.parent.stat().st_mode & 0o777 == 0o700
        assert receipt.stat().st_mode & 0o777 == 0o600
        assert (receipt.parent / "backup.sqlite3").stat().st_mode & 0o777 == 0o600
    restored = create_repair_snapshot(receipt.parent / "backup.sqlite3",
        tmp_path / "restore" / "working.sqlite3")
    assert verify_repair_snapshot(restored)["ledger_revision"] == facts["ledger_revision"]
    assert source.read_bytes() == original_bytes
    # SQLite backup can change header bookkeeping without changing logical data.
    with sqlite3.connect(source) as original, sqlite3.connect(restored.parent / "working.sqlite3") as working:
        assert list(original.iterdump()) == list(working.iterdump())


def test_concurrent_wal_commit_does_not_mix_revisions(tmp_path):
    source = ledger(tmp_path)
    wrote = []
    def commit_later(*_):
        if not wrote:
            wrote.append(True)
            with sqlite3.connect(source) as writer:
                from codex_usage.ledger_writer_contract import authorize_cache_connection
                authorize_cache_connection(writer)
                writer.execute("update ledger_meta set value='99' where key='ledger_revision'")
    receipt = create_repair_snapshot(source, tmp_path / "private" / "backup.sqlite3", progress=commit_later)
    assert verify_repair_snapshot(receipt)["ledger_revision"] == 0
    with sqlite3.connect(source) as connection:
        assert connection.execute("select value from ledger_meta where key='ledger_revision'").fetchone() == ("99",)


def test_existing_directory_and_source_destination_are_never_overwritten(tmp_path):
    source = ledger(tmp_path)
    with pytest.raises(ValueError, match="separate"):
        create_repair_snapshot(source, source)
    target = tmp_path / "private"
    target.mkdir()
    sentinel = target / "sentinel"
    sentinel.write_text("keep")
    with pytest.raises(FileExistsError):
        create_repair_snapshot(source, target / "snapshot.sqlite3")
    assert sentinel.read_text() == "keep"


def test_hash_and_facts_mismatch_are_rejected(tmp_path):
    source = ledger(tmp_path)
    receipt = create_repair_snapshot(source, tmp_path / "private" / "backup.sqlite3")
    manifest = json.loads(receipt.read_text())
    manifest["ledger_revision"] = 12
    receipt.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="facts mismatch"):
        verify_repair_snapshot(receipt)
    manifest["ledger_revision"] = 0
    manifest["sha256"] = "0" * 64
    receipt.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="hash/size"):
        verify_repair_snapshot(receipt)
