import json
import sqlite3
from pathlib import Path

from codex_usage.sync import (
    export_threads,
    import_threads,
    list_threads,
    sync_status,
)


def test_list_threads_filters_by_project_key_and_returns_titles(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    project = tmp_path / "repo"
    _write_git_config(project, "https://github.com/example/demo.git")
    session_path = _write_session(sessions, "thread-1", project, total=120)
    _write_session(sessions, "thread-2", tmp_path / "other", total=75)
    _write_index(codex_home, {"id": "thread-1", "thread_name": "Demo thread", "updated_at": "2026-04-29T10:05:00Z"})

    threads = list_threads([sessions], project_keys=["https://github.com/example/demo"])

    assert [thread.thread_id for thread in threads] == ["thread-1"]
    assert threads[0].title == "Demo thread"
    assert threads[0].project_key == "https://github.com/example/demo"
    assert threads[0].total_tokens == 120
    assert threads[0].session_path == session_path


def test_list_threads_filters_by_transition_target_project(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    old_repo = tmp_path / "signoz-stack"
    new_repo = tmp_path / "ops-board"
    _write_git_config(new_repo, "https://github.com/example/ops-board.git")
    day = sessions / "2026" / "05" / "23"
    day.mkdir(parents=True)
    path = day / "rollout-2026-05-23T17-00-00-thread-1.jsonl"
    rows = [
        {
            "timestamp": "2026-05-23T21:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "thread-1",
                "timestamp": "2026-05-23T21:00:00Z",
                "cwd": str(old_repo),
                "git": {"repository_url": "https://github.com/example/signoz-stack.git"},
                "memory_mode": "enabled",
                "base_instructions": {"text": "instructions"},
            },
        },
        {"timestamp": "2026-05-23T21:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.5"}},
        _token_count_event("2026-05-23T21:00:02Z", 100),
        {
            "timestamp": "2026-05-23T21:06:45Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "arguments": json.dumps({"workdir": str(new_repo), "command": "Get-Location"}),
            },
        },
        _token_count_event("2026-05-23T21:06:46Z", 300),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    _write_index(codex_home, {"id": "thread-1", "thread_name": "Ops thread", "updated_at": "2026-05-23T21:07:00Z"})

    threads = list_threads([sessions], project_keys=["https://github.com/example/ops-board"])

    assert [thread.thread_id for thread in threads] == ["thread-1"]
    assert threads[0].title == "Ops thread"
    assert threads[0].project_key == "https://github.com/example/ops-board"
    assert "https://github.com/example/signoz-stack" in threads[0].project_aliases
    assert threads[0].total_tokens == 300
    assert threads[0].session_path == path


def test_list_threads_normalizes_raw_path_project_filter_for_metadata_fallback(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    project = tmp_path / "Repo With Spaces"
    _write_git_config(project, "https://github.com/example/demo.git")
    session_path = _write_metadata_only_session(sessions, "thread-1", project)

    threads = list_threads([sessions], project_keys=[str(project)])

    assert [thread.thread_id for thread in threads] == ["thread-1"]
    assert threads[0].project_key == "https://github.com/example/demo"
    assert threads[0].total_tokens == 0
    assert threads[0].session_path == session_path


def test_export_and_import_selected_thread_with_index_backup_and_conflict(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    target_home = tmp_path / "target"
    sync_dir = tmp_path / "sync"
    source_sessions = source_home / "sessions"
    target_sessions = target_home / "sessions"
    source_project = tmp_path / "source-repo"
    target_project = tmp_path / "target-repo"
    _write_git_config(source_project, "git@github.com:example/demo.git")
    _write_git_config(target_project, "https://github.com/example/demo.git")
    _write_session(source_sessions, "thread-1", source_project, total=120)
    _write_session(source_sessions, "thread-2", tmp_path / "other", total=75)
    local_target_path = _write_session(target_sessions, "thread-1", target_project, total=40)
    _write_index(source_home, {"id": "thread-1", "thread_name": "Remote newer", "updated_at": "2026-04-29T10:05:00Z"})
    _write_index(target_home, {"id": "thread-1", "thread_name": "Local older", "updated_at": "2026-04-29T09:00:00Z"})

    export_result = export_threads(
        session_dirs=[source_sessions],
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="source-machine",
    )

    thread_dir = sync_dir / "threads" / "thread-1"
    assert export_result.exported == ["thread-1"]
    assert (thread_dir / "manifest.json").is_file()
    assert (thread_dir / "session.jsonl").is_file()
    assert not (sync_dir / "threads" / "thread-2").exists()

    local_target_path.write_text(local_target_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    conflict_status = sync_status(session_dirs=[target_sessions], sync_dir=sync_dir, thread_ids=["thread-1"])
    assert conflict_status.threads[0]["state"] == "conflict"

    import_result = import_threads(
        session_dirs=[target_sessions],
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        conflict_policy="remote",
        backup_label="test-backup",
    )

    assert import_result.imported == ["thread-1"]
    assert import_result.backup_dir is not None
    assert (import_result.backup_dir / "thread-1" / "session.jsonl").is_file()
    assert "Remote newer" in (target_home / "session_index.jsonl").read_text(encoding="utf-8")
    assert _line_count(target_sessions.rglob("*.jsonl")) == 1


def test_import_thread_conflicts_with_existing_thread_at_different_path(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    target_home = tmp_path / "target"
    sync_dir = tmp_path / "sync"
    source_sessions = source_home / "sessions"
    target_sessions = target_home / "sessions"
    existing_path = _write_session(target_sessions, "thread-1", tmp_path / "local-repo", total=40, day=("2026", "05", "01"))
    _write_session(source_sessions, "thread-1", tmp_path / "remote-repo", total=120, day=("2026", "04", "29"))
    _write_index(source_home, {"id": "thread-1", "thread_name": "Remote", "updated_at": "2026-04-29T10:05:00Z"})

    export_threads(
        session_dirs=[source_sessions],
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="source-machine",
    )
    manifest_target = target_sessions / "2026" / "04" / "29" / "rollout-2026-04-29T10-00-00-thread-1.jsonl"

    import_result = import_threads(
        session_dirs=[target_sessions],
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        conflict_policy="skip",
        backup_label="duplicate-skip",
    )

    assert import_result.imported == []
    assert import_result.conflicts == ["thread-1"]
    assert import_result.backup_dir is not None
    assert (import_result.backup_dir / "thread-1" / "remote-conflict-session.jsonl").is_file()
    assert existing_path.is_file()
    assert not manifest_target.exists()
    assert _line_count(target_sessions.rglob("*.jsonl")) == 1


def test_import_thread_remote_overwrites_existing_thread_at_different_path(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    target_home = tmp_path / "target"
    sync_dir = tmp_path / "sync"
    source_sessions = source_home / "sessions"
    target_sessions = target_home / "sessions"
    existing_path = _write_session(target_sessions, "thread-1", tmp_path / "local-repo", total=40, day=("2026", "05", "01"))
    _write_session(source_sessions, "thread-1", tmp_path / "remote-repo", total=120, day=("2026", "04", "29"))
    _write_index(source_home, {"id": "thread-1", "thread_name": "Remote", "updated_at": "2026-04-29T10:05:00Z"})

    export_threads(
        session_dirs=[source_sessions],
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="source-machine",
    )
    manifest_target = target_sessions / "2026" / "04" / "29" / "rollout-2026-04-29T10-00-00-thread-1.jsonl"

    import_result = import_threads(
        session_dirs=[target_sessions],
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        conflict_policy="remote",
        backup_label="duplicate-remote",
    )

    assert import_result.imported == ["thread-1"]
    assert import_result.conflicts == []
    assert import_result.backup_dir is not None
    assert (import_result.backup_dir / "thread-1" / "session.jsonl").is_file()
    assert "remote-repo" in existing_path.read_text(encoding="utf-8")
    assert not manifest_target.exists()
    assert _line_count(target_sessions.rglob("*.jsonl")) == 1


def test_import_thread_rejects_manifest_path_traversal(tmp_path: Path) -> None:
    target_home = tmp_path / "target"
    target_sessions = target_home / "sessions"
    sync_dir = tmp_path / "sync"
    _write_remote_thread(sync_dir, "thread-1", "../outside.jsonl")

    import_result = import_threads(
        session_dirs=[target_sessions],
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        conflict_policy="remote",
    )

    assert import_result.imported == []
    assert import_result.skipped == ["thread-1"]
    assert not (target_home / "outside.jsonl").exists()
    assert not any(target_sessions.rglob("*.jsonl"))


def test_sync_status_reports_memory_database_rows_without_syncing_sqlite(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    sync_dir = tmp_path / "sync"
    _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    _write_index(codex_home, {"id": "thread-1", "thread_name": "Demo", "updated_at": "2026-04-29T10:05:00Z"})
    _write_memory_db(codex_home / "state_5.sqlite", "thread-1")

    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="source-machine")
    status = sync_status(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])

    assert status.threads[0]["memory_database_rows"] == 1
    assert status.threads[0]["memory_note"] == "memory database rows detected, not synced by this beta"
    assert not (sync_dir / "state_5.sqlite").exists()


def _write_session(
    sessions_dir: Path,
    thread_id: str,
    cwd: Path,
    total: int,
    *,
    day: tuple[str, str, str] = ("2026", "04", "29"),
) -> Path:
    year, month, day_number = day
    day_dir = sessions_dir / year / month / day_number
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"rollout-{year}-{month}-{day_number}T10-00-00-{thread_id}.jsonl"
    rows = [
        {
            "timestamp": "2026-04-29T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": thread_id,
                "timestamp": "2026-04-29T10:00:00Z",
                "cwd": str(cwd),
                "memory_mode": "enabled",
                "base_instructions": {"text": "instructions"},
            },
        },
        {"timestamp": "2026-04-29T10:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.5"}},
        {
            "timestamp": "2026-04-29T10:00:02Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": total,
                        "cached_input_tokens": 0,
                        "output_tokens": 0,
                        "reasoning_output_tokens": 0,
                        "total_tokens": total,
                    }
                },
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _write_metadata_only_session(sessions_dir: Path, thread_id: str, cwd: Path) -> Path:
    day = sessions_dir / "2026" / "04" / "29"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-2026-04-29T10-00-00-{thread_id}.jsonl"
    rows = [
        {
            "timestamp": "2026-04-29T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": thread_id,
                "timestamp": "2026-04-29T10:00:00Z",
                "cwd": str(cwd),
            },
        }
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _write_remote_thread(sync_dir: Path, thread_id: str, relative_path: str) -> None:
    thread_dir = sync_dir / "threads" / thread_id
    thread_dir.mkdir(parents=True, exist_ok=True)
    _write_session_jsonl(thread_dir / "session.jsonl", thread_id, Path("remote-repo"), 120)
    _write_json(thread_dir / "manifest.json", {"thread_id": thread_id, "source_relative_path": relative_path})


def _write_session_jsonl(path: Path, thread_id: str, cwd: Path, total: int) -> None:
    rows = [
        {
            "timestamp": "2026-04-29T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": thread_id,
                "timestamp": "2026-04-29T10:00:00Z",
                "cwd": str(cwd),
            },
        },
        {"timestamp": "2026-04-29T10:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.5"}},
        _token_count_event("2026-04-29T10:00:02Z", total),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _token_count_event(timestamp: str, total: int) -> dict[str, object]:
    usage = {
        "input_tokens": total,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": total,
    }
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": "token_count", "info": {"total_token_usage": usage}},
    }


def _write_index(codex_home: Path, entry: dict[str, str]) -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    with (codex_home / "session_index.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def _write_git_config(repo: Path, url: str) -> None:
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(f'[remote "origin"]\n\turl = {url}\n', encoding="utf-8")


def _write_memory_db(path: Path, thread_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.execute("create table stage1_outputs (thread_id text, raw_memory text, rollout_summary text)")
        con.execute("insert into stage1_outputs values (?, ?, ?)", (thread_id, "memory", "summary"))
        con.commit()
    finally:
        con.close()


def _line_count(paths) -> int:
    return sum(1 for _ in paths)
