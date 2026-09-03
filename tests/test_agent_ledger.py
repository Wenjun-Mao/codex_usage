from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import codex_usage.agent_capture as capture_module
import codex_usage.agent_reports as reports_module
from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import render_ledger_report
from codex_usage.agent_rebuild import rebuild_stale_source_slice
from codex_usage.ledger_queries import load_ledger_records, load_ledger_status


def test_capture_populates_durable_ledger_and_reports_without_jsonl_reads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / ".codex"
    path = _write_session(home, "task-1", total=100)

    result = capture_once(home, request_kind="manual", max_workers=1)

    assert result.outcome == "success"
    ledger = ledger_database_path(home)
    assert ledger.is_file()
    with sqlite3.connect(ledger) as connection:
        assert connection.execute("pragma journal_mode").fetchone()[0] == "wal"
        assert connection.execute("select count(*) from ledger_sources").fetchone()[0] == 1
        assert connection.execute("select count(*) from ledger_usage_events").fetchone()[0] == 1
        assert connection.execute("select count(*) from ledger_models").fetchone()[0] == 1

    original_open = Path.open
    original_connect = sqlite3.connect

    def reject_jsonl_open(candidate: Path, *args, **kwargs):
        if candidate.suffix == ".jsonl":
            raise AssertionError(f"report reopened source JSONL: {candidate}")
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_jsonl_open)

    def reject_storage_database(database, *args, **kwargs):
        if "storage-diagnostics.sqlite3" in str(database):
            raise AssertionError("usage report opened Task Storage diagnostics")
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", reject_storage_database)
    report = render_ledger_report(
        home,
        range_name="all",
        project_keys=[],
        theme="night",
        timezone_name="UTC",
    )

    assert "100" in report.html
    assert report.status.coverage.complete
    assert load_ledger_records(ledger)[0].usage.total_tokens == 100
    assert path.exists()


def test_deleted_source_history_remains_in_ledger(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    path = _write_session(home, "task-1", total=120)
    first = capture_once(home, request_kind="startup", max_workers=1)
    path.unlink()

    second = capture_once(home, request_kind="scheduled", max_workers=1)

    assert first.outcome == second.outcome == "success"
    ledger = ledger_database_path(home)
    assert [record.usage.total_tokens for record in load_ledger_records(ledger)] == [120]
    assert load_ledger_status(ledger).coverage.total_sources == 1
    with sqlite3.connect(ledger) as connection:
        assert connection.execute(
            "select is_missing from ledger_sources"
        ).fetchone()[0] == 1


def test_bounded_baseline_coverage_includes_files_not_yet_scheduled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / ".codex"
    paths = [
        _write_session(home, "task-1", total=100),
        _write_session(home, "task-2", total=200),
    ]
    monkeypatch.setattr(capture_module, "CAPTURE_SLICE_BYTES", 128)
    monkeypatch.setattr(capture_module, "CAPTURE_FILE_QUANTUM_BYTES", 128)

    result = capture_once(home, request_kind="startup", max_workers=1)

    coverage = result.status.coverage
    assert result.outcome == "success"
    assert result.stats.files_total == coverage.total_sources == 2
    assert result.stats.files_removed == 0
    assert coverage.total_bytes == sum(path.stat().st_size for path in paths)
    assert coverage.pending_files == result.stats.pending_files
    assert coverage.pending_bytes == result.stats.pending_bytes
    assert coverage.captured_bytes < coverage.total_bytes
    assert coverage.complete is False
    with sqlite3.connect(ledger_database_path(home)) as connection:
        capture = connection.execute(
            "select pending_files, pending_bytes from capture_runs"
        ).fetchone()
    assert capture == (coverage.pending_files, coverage.pending_bytes)


def test_append_preserves_existing_normalized_event_rows(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    path = _write_session(home, "task-1", total=100)
    first = capture_once(home, request_kind="startup", max_workers=1)
    ledger = ledger_database_path(home)
    with sqlite3.connect(ledger) as connection:
        first_event_id = connection.execute(
            "select event_id from ledger_usage_events where source_record_index = 0"
        ).fetchone()[0]

    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "timestamp": "2026-09-02T10:00:03Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 150,
                                "total_tokens": 150,
                            }
                        },
                    },
                }
            )
            + "\n"
        )
    second = capture_once(home, request_kind="scheduled", max_workers=1)

    assert first.outcome == second.outcome == "success"
    with sqlite3.connect(ledger) as connection:
        rows = connection.execute(
            """
            select event_id, source_record_index
            from ledger_usage_events order by source_record_index
            """
        ).fetchall()
    assert rows[0] == (first_event_id, 0)
    assert rows[1][1] == 1
    assert [record.usage.total_tokens for record in load_ledger_records(ledger)] == [
        100,
        50,
    ]


def test_report_uses_one_ledger_snapshot_during_concurrent_capture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / ".codex"
    path = _write_session(home, "task-1", total=100)
    assert capture_once(home, request_kind="startup", max_workers=1).outcome == "success"
    ledger = ledger_database_path(home)
    starting_revision = load_ledger_status(ledger).revision
    observed_totals: list[int] = []
    original_query = reports_module.query_ledger_records
    original_render = reports_module.render_html_report
    advanced = False

    def advance_then_query(connection, **kwargs):
        nonlocal advanced
        if not advanced:
            advanced = True
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "timestamp": "2026-09-02T10:00:03Z",
                            "type": "event_msg",
                            "payload": {
                                "type": "token_count",
                                "info": {
                                    "total_token_usage": {
                                        "input_tokens": 150,
                                        "total_tokens": 150,
                                    }
                                },
                            },
                        }
                    )
                    + "\n"
                )
            assert (
                capture_once(home, request_kind="scheduled", max_workers=1).outcome
                == "success"
            )
        return original_query(connection, **kwargs)

    def observe_render(**kwargs):
        observed_totals.append(kwargs["total"].usage.total_tokens)
        return original_render(**kwargs)

    monkeypatch.setattr(reports_module, "query_ledger_records", advance_then_query)
    monkeypatch.setattr(reports_module, "render_html_report", observe_render)

    first = render_ledger_report(
        home,
        range_name="all",
        project_keys=[],
        theme="night",
        timezone_name="UTC",
    )
    assert first.ledger_revision == starting_revision
    assert observed_totals == [100]
    with sqlite3.connect(ledger) as connection:
        assert connection.execute("select count(*) from rendered_reports").fetchone()[0] == 0

    second = render_ledger_report(
        home,
        range_name="all",
        project_keys=[],
        theme="night",
        timezone_name="UTC",
    )
    assert second.ledger_revision > first.ledger_revision
    assert observed_totals == [100, 150]


def test_guard_failure_retains_trusted_rows_until_staged_rebuild_completes(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    path = _write_session(home, "task-1", total=100)
    assert capture_once(home, request_kind="startup", max_workers=1).outcome == "success"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '"input_tokens": 100', '"input_tokens": 200'
        ).replace('"total_tokens": 100', '"total_tokens": 200'),
        encoding="utf-8",
    )

    stale = capture_once(home, request_kind="scheduled", max_workers=1)

    ledger = ledger_database_path(home)
    assert stale.outcome == "success"
    assert load_ledger_status(ledger).coverage.stale_sources == 1
    assert [record.usage.total_tokens for record in load_ledger_records(ledger)] == [100]

    rebuilt = rebuild_stale_source_slice(home, "task-1", max_bytes=64)
    while not rebuilt.complete:
        rebuilt = rebuild_stale_source_slice(home, "task-1", max_bytes=64)

    assert load_ledger_status(ledger).coverage.stale_sources == 0
    assert [record.usage.total_tokens for record in load_ledger_records(ledger)] == [200]


def _write_session(home: Path, task_id: str, *, total: int) -> Path:
    directory = home / "sessions" / "2026" / "09" / "02"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"rollout-{task_id}.jsonl"
    rows = [
        {
            "timestamp": "2026-09-02T10:00:00Z",
            "type": "session_meta",
            "payload": {"id": task_id, "cwd": str(home.parent / "project")},
        },
        {
            "timestamp": "2026-09-02T10:00:01Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.6-sol"},
        },
        {
            "timestamp": "2026-09-02T10:00:02Z",
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
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path
