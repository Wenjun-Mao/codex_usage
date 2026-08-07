from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from codex_usage.parser import (
    CHECKPOINT_DIGEST_BYTES,
    AppendCheckpointMismatch,
    parse_session_append,
    parse_session_generation,
)


def test_repeated_appends_match_a_from_zero_oracle(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    _write_rows(
        path,
        [
            _session_meta("task-1", "/repo/main", parent_thread_id="parent-1"),
            _turn_context("gpt-5.6-sol", "turn-1", "high", "default"),
            _token("2026-08-07T10:00:00Z", 100),
        ],
    )
    first = parse_session_generation(path)

    _append_rows(
        path,
        [
            _function_call("2026-08-07T10:01:00Z", "/repo/other"),
            _turn_context("gpt-5.6-terra", "turn-2", "medium", "plan"),
            _token("2026-08-07T10:02:00Z", 160),
        ],
    )
    second = parse_session_append(
        path,
        first.checkpoint,
        stop_offset=path.stat().st_size,
    )
    _append_rows(
        path,
        [
            _task_started("turn-3", "default"),
            _token("2026-08-07T10:03:00Z", 200),
        ],
    )
    third = parse_session_append(
        path,
        second.checkpoint,
        stop_offset=path.stat().st_size,
    )
    oracle = parse_session_generation(path)

    assert first.records + second.records + third.records == oracle.records
    assert first.candidates + second.candidates + third.candidates == oracle.candidates
    assert third.metadata == oracle.metadata
    assert third.checkpoint.state == oracle.checkpoint.state
    assert third.checkpoint.byte_offset == oracle.checkpoint.byte_offset
    assert third.checkpoint.next_record_index == len(oracle.records)
    assert third.checkpoint.next_candidate_index == len(oracle.candidates)
    assert [record.usage.total_tokens for record in oracle.records] == [100, 60, 40]
    assert [record.model for record in oracle.records] == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-terra",
    ]
    assert oracle.records[-1].turn_id == "turn-3"
    assert oracle.records[0].usage_role == "subagent"


def test_fork_state_survives_an_append_boundary(tmp_path: Path) -> None:
    path = tmp_path / "fork.jsonl"
    _write_rows(
        path,
        [
            _session_meta("fork-task", "/repo/fork", forked_from_id="parent-task"),
            _turn_context("gpt-5.6-sol", "fork-before", "high", "default"),
            _token("2026-08-07T11:00:00Z", 1_000),
            _session_meta("parent-task", "/repo/parent"),
            _token("2026-08-07T11:01:00Z", 2_000),
        ],
    )
    first = parse_session_generation(path)
    assert first.records == ()

    _append_rows(
        path,
        [
            _session_meta("fork-task", "/repo/fork", forked_from_id="parent-task"),
            _turn_context("gpt-5.6-sol", "fork-after", "high", "default"),
            _token("2026-08-07T11:02:00Z", 2_100),
            _token("2026-08-07T11:03:00Z", 2_300),
        ],
    )
    appended = parse_session_append(
        path,
        first.checkpoint,
        stop_offset=path.stat().st_size,
    )
    oracle = parse_session_generation(path)

    assert appended.records == oracle.records
    assert [record.usage.total_tokens for record in oracle.records] == [100, 200]
    assert all(record.session_id == "fork-task" for record in oracle.records)
    assert appended.checkpoint.state == oracle.checkpoint.state


def test_incomplete_final_row_is_deferred_until_completed(tmp_path: Path) -> None:
    path = tmp_path / "partial.jsonl"
    _write_rows(
        path,
        [
            _session_meta("partial-task", "/repo/partial"),
            _turn_context("gpt-5.6-sol", "turn-1", "medium", "default"),
            _token("2026-08-07T12:00:00Z", 100),
        ],
    )
    partial_row = json.dumps(_token("2026-08-07T12:01:00Z", 175)).encode()
    split_at = len(partial_row) // 2
    with path.open("ab") as handle:
        partial_start = handle.tell()
        handle.write(partial_row[:split_at])

    first = parse_session_generation(path)
    assert first.checkpoint.byte_offset == partial_start
    assert [record.usage.total_tokens for record in first.records] == [100]

    with path.open("ab") as handle:
        handle.write(partial_row[split_at:] + b"\n")
    appended = parse_session_append(
        path,
        first.checkpoint,
        stop_offset=path.stat().st_size,
    )
    oracle = parse_session_generation(path)

    assert first.records + appended.records == oracle.records
    assert [record.usage.total_tokens for record in appended.records] == [75]
    assert appended.checkpoint.byte_offset == path.stat().st_size


def test_valid_unterminated_row_is_processed_and_checkpointed(tmp_path: Path) -> None:
    path = tmp_path / "unterminated.jsonl"
    rows = [
        _session_meta("unterminated-task", "/repo/unterminated"),
        _turn_context("gpt-5.6-sol", "turn-1", "medium", "default"),
        _token("2026-08-07T13:00:00Z", 100),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    generation = parse_session_generation(path)

    assert [record.usage.total_tokens for record in generation.records] == [100]
    assert generation.checkpoint.byte_offset == path.stat().st_size


def test_guarded_append_rejects_replacement_and_boundary_modification(
    tmp_path: Path,
) -> None:
    path = tmp_path / "guarded.jsonl"
    large_irrelevant = {
        "type": "response_item",
        "payload": {"type": "message", "text": "x" * (CHECKPOINT_DIGEST_BYTES * 3)},
    }
    _write_rows(
        path,
        [
            _session_meta("guarded-task", "/repo/guarded"),
            _turn_context("gpt-5.6-sol", "turn-1", "medium", "default"),
            _token("2026-08-07T14:00:00Z", 100),
            large_irrelevant,
        ],
    )
    generation = parse_session_generation(path)
    original_size = path.stat().st_size
    _append_rows(path, [_token("2026-08-07T14:01:00Z", 150)])
    with path.open("r+b") as handle:
        handle.seek(original_size - 20)
        original = handle.read(1)
        handle.seek(original_size - 20)
        handle.write(b"y" if original != b"y" else b"z")

    with pytest.raises(AppendCheckpointMismatch, match="boundary changed"):
        parse_session_append(
            path,
            generation.checkpoint,
            stop_offset=path.stat().st_size,
        )

    replacement = tmp_path / "replacement.jsonl"
    replacement.write_bytes(path.read_bytes())
    os.replace(replacement, path)
    with pytest.raises(AppendCheckpointMismatch, match="identity changed"):
        parse_session_append(
            path,
            generation.checkpoint,
            stop_offset=path.stat().st_size,
        )


def test_append_reads_only_tail_and_fixed_guard_windows(tmp_path: Path) -> None:
    path = tmp_path / "large.jsonl"
    _write_rows(
        path,
        [
            _session_meta("large-task", "/repo/large"),
            {
                "type": "response_item",
                "payload": {"type": "message", "text": "x" * 2_000_000},
            },
            _turn_context("gpt-5.6-sol", "turn-1", "medium", "default"),
            _token("2026-08-07T15:00:00Z", 100),
        ],
    )
    first = parse_session_generation(path)
    old_size = path.stat().st_size
    _append_rows(path, [_token("2026-08-07T15:01:00Z", 125)])
    tail_size = path.stat().st_size - old_size

    appended = parse_session_append(
        path,
        first.checkpoint,
        stop_offset=path.stat().st_size,
    )

    assert [record.usage.total_tokens for record in appended.records] == [25]
    assert appended.bytes_read <= tail_size + (4 * CHECKPOINT_DIGEST_BYTES)
    assert appended.bytes_read < path.stat().st_size // 2


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(f"{json.dumps(row)}\n" for row in rows),
        encoding="utf-8",
    )


def _append_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(f"{json.dumps(row)}\n")


def _session_meta(
    session_id: str,
    cwd: str,
    *,
    forked_from_id: str = "",
    parent_thread_id: str = "",
) -> dict[str, object]:
    source: object = "vscode"
    if parent_thread_id:
        source = {"subagent": {"thread_spawn": {"parent_thread_id": parent_thread_id}}}
    return {
        "timestamp": "2026-08-07T09:59:00Z",
        "type": "session_meta",
        "payload": {
            "id": session_id,
            "cwd": cwd,
            "forked_from_id": forked_from_id,
            "source": source,
        },
    }


def _turn_context(
    model: str,
    turn_id: str,
    effort: str,
    mode: str,
) -> dict[str, object]:
    return {
        "timestamp": "2026-08-07T09:59:30Z",
        "type": "turn_context",
        "payload": {
            "model": model,
            "turn_id": turn_id,
            "effort": effort,
            "collaboration_mode": {"mode": mode},
        },
    }


def _task_started(turn_id: str, mode: str) -> dict[str, object]:
    return {
        "timestamp": "2026-08-07T10:02:30Z",
        "type": "event_msg",
        "payload": {
            "type": "task_started",
            "turn_id": turn_id,
            "collaboration_mode_kind": mode,
        },
    }


def _token(timestamp: str, total: int) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total,
                    "total_tokens": total,
                }
            },
        },
    }


def _function_call(timestamp: str, workdir: str) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "arguments": json.dumps({"workdir": workdir, "command": "pwd"}),
        },
    }
