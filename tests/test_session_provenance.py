from __future__ import annotations

import json
from pathlib import Path

from codex_usage.models import ROOT_USAGE_ROLE, SUBAGENT_USAGE_ROLE
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


def test_usage_records_keep_explicit_root_and_parentless_subagent_roles(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "root.jsonl"
    malformed_path = tmp_path / "malformed.jsonl"
    review_path = tmp_path / "review.jsonl"
    _write_session(root_path, "cli")
    _write_session(malformed_path, {"subagent": "review"})
    _write_session(review_path, {"subagent": {"other": "review"}})

    root = parse_session_file(root_path)
    malformed = parse_session_file(malformed_path)
    review = parse_session_file(review_path)

    assert [record.usage_role for record in root] == [ROOT_USAGE_ROLE]
    assert [record.usage_role for record in malformed] == [ROOT_USAGE_ROLE]
    assert [record.usage_role for record in review] == [SUBAGENT_USAGE_ROLE]
    assert review[0].parent_thread_id == ""
