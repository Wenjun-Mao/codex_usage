from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

import codex_usage.storage_analysis as storage_analysis
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data
from codex_usage.storage_analysis import (
    StorageAnalysisRequest,
    analyze_storage_request,
    analyze_storage_tree,
)
from codex_usage.storage_context import load_storage_context


def test_explicit_analysis_measures_large_compacted_rows(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    path = _write_root(sessions)
    compacted = _compacted_row("data:image/png;base64,abc", padding=2_000_000)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(compacted) + "\n")
    result = analyze_storage_tree(
        "root", session_dirs=[sessions], cache_dir=tmp_path / "cache", max_workers=1
    )
    metrics = result.diagnostics[0].metrics

    assert metrics.compacted_record_count == 1
    assert metrics.compacted_bytes > 2_000_000
    assert metrics.media_compacted_record_count == 1
    assert metrics.embedded_media_occurrence_count == 1


def test_selected_tree_analysis_reuses_warm_result_and_appends_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    path = _write_root(sessions)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {"type": "message", "text": "z" * 400_000},
                }
            )
            + "\n"
        )
        handle.write(json.dumps(_compacted_row("data:image/png;base64,one")) + "\n")
    cache_dir = tmp_path / "cache"

    first = analyze_storage_tree(
        "root",
        session_dirs=[sessions],
        cache_dir=cache_dir,
        max_workers=1,
    )
    assert first.full_scans == 1
    assert first.diagnostics[0].metrics.compacted_record_count == 1

    original_open = Path.open

    def reject_jsonl_open(self: Path, *args: object, **kwargs: object):
        if self == path:
            raise AssertionError("unchanged analysis reopened the task JSONL")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_jsonl_open)
    warm = analyze_storage_tree(
        "root",
        session_dirs=[sessions],
        cache_dir=cache_dir,
        max_workers=1,
    )
    assert warm.files_unchanged == 1
    assert warm.source_bytes_read == 0
    monkeypatch.setattr(Path, "open", original_open)

    before_size = path.stat().st_size
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_compacted_row("plain text")) + "\n")
    appended = analyze_storage_tree(
        "root",
        session_dirs=[sessions],
        cache_dir=cache_dir,
        max_workers=1,
    )
    assert appended.files_appended == 1
    assert appended.diagnostics[0].metrics.compacted_record_count == 2
    assert appended.source_bytes_read < before_size

    snapshot = load_storage_context(
        session_dirs=[sessions], cache_dir=cache_dir
    ).insights.task_trees[0]
    assert snapshot.analysis_status == "complete"
    assert snapshot.analysis_coverage == 1.0


def test_usage_capture_does_not_overwrite_explicit_content_diagnostics(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    path = _write_root(sessions)
    cache_dir = tmp_path / "cache"
    analyzed = analyze_storage_tree(
        "root", session_dirs=[sessions], cache_dir=cache_dir, max_workers=1
    )
    assert analyzed.diagnostics[0].metrics.compacted_record_count == 0
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_compacted_row("plain text")) + "\n")

    refreshed = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    tree = refreshed.storage_insights.task_trees[0]

    assert refreshed.stats.files_full_parsed == 1
    assert tree.analysis_status == "partial"
    assert tree.compacted_record_count == 0

    updated = analyze_storage_tree(
        "root", session_dirs=[sessions], cache_dir=cache_dir, max_workers=1
    )
    assert updated.diagnostics[0].metrics.compacted_record_count == 1


def test_guard_change_forces_full_content_rescan(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    path = _write_root(sessions)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_compacted_row("first")) + "\n")
    cache_dir = tmp_path / "cache"
    analyze_storage_tree(
        "root", session_dirs=[sessions], cache_dir=cache_dir, max_workers=1
    )

    contents = path.read_bytes()
    path.write_bytes(contents.replace(b'"timestamp":', b'"timestamq":', 1))
    with path.open("ab") as handle:
        handle.write(json.dumps(_compacted_row("second")).encode() + b"\n")

    result = analyze_storage_tree(
        "root", session_dirs=[sessions], cache_dir=cache_dir, max_workers=1
    )

    assert result.append_fallbacks == 1
    assert result.diagnostics[0].metrics.compacted_record_count == 2


def test_misleading_media_text_outside_compacted_row_is_not_counted(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    path = _write_root(sessions)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "timestamp": "2026-08-08T10:00:01Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": 'literal "image_url":"data:image/png;base64,nope"',
                    },
                }
            )
            + "\n"
        )
    result = analyze_storage_tree(
        "root", session_dirs=[sessions], cache_dir=tmp_path / "cache", max_workers=1
    )
    metrics = result.diagnostics[0].metrics

    assert metrics.compacted_record_count == 0
    assert metrics.embedded_media_occurrence_count == 0


def test_terminated_unclassified_row_keeps_analysis_honest(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    path = _write_root(sessions)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not-json}\n")

    result = analyze_storage_tree(
        "root", session_dirs=[sessions], cache_dir=tmp_path / "cache", max_workers=1
    )
    metrics = result.diagnostics[0].metrics

    assert metrics.unclassified_record_count == 1
    assert metrics.complete is False


def test_partial_final_row_is_deferred_until_terminated(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    path = _write_root(sessions)
    cache_dir = tmp_path / "cache"
    first = analyze_storage_tree(
        "root", session_dirs=[sessions], cache_dir=cache_dir, max_workers=1
    )
    original_offset = first.diagnostics[0].analyzed_offset
    encoded = json.dumps(_compacted_row("plain text")).encode()
    with path.open("ab") as handle:
        handle.write(encoded)

    deferred = analyze_storage_tree(
        "root", session_dirs=[sessions], cache_dir=cache_dir, max_workers=1
    )
    assert deferred.diagnostics[0].analyzed_offset == original_offset
    assert deferred.diagnostics[0].metrics.compacted_record_count == 0
    assert load_storage_context(
        session_dirs=[sessions], cache_dir=cache_dir
    ).insights.task_trees[0].analysis_status == "partial"

    with path.open("ab") as handle:
        handle.write(b"\n")
    completed = analyze_storage_tree(
        "root", session_dirs=[sessions], cache_dir=cache_dir, max_workers=1
    )
    assert completed.files_appended == 1
    assert completed.diagnostics[0].analyzed_offset == path.stat().st_size
    assert completed.diagnostics[0].metrics.compacted_record_count == 1


def test_analysis_is_selected_tree_only_and_archives_never_append(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    selected = _write_root(sessions, task_id="selected", cwd="/repo/selected")
    _write_root(sessions, task_id="other", cwd="/repo/other")
    archived_path = _write_root(
        archived, task_id="archived", cwd="/repo/archived"
    )
    cache_dir = tmp_path / "cache"

    result = analyze_storage_tree(
        "selected", session_dirs=[sessions, archived], cache_dir=cache_dir, max_workers=1
    )
    assert [item.path for item in result.diagnostics] == [str(selected)]
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        assert connection.execute(
            "select path from storage_content_diagnostics order by path"
        ).fetchall() == [(str(selected),)]

    analyze_storage_tree(
        "archived", session_dirs=[sessions, archived], cache_dir=cache_dir, max_workers=1
    )
    with archived_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_compacted_row("plain text")) + "\n")
    rescanned = analyze_storage_tree(
        "archived", session_dirs=[sessions, archived], cache_dir=cache_dir, max_workers=1
    )
    assert rescanned.full_scans == 1
    assert rescanned.files_appended == 0


def test_failed_analysis_transaction_keeps_previous_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    path = _write_root(sessions)
    cache_dir = tmp_path / "cache"
    analyze_storage_tree(
        "root", session_dirs=[sessions], cache_dir=cache_dir, max_workers=1
    )
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        before = connection.execute(
            "select * from storage_content_diagnostics"
        ).fetchall()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_compacted_row("plain text")) + "\n")

    def fail_store(*_args: object, **_kwargs: object) -> None:
        raise sqlite3.OperationalError("simulated commit failure")

    monkeypatch.setattr(storage_analysis, "upsert_content_diagnostic", fail_store)
    with pytest.raises(sqlite3.OperationalError, match="simulated commit failure"):
        analyze_storage_tree(
            "root", session_dirs=[sessions], cache_dir=cache_dir, max_workers=1
        )
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        assert connection.execute(
            "select * from storage_content_diagnostics"
        ).fetchall() == before


def test_unavailable_file_identity_forces_repeat_full_scans(tmp_path: Path) -> None:
    path = _write_root(tmp_path)
    stat = path.stat()
    request = StorageAnalysisRequest(
        ordinal=0,
        path=path,
        task_id="root",
        storage_state="active",
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        source_device=0,
        source_inode=0,
        existing=None,
    )

    first = analyze_storage_request(request)
    second = analyze_storage_request(replace(request, existing=first.diagnostic))

    assert first.error == second.error == ""
    assert first.outcome == second.outcome == "full"


def _write_root(
    root: Path,
    *,
    task_id: str = "root",
    cwd: str = "/repo/demo",
) -> Path:
    path = root / "2026" / "08" / "08" / f"{task_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-08-08T10:00:00Z",
                "type": "session_meta",
                "payload": {"id": task_id, "cwd": cwd},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _compacted_row(media: str, *, padding: int = 0) -> dict[str, object]:
    return {
        "timestamp": "2026-08-08T10:00:02Z",
        "type": "compacted",
        "payload": {
            "replacement_history": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_image", "image_url": media},
                        {"type": "input_text", "text": "x" * padding},
                    ],
                }
            ]
        },
    }
