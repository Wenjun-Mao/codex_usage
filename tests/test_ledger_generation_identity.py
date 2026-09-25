from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

import codex_usage.ledger_sync as ledger_sync
from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_rebuild import rebuild_stale_source_slice
from codex_usage.ledger_queries import load_ledger_records
from codex_usage.ledger_schema import open_ledger
from codex_usage.session_cache import refresh_cached_session_data
from codex_usage.session_row_relevance import CHECKPOINT_DIGEST_BYTES


def _token_row(total: int) -> dict[str, object]:
    return {
        "timestamp": "2026-09-02T10:00:02Z",
        "type": "event_msg",
        "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": total, "total_tokens": total}}},
    }


def _write_session(path: Path, total: int, *, long_tail: bool = False) -> None:
    rows = [
        {"timestamp": "2026-09-02T10:00:00Z", "type": "session_meta",
         "payload": {"id": "task-1", "cwd": "/fixture/project"}},
        {"timestamp": "2026-09-02T10:00:01Z", "type": "turn_context",
         "payload": {"model": "gpt-5.6-sol"}},
        _token_row(total),
    ]
    if long_tail:
        rows.append({"type": "response_item", "payload": {
            "type": "message", "text": "x" * (CHECKPOINT_DIGEST_BYTES * 3)}})
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def _captured_ledger(tmp_path: Path, *, long_tail: bool = False) -> tuple[Path, Path, Path]:
    home = tmp_path / ".codex"
    directory = home / "sessions" / "2026" / "09" / "02"
    directory.mkdir(parents=True)
    path = directory / "rollout-task-1.jsonl"
    _write_session(path, 100, long_tail=long_tail)
    assert capture_once(home, request_kind="startup", max_workers=1).outcome == "success"
    return home, path, ledger_database_path(home)


def _generations(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """select generation_id, generation_number, generation_key, status,
                  (select count(*) from ledger_usage_events as events
                   where events.generation_id = generations.generation_id) as events
           from ledger_generations as generations order by generation_number"""
    ).fetchall()


def _finish_stale_rebuild(home: Path) -> None:
    rebuilt = rebuild_stale_source_slice(home, "task-1", max_bytes=64 * 1024)
    while not rebuilt.complete:
        rebuilt = rebuild_stale_source_slice(home, "task-1", max_bytes=64 * 1024)


def test_device_change_and_reversion_use_guards_and_keep_one_generation(
    tmp_path: Path,
) -> None:
    home, path, ledger = _captured_ledger(tmp_path)
    with open_ledger(ledger) as connection:
        original_device = connection.execute(
            "select source_device from parser_checkpoints"
        ).fetchone()[0]
        connection.execute("update parser_checkpoints set source_device = '987654321'")
        connection.commit()
    ledger_sync.synchronize_parser_workset(ledger)
    with open_ledger(ledger, read_only=True) as connection:
        assert len(_generations(connection)) == 1
        assert connection.execute(
            "select source_device from ledger_sources"
        ).fetchone()[0] == "987654321"

    with path.open("a") as handle:
        handle.write(json.dumps(_token_row(150)) + "\n")
    resumed = capture_once(home, request_kind="scheduled", max_workers=1)
    repeated = capture_once(home, request_kind="scheduled", max_workers=1)
    assert resumed.outcome == repeated.outcome == "success"
    assert resumed.stats.files_appended == 1
    assert repeated.stats.source_bytes_read == 0
    assert [record.usage.total_tokens for record in load_ledger_records(ledger)] == [
        100, 50
    ]
    with open_ledger(ledger, read_only=True) as connection:
        rows = _generations(connection)
        assert len(rows) == 1
        assert rows[0]["status"] == "trusted"
        assert rows[0]["events"] == 2
        assert connection.execute(
            "select source_device from ledger_sources"
        ).fetchone()[0] == original_device
        assert [row[0] for row in connection.execute(
            "select source_record_index from ledger_usage_events order by source_record_index"
        )] == [0, 1]


def test_device_change_without_growth_verifies_guards(tmp_path: Path) -> None:
    home, _, ledger = _captured_ledger(tmp_path, long_tail=True)
    with open_ledger(ledger) as connection:
        connection.execute("update parser_checkpoints set source_device = '987654321'")
        connection.commit()
    result = capture_once(home, request_kind="scheduled", max_workers=1)
    assert result.outcome == "success"
    assert result.stats.files_appended == 1
    assert result.stats.files_full_parsed == 0
    assert result.stats.source_bytes_read <= 4 * CHECKPOINT_DIGEST_BYTES
    with open_ledger(ledger, read_only=True) as connection:
        assert len(_generations(connection)) == 1


def test_same_inode_and_prefix_but_changed_boundary_replaces_history(
    tmp_path: Path,
) -> None:
    home, path, ledger = _captured_ledger(tmp_path, long_tail=True)
    original_stat = path.stat()
    with path.open("r+b") as handle:
        handle.seek(original_stat.st_size - 20)
        handle.write(b"y")
    with path.open("a") as handle:
        handle.write(json.dumps(_token_row(150)) + "\n")
    assert path.stat().st_ino == original_stat.st_ino
    stale = capture_once(home, request_kind="scheduled", max_workers=1)
    assert stale.outcome == "success"
    assert stale.status.coverage.stale_sources == 1
    with open_ledger(ledger, read_only=True) as connection:
        assert [row["events"] for row in _generations(connection)] == [1]
    _finish_stale_rebuild(home)
    assert [record.usage.total_tokens for record in load_ledger_records(ledger)] == [
        100, 50
    ]
    with open_ledger(ledger, read_only=True) as connection:
        rows = _generations(connection)
        assert [row["status"] for row in rows] == ["superseded", "trusted"]
        assert [row["events"] for row in rows] == [1, 2]
        assert rows[1]["generation_key"] == "occurrence:2"


def test_genuine_file_replacement_creates_new_history(tmp_path: Path) -> None:
    home, path, ledger = _captured_ledger(tmp_path)
    old_inode = path.stat().st_ino
    replacement = tmp_path / "replacement.jsonl"
    _write_session(replacement, 200)
    os.replace(replacement, path)
    assert path.stat().st_ino != old_inode
    stale = capture_once(home, request_kind="scheduled", max_workers=1)
    assert stale.outcome == "success"
    assert stale.status.coverage.stale_sources == 1
    _finish_stale_rebuild(home)
    assert [record.usage.total_tokens for record in load_ledger_records(ledger)] == [
        200
    ]
    with open_ledger(ledger, read_only=True) as connection:
        rows = _generations(connection)
        assert [row["status"] for row in rows] == ["superseded", "trusted"]
        assert [row["events"] for row in rows] == [1, 1]
        assert rows[1]["generation_key"] == "occurrence:2"


def test_generation_insert_failure_rolls_back_source_and_trust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, path, ledger = _captured_ledger(tmp_path)
    replacement = tmp_path / "replacement.jsonl"
    _write_session(replacement, 200)
    os.replace(replacement, path)
    outcome = refresh_cached_session_data(
        [home / "sessions"], cache_database_path=ledger,
        max_workers=1, defer_full_fallback=False,
    )
    assert outcome.stats.files_full_parsed == 1
    with open_ledger(ledger, read_only=True) as connection:
        original_inode = connection.execute(
            "select source_inode from ledger_sources"
        ).fetchone()[0]
        original_revision = connection.execute(
            "select value from ledger_meta where key = 'ledger_revision'"
        ).fetchone()[0]

    def fail_insertion(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected event insertion failure")

    with monkeypatch.context() as patch:
        patch.setattr(ledger_sync, "insert_generation_events", fail_insertion)
        with pytest.raises(RuntimeError, match="injected event insertion failure"):
            ledger_sync.synchronize_parser_workset(ledger)

    with open_ledger(ledger, read_only=True) as connection:
        assert connection.execute(
            "select source_inode from ledger_sources"
        ).fetchone()[0] == original_inode
        assert connection.execute(
            "select value from ledger_meta where key = 'ledger_revision'"
        ).fetchone()[0] == original_revision
        rows = _generations(connection)
        assert len(rows) == 1
        assert rows[0]["status"] == "trusted"
        assert rows[0]["events"] == 1

    ledger_sync.synchronize_parser_workset(ledger)
    with open_ledger(ledger, read_only=True) as connection:
        assert [row["events"] for row in _generations(connection)] == [1, 1]
