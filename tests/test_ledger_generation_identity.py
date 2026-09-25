from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import codex_usage.ledger_sync as ledger_sync
from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.ledger_schema import open_ledger


def _captured_ledger(tmp_path: Path) -> Path:
    home = tmp_path / ".codex"
    directory = home / "sessions" / "2026" / "09" / "02"
    directory.mkdir(parents=True)
    path = directory / "rollout-task-1.jsonl"
    rows = (
        {"timestamp": "2026-09-02T10:00:00Z", "type": "session_meta",
         "payload": {"id": "task-1", "cwd": "/fixture/project"}},
        {"timestamp": "2026-09-02T10:00:01Z", "type": "turn_context",
         "payload": {"model": "gpt-5.6-sol"}},
        {"timestamp": "2026-09-02T10:00:02Z", "type": "event_msg",
         "payload": {"type": "token_count", "info": {
             "total_token_usage": {"input_tokens": 100, "total_tokens": 100}}}},
    )
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    assert capture_once(home, request_kind="startup", max_workers=1).outcome == "success"
    return ledger_database_path(home)


def _generations(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """select generation_id, generation_number, generation_key, status,
                  (select count(*) from ledger_usage_events as events
                   where events.generation_id = generations.generation_id) as events
           from ledger_generations as generations order by generation_number"""
    ).fetchall()


def test_device_identity_reversion_keeps_every_generation_and_retries_idempotently(
    tmp_path: Path,
) -> None:
    ledger = _captured_ledger(tmp_path)
    with open_ledger(ledger) as connection:
        original_device = connection.execute(
            "select source_device from parser_checkpoints"
        ).fetchone()[0]
        connection.execute("update parser_checkpoints set source_device = '987654321'")
        connection.commit()
    ledger_sync.synchronize_parser_workset(ledger)

    with open_ledger(ledger) as connection:
        connection.execute(
            "update parser_checkpoints set source_device = ?", (original_device,)
        )
        connection.execute("update ledger_sources set is_stale = 1")
        connection.commit()
    ledger_sync.synchronize_parser_workset(ledger)

    with open_ledger(ledger, read_only=True) as connection:
        rows = _generations(connection)
        assert [row["status"] for row in rows] == [
            "superseded", "superseded", "trusted"
        ]
        assert [row["events"] for row in rows] == [1, 1, 1]
        assert len({row["generation_key"] for row in rows}) == 3
        trusted_id = rows[-1]["generation_id"]
    revision, changed = ledger_sync.synchronize_parser_workset(ledger)
    assert not changed
    with open_ledger(ledger, read_only=True) as connection:
        assert _generations(connection)[-1]["generation_id"] == trusted_id
        assert connection.execute(
            "select value from ledger_meta where key = 'ledger_revision'"
        ).fetchone()[0] == str(revision)


def test_same_identity_new_head_preserves_prior_events(tmp_path: Path) -> None:
    ledger = _captured_ledger(tmp_path)
    with open_ledger(ledger) as connection:
        connection.execute("update parser_checkpoints set head_sha256 = ?", ("a" * 64,))
        connection.commit()
    ledger_sync.synchronize_parser_workset(ledger)
    with open_ledger(ledger, read_only=True) as connection:
        rows = _generations(connection)
        assert [row["status"] for row in rows] == ["superseded", "trusted"]
        assert [row["events"] for row in rows] == [1, 1]


def test_same_size_boundary_change_preserves_prior_events(tmp_path: Path) -> None:
    ledger = _captured_ledger(tmp_path)
    with open_ledger(ledger) as connection:
        connection.execute(
            "update parser_checkpoints set boundary_sha256 = ?", ("b" * 64,)
        )
        connection.commit()
    ledger_sync.synchronize_parser_workset(ledger)
    with open_ledger(ledger, read_only=True) as connection:
        rows = _generations(connection)
        assert [row["status"] for row in rows] == ["superseded", "trusted"]
        assert [row["events"] for row in rows] == [1, 1]


def test_generation_insert_failure_rolls_back_source_and_trust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _captured_ledger(tmp_path)
    with open_ledger(ledger) as connection:
        original_device = connection.execute(
            "select source_device from ledger_sources"
        ).fetchone()[0]
        original_revision = connection.execute(
            "select value from ledger_meta where key = 'ledger_revision'"
        ).fetchone()[0]
        connection.execute("update parser_checkpoints set source_device = '987654321'")
        connection.commit()

    def fail_insertion(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected event insertion failure")

    with monkeypatch.context() as patch:
        patch.setattr(ledger_sync, "insert_generation_events", fail_insertion)
        with pytest.raises(RuntimeError, match="injected event insertion failure"):
            ledger_sync.synchronize_parser_workset(ledger)

    with open_ledger(ledger, read_only=True) as connection:
        assert connection.execute(
            "select source_device from ledger_sources"
        ).fetchone()[0] == original_device
        assert connection.execute(
            "select value from ledger_meta where key = 'ledger_revision'"
        ).fetchone()[0] == original_revision
        rows = _generations(connection)
        assert len(rows) == 1
        assert rows[0]["status"] == "trusted"
        assert rows[0]["events"] == 1

    ledger_sync.synchronize_parser_workset(ledger)
    with open_ledger(ledger, read_only=True) as connection:
        assert len(_generations(connection)) == 2
