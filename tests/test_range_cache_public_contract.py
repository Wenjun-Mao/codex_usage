from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.aggregation import (
    aggregate_records,
    resolve_range_bounds,
    summarize_records,
)
from codex_usage.report_breakdown import build_report_breakdown
from codex_usage.reporting import (
    render_html_report,
    render_terminal,
    summary_payload,
    write_csv,
)
from codex_usage.session_cache import load_cached_session_data


def test_cached_range_uses_stable_project_key_order_for_tied_report_chart_rows(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(
        sessions / "001-zeta.jsonl",
        session_id="zeta-thread",
        timestamp="2026-08-03T12:00:00Z",
        cwd="/repo/zeta",
        total_tokens=10,
    )
    _write_session(
        sessions / "002-alpha.jsonl",
        session_id="alpha-thread",
        timestamp="2026-08-03T12:00:00Z",
        cwd="/repo/alpha",
        total_tokens=10,
    )
    cache_dir = tmp_path / "cache"
    full = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    ranged = load_cached_session_data(
        [sessions],
        cache_dir=cache_dir,
        auto_transitions=False,
        range_bounds=resolve_range_bounds(
            "today", UTC, datetime(2026, 8, 3, 12, tzinfo=UTC)
        ),
    )

    rows = aggregate_records(ranged.records, "project", UTC)
    assert ranged.records == full.records
    assert [row.key for row in rows] == ["/repo/zeta", "/repo/alpha"]
    assert [row["key"] for row in summary_payload(
        rows=rows,
        total=summarize_records(ranged.records),
        generated_at=datetime(2026, 8, 3, 12, tzinfo=UTC),
        range_name="today",
        group_by="project",
        sessions_dirs=ranged.session_dirs,
        files_scanned=len(ranged.files),
    )["rows"]] == ["/repo/zeta", "/repo/alpha"]

    terminal = render_terminal(
        rows=rows,
        total=summarize_records(ranged.records),
        range_name="today",
        group_by="project",
        files_scanned=len(ranged.files),
    )
    assert terminal.index("zeta") < terminal.index("alpha")
    csv_path = tmp_path / "report.csv"
    write_csv(rows, csv_path)
    assert csv_path.read_text(encoding="utf-8").index("zeta") < csv_path.read_text(encoding="utf-8").index("alpha")

    report_path = tmp_path / "report.html"
    render_html_report(
        output_path=report_path,
        generated_at=datetime(2026, 8, 3, 12, tzinfo=UTC),
        range_name="today",
        total=summarize_records(ranged.records),
        daily_rows=aggregate_records(ranged.records, "day", UTC),
        hourly_rows=aggregate_records(ranged.records, "hour", UTC),
        breakdown=build_report_breakdown(ranged.records),
        sessions_dirs=ranged.session_dirs,
        files_scanned=len(ranged.files),
    )
    html = report_path.read_text(encoding="utf-8")
    assert html.index("alpha") < html.index("zeta")


def test_cached_range_uses_last_parent_identity_by_record_index(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_jsonl(
        sessions / "001-parent.jsonl",
        [
            _metadata("parent-thread", "2026-08-02T12:00:00Z", "/repo/new", "https://github.com/example/newer.git"),
            {"timestamp": "2026-08-02T12:00:00Z", "type": "turn_context", "payload": {"model": "gpt-5.5"}},
            _token("2026-08-02T12:00:00Z", 10),
            _metadata("parent-thread", "2026-08-01T12:00:00Z", "/repo/older", "https://github.com/example/older-index.git"),
            _token("2026-08-01T12:00:00Z", 20),
        ],
    )
    _write_session(
        sessions / "002-child.jsonl",
        session_id="child-thread",
        timestamp="2026-08-03T12:00:00Z",
        cwd="/repo/child",
        total_tokens=50,
        parent_thread_id="parent-thread",
    )
    cache_dir = tmp_path / "cache"
    full = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    ranged = load_cached_session_data(
        [sessions],
        cache_dir=cache_dir,
        auto_transitions=False,
        range_bounds=resolve_range_bounds(
            "today", UTC, datetime(2026, 8, 3, 12, tzinfo=UTC)
        ),
    )

    full_child = next(record for record in full.records if record.session_id == "child-thread")
    assert ranged.records == [full_child]
    assert ranged.records[0].project_key == "https://github.com/example/older-index"


def _write_session(
    path: Path,
    *,
    session_id: str,
    timestamp: str,
    cwd: str,
    total_tokens: int,
    parent_thread_id: str = "",
) -> None:
    metadata = _metadata(session_id, timestamp, cwd)
    if parent_thread_id:
        metadata["payload"]["source"] = {
            "subagent": {"thread_spawn": {"parent_thread_id": parent_thread_id}}
        }
    _write_jsonl(
        path,
        [
            metadata,
            {"timestamp": timestamp, "type": "turn_context", "payload": {"model": "gpt-5.5"}},
            _token(timestamp, total_tokens),
        ],
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def _metadata(session_id: str, timestamp: str, cwd: str, repository_url: str = "") -> dict[str, object]:
    payload: dict[str, object] = {"id": session_id, "timestamp": timestamp, "cwd": cwd}
    if repository_url:
        payload["git"] = {"repository_url": repository_url, "branch": "main"}
    return {"timestamp": timestamp, "type": "session_meta", "payload": payload}


def _token(timestamp: str, total_tokens: int) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": "token_count", "info": {"total_token_usage": {"total_tokens": total_tokens}}},
    }
