from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

import codex_usage.storage_insights as storage_insights
from codex_usage.session_cache import load_cached_session_data
from codex_usage.session_cache_schema import _ensure_schema


def test_storage_metadata_reads_only_new_or_changed_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    first = _write_session(sessions, "first", "/repo/one")
    second = _write_session(sessions, "second", "/repo/two")
    cache_dir = tmp_path / "cache"
    original_read = storage_insights.read_session_metadata_bounded
    reads: list[Path] = []

    def record_read(path: Path):
        reads.append(path)
        return original_read(path)

    monkeypatch.setattr(storage_insights, "read_session_metadata_bounded", record_read)

    cold = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert reads == [first, second]
    assert cold.stats.storage_metadata_reads == 2

    reads.clear()
    warm = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert reads == []
    assert warm.stats.storage_metadata_reads == 0
    assert warm.stats.storage_files_reused == 2

    _append_side_chat_turn(second)
    os.utime(second, None)
    reads.clear()
    changed = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert reads == [second]
    assert changed.stats.storage_metadata_reads == 1


def test_storage_insights_conserve_duplicate_active_and_archived_paths(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    active_path = _write_session(sessions, "root", "/repo/demo")
    archived_path = _write_session(archived, "root", "/repo/demo")

    data = load_cached_session_data(
        [sessions, archived], cache_dir=tmp_path / "cache", auto_transitions=False,
        max_workers=1,
    )
    insights = _require_insights(data)

    assert len(data.files) == 1  # Canonical usage still prefers the active generation.
    assert insights.physical_file_count == 2
    assert insights.corpus_bytes == active_path.stat().st_size + archived_path.stat().st_size
    assert insights.active_bytes == active_path.stat().st_size
    assert insights.archived_bytes == archived_path.stat().st_size
    assert len(insights.task_trees) == 1
    tree = insights.task_trees[0]
    assert tree.root_task_id == "root"
    assert tree.root_bytes == insights.corpus_bytes
    assert tree.descendant_bytes == 0
    assert tree.active_file_count == 1
    assert tree.archived_file_count == 1
    assert tree.has_duplicate_task_id is True
    assert tree.share == 1.0


def test_storage_insights_roll_nested_subagents_into_root(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    root = _write_session(sessions, "root", "/repo/demo")
    child = _write_session(sessions, "child", "/repo/demo", parent_id="root")
    grandchild = _write_session(
        sessions, "grandchild", "/repo/demo", parent_id="child"
    )

    insights = _require_insights(
        load_cached_session_data(
            [sessions], cache_dir=tmp_path / "cache", auto_transitions=False,
            max_workers=1,
        )
    )

    assert insights.corpus_bytes == sum(
        path.stat().st_size for path in (root, child, grandchild)
    )
    assert insights.root_bytes == root.stat().st_size
    assert insights.descendant_bytes == child.stat().st_size + grandchild.stat().st_size
    tree = insights.task_trees[0]
    assert tree.root_task_id == "root"
    assert tree.root_bytes == root.stat().st_size
    assert tree.descendant_bytes == child.stat().st_size + grandchild.stat().st_size
    assert tree.descendant_count == 2
    assert tree.has_missing_root is False
    assert tree.has_relationship_cycle is False


def test_storage_insights_conserve_missing_roots_and_cycles(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    missing = _write_session(sessions, "missing-child", "/repo/missing", parent_id="gone")
    cycle_a = _write_session(sessions, "cycle-a", "/repo/cycle", parent_id="cycle-b")
    cycle_b = _write_session(sessions, "cycle-b", "/repo/cycle", parent_id="cycle-a")

    insights = _require_insights(
        load_cached_session_data(
            [sessions], cache_dir=tmp_path / "cache", auto_transitions=False,
            max_workers=1,
        )
    )

    assert insights.corpus_bytes == sum(
        path.stat().st_size for path in (missing, cycle_a, cycle_b)
    )
    assert insights.root_bytes == 0
    assert insights.descendant_bytes == insights.corpus_bytes
    trees = {tree.root_task_id: tree for tree in insights.task_trees}
    assert trees["missing:gone"].has_missing_root is True
    assert trees["missing:gone"].has_relationship_cycle is False
    assert trees["cycle:cycle-a"].has_relationship_cycle is True
    assert trees["cycle:cycle-a"].has_missing_root is False


def test_storage_insights_exclude_retained_missing_and_filter_projects(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    removed = _write_session(sessions, "removed", "/repo/one")
    preserved = _write_session(archived, "preserved", "/repo/two")
    cache_dir = tmp_path / "cache"
    load_cached_session_data(
        [sessions, archived], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    removed.unlink()

    data = load_cached_session_data(
        [sessions, archived], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    insights = _require_insights(data)
    filtered = insights.filter_projects(["/repo/two"])

    assert data.retained_missing_files == [removed]
    assert insights.corpus_bytes == preserved.stat().st_size
    assert insights.physical_file_count == 1
    assert filtered.corpus_bytes == preserved.stat().st_size
    assert [tree.root_task_id for tree in filtered.task_trees] == ["preserved"]
    assert filtered.task_trees[0].share == 1.0


def test_cached_storage_snapshot_filters_without_reopening_jsonls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    first = _write_session(sessions, "first", "/repo/one")
    second = _write_session(sessions, "second", "/repo/two")
    data = load_cached_session_data(
        [sessions], cache_dir=tmp_path / "cache", auto_transitions=False, max_workers=1
    )
    original_open = Path.open

    def fail_jsonl_open(path: Path, *args: object, **kwargs: object):
        if path in {first, second}:
            raise AssertionError("project filtering must use cached storage metadata")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_jsonl_open)
    snapshot = storage_insights.build_task_storage_snapshot(
        data, project_keys=["/repo/two"]
    )

    assert snapshot.corpus_bytes == second.stat().st_size
    assert [tree.root_task_id for tree in snapshot.task_trees] == ["second"]
    assert snapshot.roots


def test_side_chat_shaped_root_file_is_one_root_storage_row(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    path = _write_session(sessions, "root", "/repo/demo", extra_turns=3)

    insights = _require_insights(
        load_cached_session_data(
            [sessions], cache_dir=tmp_path / "cache", auto_transitions=False,
            max_workers=1,
        )
    )

    assert insights.physical_file_count == 1
    assert len(insights.task_trees) == 1
    tree = insights.task_trees[0]
    assert tree.root_task_id == "root"
    assert tree.root_bytes == path.stat().st_size
    assert tree.descendant_bytes == 0
    assert tree.descendant_count == 0


def test_storage_warning_thresholds_are_inclusive_and_exact(tmp_path: Path) -> None:
    session_dir = tmp_path / "codex" / "sessions"
    session_dir.mkdir(parents=True)
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        _ensure_schema(connection)
        connection.executemany(
            """
            insert into storage_files (
                path, session_dir, storage_state, size_bytes, mtime_ns,
                last_seen_at, is_missing, task_id, parent_task_id, usage_role,
                project_key, project_label, project_aliases_json, metadata_diagnostic
            ) values (?, ?, 'active', ?, 1, 'now', 0, ?, ?, ?, 'project', 'Project', '[]', '')
            """,
            (
                (
                    "/storage/root.jsonl",
                    str(session_dir),
                    1 << 30,
                    "root",
                    "",
                    "root",
                ),
                (
                    "/storage/child.jsonl",
                    str(session_dir),
                    9 << 30,
                    "child",
                    "root",
                    "subagent",
                ),
            ),
        )
        insights = storage_insights.load_task_storage_insights(connection, [session_dir])

    tree = insights.task_trees[0]
    assert tree.root_bytes == 1 << 30
    assert tree.total_bytes == 10 << 30
    assert tree.is_large_root is True
    assert tree.is_large_tree is True


def test_storage_insights_keep_metadata_diagnostics_without_dropping_bytes(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    path = sessions / "2026" / "08" / "07" / "metadata-missing.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_token_count_row(100)) + "\n", encoding="utf-8")

    insights = _require_insights(
        load_cached_session_data(
            [sessions], cache_dir=tmp_path / "cache", auto_transitions=False,
            max_workers=1,
        )
    )

    assert insights.corpus_bytes == path.stat().st_size
    assert insights.task_trees[0].metadata_diagnostics == ("session_meta_missing",)


def _require_insights(data: object) -> storage_insights.TaskStorageInsights:
    value = getattr(data, "storage_insights")
    assert isinstance(value, storage_insights.TaskStorageInsights)
    return value


def _write_session(
    session_dir: Path,
    task_id: str,
    cwd: str,
    *,
    parent_id: str = "",
    extra_turns: int = 0,
) -> Path:
    path = session_dir / "2026" / "08" / "07" / f"{task_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    source: object = "cli"
    if parent_id:
        source = {"subagent": {"thread_spawn": {"parent_thread_id": parent_id}}}
    rows: list[dict[str, object]] = [
        {
            "timestamp": "2026-08-07T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": task_id, "cwd": cwd, "source": source},
        },
        {
            "timestamp": "2026-08-07T12:00:01Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.6-terra"},
        },
        _token_count_row(100),
    ]
    for index in range(extra_turns):
        rows.append(
            {
                "timestamp": f"2026-08-07T12:00:{index + 3:02d}Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": f"side chat turn {index}"},
            }
        )
        rows.append(_token_count_row(110 + index * 10))
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def _append_side_chat_turn(path: Path) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_token_count_row(150)) + "\n")


def _token_count_row(total_tokens: int) -> dict[str, object]:
    return {
        "timestamp": "2026-08-07T12:00:02Z",
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total_tokens - 20,
                    "output_tokens": 20,
                    "total_tokens": total_tokens,
                }
            },
        },
    }
