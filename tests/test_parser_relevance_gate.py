from __future__ import annotations

import json
from pathlib import Path

import pytest

import codex_usage.parser as parser_module
import codex_usage.session_parser_events as parser_events
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


def test_parser_uses_buffered_binary_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "buffered.jsonl"
    path.write_text(json.dumps(_token_count()) + "\n", encoding="utf-8")
    original_open = Path.open
    observed_buffering: list[int] = []

    def tracking_open(candidate: Path, *args: object, **kwargs: object):
        if candidate == path and args == ("rb",):
            observed_buffering.append(int(kwargs.get("buffering", -1)))
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracking_open)

    parse_session_file(path)

    assert observed_buffering == [parser_module.SESSION_READ_BUFFER_BYTES]
    assert observed_buffering[0] > 0


def test_parser_decodes_only_relevant_candidate_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "session.jsonl"
    relevant = [
        {"timestamp": "2026-07-31T12:00:00Z", "type": "session_meta", "payload": {"id": "session", "cwd": "/repo/demo"}},
        {"timestamp": "2026-07-31T12:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.6-sol", "collaboration_mode": {"mode": "default"}}},
        {"timestamp": "2026-07-31T12:00:01Z", "type": "inter_agent_communication_metadata", "payload": {}},
        {"timestamp": "2026-07-31T12:00:02Z", "type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-1", "collaboration_mode_kind": "default"}},
        _token_count(),
    ]
    lines = [
        json.dumps(relevant[0], separators=(",", ":")),
        json.dumps(
            {
                "type": "response_item",
                "payload": {"type": "message", "text": "x" * 2_000_000},
            }
        ),
        json.dumps(relevant[1], indent=2).replace("\n", " "),
        json.dumps(relevant[2]),
        json.dumps(relevant[3]),
        json.dumps(relevant[4]),
        '{"type":"turn_context", malformed',
        json.dumps({"type": "response_item", "payload": {"token_count": "user content, not an event type"}}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    original_loads = parser_events.json.loads
    decoded: list[str] = []

    def counting_loads(value: str) -> object:
        decoded.append(value)
        return original_loads(value)

    monkeypatch.setattr(parser_events.json, "loads", counting_loads)
    records = parse_session_file(path)

    assert len(decoded) == 7
    assert len(records) == 1
    assert records[0].usage.total_tokens == 100
    assert records[0].model == "gpt-5.6-sol"
    assert records[0].turn_id == "turn-1"
    assert records[0].collaboration_mode == "default"


def test_known_irrelevant_row_is_skipped_before_utf8_decode(tmp_path: Path) -> None:
    path = tmp_path / "irrelevant-invalid-utf8.jsonl"
    rows = [
        json.dumps(
            {
                "timestamp": "2026-07-31T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "session", "cwd": "/repo/demo"},
            }
        ).encode(),
        b'{"type":"response_item","payload":{"type":"message","text":"'
        + (b"x" * 10_000)
        + b'\xff"}}',
        json.dumps(_token_count()).encode(),
    ]
    path.write_bytes(b"\n".join(rows) + b"\n")

    records = parse_session_file(path)

    assert [record.usage.total_tokens for record in records] == [100]


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


def test_reordered_response_item_discriminator_falls_back_to_full_line(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reordered-response.jsonl"
    target = tmp_path / "target"
    rows = [
        {
            "timestamp": "2026-07-31T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": "reordered", "cwd": "/repo/demo"},
        },
        {
            "timestamp": "2026-07-31T12:00:01Z",
            "type": "response_item",
            "padding": "x" * 5_000,
            "payload": {
                "type": "function_call",
                "arguments": json.dumps({"workdir": str(target)}),
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    generation = parser_module.parse_session_generation(path)

    assert [candidate.raw_path for candidate in generation.candidates] == [str(target)]


def test_reordered_event_discriminator_falls_back_to_full_line(tmp_path: Path) -> None:
    path = tmp_path / "reordered-event.jsonl"
    rows = [
        {
            "timestamp": "2026-07-31T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": "reordered", "cwd": "/repo/demo"},
        },
        {
            "timestamp": "2026-07-31T12:00:01Z",
            "type": "event_msg",
            "padding": "x" * 5_000,
            "payload": _token_count()["payload"],
        },
    ]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    records = parse_session_file(path)

    assert [record.usage.total_tokens for record in records] == [100]
