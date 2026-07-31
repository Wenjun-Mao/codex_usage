from __future__ import annotations

import json
from pathlib import Path

from codex_usage.parser import parse_session_file
from codex_usage.session_files import read_session_metadata
from codex_usage.session_provenance import (
    is_structured_subagent,
    parent_thread_id_from_source,
)


def _write_session(path: Path, source: object) -> None:
    rows = [
        {
            "timestamp": "2026-07-31T12:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": path.stem,
                "cwd": "/repo/demo",
                "source": source,
            },
        },
        {
            "timestamp": "2026-07-31T12:00:01Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.6-sol"},
        },
        {
            "timestamp": "2026-07-31T12:00:02Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {"input_tokens": 80, "output_tokens": 20, "total_tokens": 100}},
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_structured_subagent_classifies_spawn_and_parentless_guardian() -> None:
    spawned = {"source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}}}
    guardian = {"source": {"subagent": {"other": "guardian"}}}
    assert is_structured_subagent(spawned)
    assert is_structured_subagent(guardian)
    assert parent_thread_id_from_source(spawned) == "parent"
    assert parent_thread_id_from_source(guardian) == ""


def test_non_object_subagent_marker_does_not_change_root_classification() -> None:
    assert not is_structured_subagent({"source": "cli"})
    assert not is_structured_subagent({"source": {"subagent": "not-structured"}})


def test_metadata_marks_subagent_but_usage_parser_keeps_its_tokens(tmp_path: Path) -> None:
    path = tmp_path / "child.jsonl"
    _write_session(path, {"subagent": {"other": "review"}})
    metadata = read_session_metadata(path)
    assert metadata is not None and metadata.is_subagent
    assert sum(record.usage.total_tokens for record in parse_session_file(path)) == 100
