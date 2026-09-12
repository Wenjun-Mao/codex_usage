from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.image_models import ImageOperationKind, ImageOutcome
from codex_usage.ledger_migration import LegacyCacheCandidate, migrate_legacy_caches
from codex_usage.ledger_migration_source import legacy_cache_digest
from codex_usage.ledger_queries import load_ledger_image_operations
from codex_usage.ledger_schema import open_ledger
from codex_usage.parser import parse_session_append, parse_session_generation
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data
from codex_usage.session_parser_models import parser_state_to_json


def test_image_result_arriving_in_an_append_settles_the_original_call(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    secret_prompt = "do-not-persist-this-prompt"
    rows = [_session_meta("task-image"), _turn_context(), _image_call("call-1", secret_prompt)]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")

    first = parse_session_generation(path)

    assert len(first.image_operations) == 1
    assert first.image_operations[0].kind is ImageOperationKind.EDIT_REFERENCE
    assert first.image_operations[0].outcome is ImageOutcome.ATTEMPTED
    assert secret_prompt not in parser_state_to_json(first.checkpoint.state)

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_image_result("call-1", count=2)) + "\n")
    appended = parse_session_append(path, first.checkpoint, stop_offset=path.stat().st_size)

    assert len(appended.image_operations) == 1
    operation = appended.image_operations[0]
    assert operation.tool_call_id == "call-1"
    assert operation.outcome is ImageOutcome.SUCCEEDED
    assert operation.output_count == 2
    assert operation.usage.cached_text_input_tokens == 0
    assert operation.usage.image_input_tokens == 0
    assert appended.checkpoint.state.image_capture.pending == ()


def test_large_base64_tool_rows_are_drained_without_becoming_ledger_content(
    tmp_path: Path,
) -> None:
    path = tmp_path / "large.jsonl"
    content = "a" * 2_000_000
    rows = [
        _session_meta("task-large"),
        _turn_context(),
        {
            "timestamp": "2026-09-12T10:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "image_gen",
                "call_id": "call-large",
                "arguments": json.dumps(
                    {"model": "gpt-image-2", "prompt": "private", "input_image": content}
                ),
            },
        },
        {
            "timestamp": "2026-09-12T10:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call-large",
                "output": json.dumps({"data": [{"b64_json": content}]}),
            },
        },
    ]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")

    parsed = parse_session_generation(path)

    assert [operation.outcome for operation in parsed.image_operations] == [
        ImageOutcome.ATTEMPTED,
        ImageOutcome.SUCCEEDED,
    ]
    assert parsed.bytes_read < path.stat().st_size * 2
    state = parser_state_to_json(parsed.checkpoint.state)
    assert content not in state
    assert "private" not in state


def test_incomplete_image_result_and_direct_events_preserve_operation_contract(
    tmp_path: Path,
) -> None:
    path = tmp_path / "partial.jsonl"
    initial = [_session_meta("task-partial"), _turn_context(), _image_call("call-1", "secret")]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in initial), encoding="utf-8")
    partial = json.dumps(_image_result("call-1", count=2)).encode()
    with path.open("ab") as handle:
        split = len(partial) // 2
        partial_start = handle.tell()
        handle.write(partial[:split])

    first = parse_session_generation(path)

    assert first.checkpoint.byte_offset == partial_start
    assert first.checkpoint.state.image_capture.pending[0].tool_call_id == "call-1"
    with path.open("ab") as handle:
        handle.write(partial[split:] + b"\n")
        handle.write(
            json.dumps(
                {
                    "timestamp": "2026-09-12T10:00:04Z",
                    "type": "response_item",
                    "payload": {
                        "type": "image_generation",
                        "id": "direct-1",
                        "model": "gpt-image-2",
                        "data": [{}, {}, {}],
                    },
                }
            ).encode()
            + b"\n"
        )
    appended = parse_session_append(path, first.checkpoint, stop_offset=path.stat().st_size)

    assert [(item.tool_call_id, item.outcome, item.output_count) for item in appended.image_operations] == [
        ("call-1", ImageOutcome.SUCCEEDED, 2),
        ("direct-1", ImageOutcome.SUCCEEDED, 3),
    ]


def test_targeted_legacy_backfill_recovers_image_operations(tmp_path: Path) -> None:
    sessions = tmp_path / "legacy" / "sessions" / "2026" / "09" / "12"
    sessions.mkdir(parents=True)
    session_path = sessions / "rollout-task-backfill.jsonl"
    session_path.write_text(
        "".join(
            f"{json.dumps(row)}\n"
            for row in (
                _session_meta("task-backfill"),
                _turn_context(),
                _image_call("call-backfill", "never-retain"),
                _image_result("call-backfill", count=2),
            )
        ),
        encoding="utf-8",
    )
    cache_dir = tmp_path / "legacy" / "cache"
    load_cached_session_data([sessions.parents[2]], cache_dir=cache_dir, auto_transitions=False, max_workers=1)
    cache = cache_dir / CACHE_DB_NAME
    ledger = tmp_path / "ledger.sqlite3"
    with open_ledger(ledger):
        pass

    result = migrate_legacy_caches(
        ledger,
        (LegacyCacheCandidate(cache, legacy_cache_digest(cache), "targeted"),),
    )

    assert result["imported_caches"] == 1
    with sqlite3.connect(ledger) as connection:
        assert connection.execute(
            "select tool_call_id, outcome, output_count from ledger_image_events"
        ).fetchall() == [("call-backfill", "succeeded", 2)]


def test_capture_persists_only_image_metadata_and_updates_retry_in_place(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    directory = home / "sessions" / "2026" / "09" / "12"
    directory.mkdir(parents=True)
    path = directory / "rollout-task-image.jsonl"
    secret = "private-prompt-text"
    rows = [_session_meta("task-image"), _turn_context(), _image_call("call-1", secret), _image_result("call-1", count=1)]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")

    result = capture_once(home, request_kind="manual", max_workers=1)
    ledger = ledger_database_path(home)

    assert result.outcome == "success"
    with sqlite3.connect(ledger) as connection:
        row = connection.execute(
            "select tool_call_id, outcome, output_count, evidence_json, usage_json from ledger_image_events"
        ).fetchone()
        cache_row = connection.execute(
            "select evidence_json, usage_json from image_operations"
        ).fetchone()
        dump = " ".join(str(value) for value in (*row, *cache_row))
    assert row[:3] == ("call-1", "succeeded", 1)
    assert secret not in dump
    operations = load_ledger_image_operations(ledger)
    assert [(item.tool_call_id, item.output_count) for item in operations] == [
        ("call-1", 1)
    ]

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_image_call("call-2", "failed-secret")) + "\n")
        handle.write(json.dumps(_image_failure("call-2")) + "\n")
        handle.write(json.dumps(_image_call("call-3", "retry-secret")) + "\n")
        handle.write(json.dumps(_image_result("call-3", count=3)) + "\n")
    assert capture_once(home, request_kind="scheduled", max_workers=1).outcome == "success"
    with sqlite3.connect(ledger) as connection:
        rows = connection.execute(
            "select tool_call_id, outcome, output_count from ledger_image_events order by tool_call_id"
        ).fetchall()
    assert rows == [
        ("call-1", "succeeded", 1),
        ("call-2", "failed", 0),
        ("call-3", "succeeded", 3),
    ]


def test_image_ledger_migration_creates_a_pre_migration_backup(tmp_path: Path) -> None:
    ledger = tmp_path / "usage-ledger.sqlite3"
    with open_ledger(ledger):
        pass
    with sqlite3.connect(ledger) as connection:
        connection.execute("drop table ledger_image_events")
        connection.execute("update ledger_meta set value = '1' where key = 'schema_version'")
        connection.commit()

    with open_ledger(ledger) as connection:
        version = connection.execute(
            "select value from ledger_meta where key = 'schema_version'"
        ).fetchone()[0]
        assert connection.execute(
            "select 1 from sqlite_master where type = 'table' and name = 'ledger_image_events'"
        ).fetchone() is not None

    backups = list(tmp_path.glob("usage-ledger.sqlite3.schema-1-backup-*"))
    assert version == "2"
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute(
            "select value from ledger_meta where key = 'schema_version'"
        ).fetchone()[0] == "1"
        assert connection.execute(
            "select 1 from sqlite_master where type = 'table' and name = 'ledger_image_events'"
        ).fetchone() is None


def _session_meta(task_id: str) -> dict[str, object]:
    return {
        "timestamp": "2026-09-12T10:00:00Z",
        "type": "session_meta",
        "payload": {"id": task_id, "cwd": "/repo/image"},
    }


def _turn_context() -> dict[str, object]:
    return {
        "timestamp": "2026-09-12T10:00:01Z",
        "type": "turn_context",
        "payload": {"turn_id": "turn-image", "model": "gpt-5.6-terra"},
    }


def _image_call(call_id: str, prompt: str) -> dict[str, object]:
    return {
        "timestamp": "2026-09-12T10:00:02Z",
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "image_gen",
            "call_id": call_id,
            "arguments": json.dumps(
                {
                    "model": "gpt-image-2",
                    "size": "1024x1024",
                    "quality": "high",
                    "prompt": prompt,
                    "referenced_image_paths": ["/private/input.png"],
                }
            ),
        },
    }


def _image_result(call_id: str, *, count: int) -> dict[str, object]:
    return {
        "timestamp": "2026-09-12T10:00:03Z",
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps(
                {
                    "model": "gpt-image-2",
                    "data": [{} for _ in range(count)],
                    "usage": {
                        "text_input_tokens": 10,
                        "cached_text_input_tokens": 0,
                        "image_input_tokens": 0,
                        "cached_image_input_tokens": 0,
                        "image_output_tokens": 20,
                    },
                }
            ),
        },
    }


def _image_failure(call_id: str) -> dict[str, object]:
    return {
        "timestamp": "2026-09-12T10:00:03Z",
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps({"status": "failed", "error": "generation failed"}),
        },
    }
