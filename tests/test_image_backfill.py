from __future__ import annotations

import json
import sqlite3
import struct
from pathlib import Path

from image_capture_test_support import session_meta, token_count, turn_context

from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.image_backfill import run_image_backfill_slice
from codex_usage.ledger_schema import open_ledger
from codex_usage.image_capture_payloads import has_reference_inputs


def test_null_reference_options_remain_fresh_generation() -> None:
    assert not has_reference_inputs(
        {
            "referenced_image_paths": None,
            "num_last_images_to_include": None,
        }
    )


def test_scheduled_artifact_first_backfill_preserves_language_ledger(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    directory = home / "sessions" / "2026" / "09" / "12"
    directory.mkdir(parents=True)
    task_id = "07b936fd-4c91-4430-b953-677e7abaafe7"
    path = directory / f"rollout-{task_id}.jsonl"
    artifact_name = "exec-f1d4d3db-0e01-4588-8d00-f151f42a9ec3.png"
    artifacts = home / "generated_images" / task_id
    artifacts.mkdir(parents=True)
    (artifacts / artifact_name).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", 1024, 1024)
        + b"\x08\x06\x00\x00\x00"
        + b"c2pa.actions.v2 c2pa.signature softwareAgent name gpt-image version 2.0"
    )
    rows = [
        session_meta(task_id),
        turn_context(),
        token_count(125),
        {
            "timestamp": "2026-09-12T10:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "call-backfill",
                "input": "await tools.image_gen__imagegen({prompt: 'private'});",
            },
        },
        {
            "timestamp": "2026-09-12T10:00:03Z",
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "Extension",
                    "kind": "image_gen.generation",
                    "id": artifact_name.removesuffix(".png"),
                    "status": "completed",
                    "failure": None,
                },
            },
        },
    ]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")
    assert capture_once(home, request_kind="manual", max_workers=1).outcome == "success"
    ledger = ledger_database_path(home)
    with sqlite3.connect(ledger) as connection:
        language_before = connection.execute(
            "select * from ledger_usage_events"
        ).fetchall()
        connection.execute("delete from image_operations")
        connection.execute("delete from ledger_image_events")
        connection.commit()

    result = capture_once(home, request_kind="scheduled", max_workers=1)

    assert result.outcome == "success"
    assert result.stats.source_bytes_read == 0
    assert result.status.image_backfill.complete
    with sqlite3.connect(ledger) as connection:
        assert (
            connection.execute("select * from ledger_usage_events").fetchall()
            == language_before
        )
        assert connection.execute(
            "select tool_call_id, outcome, output_count from ledger_image_events"
        ).fetchall() == [("call-backfill", "succeeded", 1)]


def test_image_ledger_migration_creates_a_pre_migration_backup(tmp_path: Path) -> None:
    ledger = tmp_path / "usage-ledger.sqlite3"
    with open_ledger(ledger):
        pass
    with sqlite3.connect(ledger) as connection:
        connection.execute("drop table ledger_image_events")
        connection.execute(
            "update ledger_meta set value = '1' where key = 'schema_version'"
        )
        connection.commit()

    with open_ledger(ledger) as connection:
        version = connection.execute(
            "select value from ledger_meta where key = 'schema_version'"
        ).fetchone()[0]
        assert (
            connection.execute(
                "select 1 from sqlite_master where type = 'table' and name = 'ledger_image_events'"
            ).fetchone()
            is not None
        )

    backups = list(tmp_path.glob("usage-ledger.sqlite3.schema-1-backup-*"))
    assert version == "2"
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert (
            connection.execute(
                "select value from ledger_meta where key = 'schema_version'"
            ).fetchone()[0]
            == "1"
        )
        assert (
            connection.execute(
                "select 1 from sqlite_master where type = 'table' and name = 'ledger_image_events'"
            ).fetchone()
            is None
        )


def test_artifact_first_backfill_never_opens_an_unrelated_rollout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / ".codex"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    task_id = "07b936fd-4c91-4430-b953-677e7abaafe7"
    owning = sessions / f"rollout-{task_id}.jsonl"
    owning.write_text(
        "".join(
            f"{json.dumps(row)}\n" for row in (session_meta(task_id), turn_context())
        ),
        encoding="utf-8",
    )
    unrelated = sessions / "rollout-unrelated.jsonl"
    unrelated.write_text("private unrelated source", encoding="utf-8")
    artifact_name = "exec-f1d4d3db-0e01-4588-8d00-f151f42a9ec3.png"
    artifacts = home / "generated_images" / task_id
    artifacts.mkdir(parents=True)
    (artifacts / artifact_name).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", 1024, 1024)
        + b"\x08\x06\x00\x00\x00"
    )
    ledger = ledger_database_path(home)
    with open_ledger(ledger):
        pass
    original_open = Path.open

    def guarded_open(path: Path, *args, **kwargs):
        if path == unrelated:
            raise AssertionError("backfill opened an unrelated rollout")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    result = run_image_backfill_slice(home, ledger)

    assert result.status == "complete"
