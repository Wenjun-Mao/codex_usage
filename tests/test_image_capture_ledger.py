from __future__ import annotations

import json
import sqlite3
import struct
from pathlib import Path

from image_capture_test_support import (
    image_call as _image_call,
    image_failure as _image_failure,
    image_result as _image_result,
    session_meta as _session_meta,
    token_count as _token_count,
    turn_context as _turn_context,
)

from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.image_models import ImageOperationKind, ImageOutcome
from codex_usage.ledger_migration import LegacyCacheCandidate, migrate_legacy_caches
from codex_usage.ledger_migration_source import legacy_cache_digest
from codex_usage.ledger_queries import load_ledger_image_operations, load_ledger_records
from codex_usage.ledger_schema import open_ledger
from codex_usage.parser import parse_session_append, parse_session_generation
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data
from codex_usage.session_parser_models import parser_state_to_json


def test_image_result_arriving_in_an_append_settles_the_original_call(
    tmp_path: Path,
) -> None:
    path = tmp_path / "session.jsonl"
    secret_prompt = "do-not-persist-this-prompt"
    rows = [
        _session_meta("task-image"),
        _turn_context(),
        _image_call("call-1", secret_prompt),
    ]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")

    first = parse_session_generation(path)

    assert len(first.image_operations) == 1
    assert first.image_operations[0].kind is ImageOperationKind.EDIT_REFERENCE
    assert first.image_operations[0].outcome is ImageOutcome.ATTEMPTED
    assert secret_prompt not in parser_state_to_json(first.checkpoint.state)

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_image_result("call-1", count=2)) + "\n")
    appended = parse_session_append(
        path, first.checkpoint, stop_offset=path.stat().st_size
    )

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
                    {
                        "model": "gpt-image-2",
                        "prompt": "private",
                        "input_image": content,
                    }
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
    initial = [
        _session_meta("task-partial"),
        _turn_context(),
        _image_call("call-1", "secret"),
    ]
    path.write_text(
        "".join(f"{json.dumps(row)}\n" for row in initial), encoding="utf-8"
    )
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
    appended = parse_session_append(
        path, first.checkpoint, stop_offset=path.stat().st_size
    )

    assert [
        (item.tool_call_id, item.outcome, item.output_count)
        for item in appended.image_operations
    ] == [
        ("call-1", ImageOutcome.SUCCEEDED, 2),
        ("direct-1", ImageOutcome.SUCCEEDED, 3),
    ]


def test_mapping_result_preserves_an_explicit_zero_output_count(tmp_path: Path) -> None:
    path = tmp_path / "mapping-result.jsonl"
    rows = [
        _session_meta("task-mapping"),
        _turn_context(),
        _image_call("call-mapping", "secret"),
        {
            "timestamp": "2026-09-12T10:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call-mapping",
                "output": {"output_count": 0, "n": 2, "status": "succeeded"},
            },
        },
    ]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")

    parsed = parse_session_generation(path)

    assert [(item.outcome, item.output_count) for item in parsed.image_operations] == [
        (ImageOutcome.ATTEMPTED, 0),
        (ImageOutcome.SUCCEEDED, 0),
    ]


def test_large_escaped_error_result_settles_a_pending_image_call(
    tmp_path: Path,
) -> None:
    path = tmp_path / "large-error.jsonl"
    detail = "a" * 2_000_000
    rows = [
        _session_meta("task-large-error"),
        _turn_context(),
        _image_call("call-large-error", "secret"),
        {
            "timestamp": "2026-09-12T10:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call-large-error",
                "output": json.dumps({"error": "generation failed", "detail": detail}),
            },
        },
    ]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")

    parsed = parse_session_generation(path)

    assert [item.outcome for item in parsed.image_operations] == [
        ImageOutcome.ATTEMPTED,
        ImageOutcome.FAILED,
    ]


def test_nested_exec_image_call_uses_signed_artifact_metadata(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    sessions = home / "sessions" / "2026" / "09" / "12"
    sessions.mkdir(parents=True)
    task_id = "task-nested"
    artifact_name = "exec-07b936fd-4c91-4430-b953-677e7abaafe7.png"
    artifacts = home / "generated_images" / task_id
    artifacts.mkdir(parents=True)
    (artifacts / artifact_name).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", 1536, 1024)
        + b"\x08\x06\x00\x00\x00"
        + b"c2pa.actions.v2 c2pa.signature softwareAgent name gpt-image version 2.0"
    )
    path = sessions / f"rollout-{task_id}.jsonl"
    rows = [
        _session_meta(task_id),
        _turn_context(),
        {
            "timestamp": "2026-09-12T10:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "call-nested",
                "input": "await tools.image_gen__imagegen({prompt: 'private', referenced_image_paths: ['/private/input.png']});",
            },
        },
        {
            "timestamp": "2026-09-12T10:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call-nested",
                "output": [
                    {"type": "input_text", "text": f"output_hint: {artifact_name}"},
                    {
                        "type": "input_text",
                        "text": "image_url: data:image/png;base64,private",
                    },
                ],
            },
        },
    ]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")

    parsed = parse_session_generation(path)

    attempted, succeeded = parsed.image_operations
    assert attempted.kind is ImageOperationKind.EDIT_REFERENCE
    assert succeeded.outcome is ImageOutcome.SUCCEEDED
    assert (
        succeeded.output_count,
        succeeded.output_width,
        succeeded.output_height,
    ) == (
        1,
        1536,
        1024,
    )
    assert [(item.raw_identity, item.version) for item in succeeded.evidence] == [
        ("gpt-image", "2.0")
    ]


def test_nested_exec_quoted_json_arguments_are_recognized(tmp_path: Path) -> None:
    path = tmp_path / "quoted.jsonl"
    nested = json.dumps(
        json.dumps({"prompt": "private", "num_last_images_to_include": 1})
    )
    rows = [
        _session_meta("task-quoted"),
        _turn_context(),
        {
            "timestamp": "2026-09-12T10:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "call-quoted",
                "input": f"await tools.image_gen__imagegen({nested});",
            },
        },
    ]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")

    parsed = parse_session_generation(path)

    assert parsed.image_operations[0].kind is ImageOperationKind.EDIT_REFERENCE


def test_extension_completion_settles_nested_call_before_large_output(
    tmp_path: Path,
) -> None:
    path = tmp_path / "extension.jsonl"
    rows = [
        _session_meta("task-extension"),
        _turn_context(),
        {
            "timestamp": "2026-09-12T10:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "call-extension",
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
                    "id": "exec-07b936fd-4c91-4430-b953-677e7abaafe7",
                    "status": "completed",
                    "failure": None,
                    "savedPath": "/private/never-persist.png",
                },
            },
        },
    ]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")

    parsed = parse_session_generation(path)

    assert [item.outcome for item in parsed.image_operations] == [
        ImageOutcome.ATTEMPTED,
        ImageOutcome.SUCCEEDED,
    ]
    assert parsed.image_operations[-1].output_count == 1
    assert "never-persist" not in parser_state_to_json(parsed.checkpoint.state)


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
    load_cached_session_data(
        [sessions.parents[2]],
        cache_dir=cache_dir,
        auto_transitions=False,
        max_workers=1,
    )
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


def test_capture_persists_only_image_metadata_and_updates_retry_in_place(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    directory = home / "sessions" / "2026" / "09" / "12"
    directory.mkdir(parents=True)
    path = directory / "rollout-task-image.jsonl"
    secret = "private-prompt-text"
    rows = [
        _session_meta("task-image"),
        _turn_context(),
        _image_call("call-1", secret),
        _image_result("call-1", count=1),
    ]
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
    assert (
        capture_once(home, request_kind="scheduled", max_workers=1).outcome == "success"
    )
    with sqlite3.connect(ledger) as connection:
        rows = connection.execute(
            "select tool_call_id, outcome, output_count from ledger_image_events order by tool_call_id"
        ).fetchall()
    assert rows == [
        ("call-1", "succeeded", 1),
        ("call-2", "failed", 0),
        ("call-3", "succeeded", 3),
    ]


def test_image_capture_keeps_language_ledger_rows_unchanged(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    directory = home / "sessions" / "2026" / "09" / "12"
    directory.mkdir(parents=True)
    path = directory / "rollout-task-language.jsonl"
    rows = [
        _session_meta("task-language"),
        _turn_context(),
        _token_count(125),
        _image_call("call-language", "secret"),
        _image_result("call-language", count=1),
    ]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")

    assert capture_once(home, request_kind="manual", max_workers=1).outcome == "success"
    ledger = ledger_database_path(home)

    assert [record.usage.to_dict() for record in load_ledger_records(ledger)] == [
        {
            "input_tokens": 125,
            "cached_input_tokens": 0,
            "cache_write_input_tokens": 0,
            "uncached_input_tokens": 125,
            "ordinary_input_tokens": 125,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
            "total_tokens": 125,
        }
    ]
    assert [
        (operation.tool_call_id, operation.usage.image_output_tokens)
        for operation in load_ledger_image_operations(ledger)
    ] == [("call-language", 20)]
