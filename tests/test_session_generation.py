from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_usage.parser import parse_session_generation
from codex_usage.session_files import read_session_metadata


def test_combined_generation_opens_jsonl_once_and_returns_all_products(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = write_session_with_usage_and_workdir(tmp_path)
    original_open = Path.open
    opens = 0

    def counted_open(path: Path, *args: object, **kwargs: object):
        nonlocal opens
        if path == session:
            opens += 1
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted_open)
    generation = parse_session_generation(session)

    assert opens == 1
    assert [record.usage.total_tokens for record in generation.records] == [100, 50]
    assert generation.metadata.session_id == "combined-thread"
    assert [candidate.thread_id for candidate in generation.candidates] == ["combined-thread"]
    assert generation.candidates[0].raw_path == str(tmp_path / "target-repo")


def test_combined_generation_matches_frozen_session_semantics(tmp_path: Path) -> None:
    path = tmp_path / "mixed-session.jsonl"
    target_repo = tmp_path / "target-repo"
    rows = [
        _session_meta(
            "fork-session",
            "/repo/fork",
            forked_from_id="parent-session",
            source={"subagent": {"thread_spawn": {"parent_thread_id": "outer-thread"}}},
        ),
        _turn_context("gpt-5.6-sol", "fork-turn"),
        _token("2026-08-03T12:00:00Z", 1_000),
        _session_meta("parent-session", "/repo/parent"),
        _turn_context("gpt-5.6-sol", "parent-turn"),
        _token("2026-08-03T12:01:00Z", 2_000),
        "{malformed json",
        _session_meta("fork-session", "/repo/fork", forked_from_id="parent-session"),
        _turn_context("gpt-5.6-sol", "fork-turn-2"),
        _token("2026-08-03T12:02:00Z", 2_100),
        _function_call("2026-08-03T12:03:00Z", target_repo),
        _token("2026-08-03T12:04:00Z", 2_300),
    ]
    path.write_text("\n".join(_encode_row(row) for row in rows), encoding="utf-8")

    generation = parse_session_generation(path)

    assert generation.metadata.session_id == "fork-session"
    assert generation.metadata.cwd == "/repo/fork"
    assert generation.metadata.forked_from_id == "parent-session"
    assert generation.metadata.is_subagent is True
    assert generation.metadata.parent_thread_id == "outer-thread"
    assert generation.metadata == read_session_metadata(path)
    assert [(record.session_id, record.turn_id, record.usage.total_tokens) for record in generation.records] == [
        ("fork-session", "fork-turn-2", 100),
        ("fork-session", "fork-turn-2", 200),
    ]
    assert generation.records[0].timestamp == datetime(2026, 8, 3, 12, 2, tzinfo=UTC)
    assert generation.candidates[0].thread_id == "fork-session"
    assert generation.candidates[0].raw_path == str(target_repo)
    assert generation.candidates[0].source == "jsonl:response_item:function_call_workdir"


def write_session_with_usage_and_workdir(tmp_path: Path) -> Path:
    path = tmp_path / "combined.jsonl"
    rows = [
        _session_meta("combined-thread", str(tmp_path / "source-repo")),
        _turn_context("gpt-5.6-sol", "turn-1"),
        _token("2026-08-03T12:00:00Z", 100),
        _function_call("2026-08-03T12:01:00Z", tmp_path / "target-repo"),
        _token("2026-08-03T12:02:00Z", 150),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _session_meta(
    session_id: str,
    cwd: str,
    *,
    forked_from_id: str = "",
    source: object = "",
) -> dict[str, object]:
    return {
        "timestamp": "2026-08-03T11:59:00Z",
        "type": "session_meta",
        "payload": {
            "id": session_id,
            "cwd": cwd,
            "forked_from_id": forked_from_id,
            "source": source,
        },
    }


def _turn_context(model: str, turn_id: str) -> dict[str, object]:
    return {
        "timestamp": "2026-08-03T11:59:30Z",
        "type": "turn_context",
        "payload": {"model": model, "turn_id": turn_id},
    }


def _token(timestamp: str, total: int) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {"total_token_usage": {"total_tokens": total}},
        },
    }


def _function_call(timestamp: str, workdir: Path) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "arguments": json.dumps({"workdir": str(workdir), "command": "pwd"}),
        },
    }


def _encode_row(row: dict[str, object] | str) -> str:
    if isinstance(row, str):
        return row
    encoded = json.dumps(row)
    if row.get("type") == "session_meta" and row["payload"].get("id") == "fork-session":
        return encoded.replace('"session_meta"', r'"\u0073ession_meta"')
    return encoded
