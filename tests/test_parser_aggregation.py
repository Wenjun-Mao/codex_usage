import json
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.aggregation import aggregate_records, filter_records_by_range, resolve_timezone, summarize_records
from codex_usage.parser import parse_session_file


def test_parser_uses_positive_cumulative_deltas(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="C:/repo/demo"),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", None),
            _token("2026-04-29T10:01:00Z", _usage(total=100, input_tokens=80, cached=20, output=20)),
            _token("2026-04-29T10:02:00Z", _usage(total=100, input_tokens=80, cached=20, output=20)),
            _token("2026-04-29T10:03:00Z", _usage(total=160, input_tokens=120, cached=30, output=40)),
        ],
    )

    records = parse_session_file(path)

    assert [record.usage.total_tokens for record in records] == [100, 60]
    assert summarize_records(records).usage.total_tokens == 160


def test_parser_tracks_model_changes_within_session(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(repo="https://github.com/example/demo.git"),
            _turn_context(model="gpt-5.4"),
            _token("2026-04-29T10:00:00Z", _usage(total=100)),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:05:00Z", _usage(total=175)),
        ],
    )

    records = parse_session_file(path)
    rows = aggregate_records(records, "model", resolve_timezone("UTC"))

    assert {row.key: row.usage.total_tokens for row in rows} == {"gpt-5.4": 100, "gpt-5.5": 75}


def test_project_grouping_falls_back_to_cwd_when_git_missing(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="D:\\Projects\\Demo"),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-29T10:00:00Z", _usage(total=100)),
        ],
    )

    record = parse_session_file(path)[0]

    assert record.project_key == "d:/projects/demo"
    assert record.project_label == "Demo"


def test_aggregation_by_day_and_hour_for_spanning_session(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="/repo/demo"),
            _turn_context(model="gpt-5.5"),
            _token("2026-04-28T23:55:00Z", _usage(total=100)),
            _token("2026-04-29T00:05:00Z", _usage(total=150)),
        ],
    )
    records = parse_session_file(path)
    timezone = resolve_timezone("UTC")

    day_rows = aggregate_records(records, "day", timezone)
    hour_rows = aggregate_records(records, "hour", timezone)

    assert [row.key for row in day_rows] == ["2026-04-28", "2026-04-29"]
    assert [row.usage.total_tokens for row in day_rows] == [100, 50]
    assert [row.key for row in hour_rows] == ["2026-04-28 23:00", "2026-04-29 00:00"]


def test_filter_records_by_month(tmp_path: Path) -> None:
    path = _write_session(
        tmp_path,
        [
            _session_meta(cwd="/repo/demo"),
            _turn_context(model="gpt-5.5"),
            _token("2026-03-31T23:00:00Z", _usage(total=100)),
            _token("2026-04-01T00:00:00Z", _usage(total=150)),
        ],
    )
    records = parse_session_file(path)
    filtered = filter_records_by_range(
        records,
        "month",
        resolve_timezone("UTC"),
        now=datetime(2026, 4, 29, tzinfo=UTC),
    )

    assert [record.usage.total_tokens for record in filtered] == [50]


def _write_session(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _session_meta(cwd: str = "/repo/demo", repo: str = "") -> dict:
    git = {"repository_url": repo, "branch": "main"} if repo else {}
    return {
        "timestamp": "2026-04-29T09:59:00Z",
        "type": "session_meta",
        "payload": {
            "id": "session-1",
            "timestamp": "2026-04-29T09:59:00Z",
            "cwd": cwd,
            "source": "vscode",
            "originator": "codex_vscode",
            "cli_version": "0.1.0",
            "git": git,
        },
    }


def _turn_context(model: str) -> dict:
    return {
        "timestamp": "2026-04-29T09:59:30Z",
        "type": "turn_context",
        "payload": {
            "turn_id": f"turn-{model}",
            "model": model,
            "effort": "medium",
            "collaboration_mode": {"mode": "default", "settings": {"model": model, "reasoning_effort": "medium"}},
        },
    }


def _token(timestamp: str, usage: dict | None) -> dict:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": None if usage is None else {"total_token_usage": usage},
        },
    }


def _usage(total: int, input_tokens: int | None = None, cached: int = 0, output: int | None = None) -> dict:
    input_value = input_tokens if input_tokens is not None else total
    output_value = output if output is not None else 0
    return {
        "input_tokens": input_value,
        "cached_input_tokens": cached,
        "output_tokens": output_value,
        "reasoning_output_tokens": 0,
        "total_tokens": total,
    }
