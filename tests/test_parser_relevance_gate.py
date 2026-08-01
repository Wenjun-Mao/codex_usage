from __future__ import annotations

import json
from pathlib import Path

import pytest

import codex_usage.parser as parser_module
from codex_usage.parser import parse_session_file


def _token_count() -> dict[str, object]:
    return {
        "timestamp": "2026-07-31T12:00:03Z",
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": 80,
                    "cached_input_tokens": 20,
                    "output_tokens": 20,
                    "total_tokens": 100,
                }
            },
        },
    }


def test_parser_decodes_only_relevant_candidate_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "session.jsonl"
    relevant = [
        {"timestamp": "2026-07-31T12:00:00Z", "type": "session_meta", "payload": {"id": "session", "cwd": "/repo/demo"}},
        {"timestamp": "2026-07-31T12:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.6-sol", "collaboration_mode": {"mode": "default"}}},
        {"timestamp": "2026-07-31T12:00:02Z", "type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-1", "collaboration_mode_kind": "default"}},
        _token_count(),
    ]
    lines = [
        json.dumps(relevant[0], separators=(",", ":")),
        json.dumps({"type": "response_item", "payload": {"text": "x" * 2_000_000}}),
        json.dumps(relevant[1], indent=2).replace("\n", " "),
        json.dumps(relevant[2]),
        json.dumps(relevant[3]),
        '{"type":"turn_context", malformed',
        json.dumps({"type": "response_item", "payload": {"token_count": "user content, not an event type"}}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    original_loads = parser_module.json.loads
    decoded: list[str] = []

    def counting_loads(value: str) -> object:
        decoded.append(value)
        return original_loads(value)

    monkeypatch.setattr(parser_module.json, "loads", counting_loads)
    records = parse_session_file(path)

    assert len(decoded) == 6
    assert len(records) == 1
    assert records[0].usage.total_tokens == 100
    assert records[0].model == "gpt-5.6-sol"
    assert records[0].turn_id == "turn-1"
    assert records[0].collaboration_mode == "default"


def test_irrelevant_marker_text_cannot_create_usage(tmp_path: Path) -> None:
    path = tmp_path / "misleading.jsonl"
    rows = [
        {"timestamp": "2026-07-31T12:00:00Z", "type": "session_meta", "payload": {"id": "misleading"}},
        {"timestamp": "2026-07-31T12:00:01Z", "type": "response_item", "payload": {"session_meta": "turn_context", "token_count": "task_started"}},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    assert parse_session_file(path) == []


def test_parser_accepts_unicode_escaped_relevant_event_labels(tmp_path: Path) -> None:
    path = tmp_path / "unicode.jsonl"
    rows = [
        {"timestamp": "2026-07-31T12:00:00Z", "type": "session_meta", "payload": {"id": "escaped-session"}},
        {"timestamp": "2026-07-31T12:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
        {"timestamp": "2026-07-31T12:00:02Z", "type": "event_msg", "payload": {"type": "task_started", "turn_id": "escaped-turn", "collaboration_mode_kind": "default"}},
        _token_count(),
    ]
    escaped_labels = (
        ("session_meta", r"\u0073ession_meta"),
        ("turn_context", r"\u0074urn_context"),
        ("task_started", r"\u0074ask_started"),
        ("token_count", r"\u0074oken_count"),
    )
    lines = [
        json.dumps(row).replace(f'"{label}"', f'"{escaped_label}"')
        for row, (label, escaped_label) in zip(rows, escaped_labels, strict=True)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    records = parse_session_file(path)

    assert len(records) == 1
    assert records[0].session_id == "escaped-session"
    assert records[0].model == "gpt-5.6-sol"
    assert records[0].turn_id == "escaped-turn"
    assert records[0].collaboration_mode == "default"
    assert records[0].usage.total_tokens == 100
