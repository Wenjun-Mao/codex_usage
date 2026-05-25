import json
import sqlite3
from pathlib import Path

import codex_usage.sync as sync_module
from codex_usage.sync import (
    export_threads,
    import_threads,
    list_threads,
    plan_sync,
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
    expected_session_bytes = session_path.stat().st_size
    assert threads[0].session_bytes == expected_session_bytes
    assert threads[0].estimated_sync_bytes == expected_session_bytes + 4096
    assert threads[0].to_dict()["session_bytes"] == expected_session_bytes
    assert threads[0].to_dict()["estimated_sync_bytes"] == expected_session_bytes + 4096


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


def test_import_thread_does_not_replace_identical_existing_session(tmp_path: Path, monkeypatch) -> None:
    source_home = tmp_path / "source"
    target_home = tmp_path / "target"
    sync_dir = tmp_path / "sync"
    source_sessions = source_home / "sessions"
    target_sessions = target_home / "sessions"
    project = tmp_path / "repo"
    _write_session(source_sessions, "thread-1", project, total=120)
    _write_session(target_sessions, "thread-1", project, total=120)
    _write_index(source_home, {"id": "thread-1", "thread_name": "Remote", "updated_at": "2026-04-29T10:05:00Z"})

    export_threads(
        session_dirs=[source_sessions],
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="source-machine",
    )

    def fail_if_session_copy_is_attempted(source: Path, target: Path) -> None:
        raise AssertionError(f"identical session should not be replaced: {source} -> {target}")

    monkeypatch.setattr(sync_module, "_atomic_copy", fail_if_session_copy_is_attempted)

    import_result = import_threads(
        session_dirs=[target_sessions],
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        conflict_policy="skip",
        backup_label="identical-noop",
    )

    assert import_result.imported == ["thread-1"]
    assert import_result.conflicts == []


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


def test_plan_sync_handles_first_sync_local_and_remote_only(tmp_path: Path) -> None:
    local_home = tmp_path / "local"
    remote_home = tmp_path / "remote"
    sync_dir = tmp_path / "sync"
    local_sessions = local_home / "sessions"
    remote_sessions = remote_home / "sessions"
    _write_session(local_sessions, "local-thread", tmp_path / "repo", total=120)
    _write_session(remote_sessions, "remote-thread", tmp_path / "repo", total=220)

    export_threads(
        session_dirs=[remote_sessions],
        sync_dir=sync_dir,
        thread_ids=["remote-thread"],
        machine_id="remote-machine",
    )

    plan = plan_sync(
        session_dirs=[local_sessions],
        sync_dir=sync_dir,
        thread_ids=["local-thread", "remote-thread"],
    )
    rows = {item["thread_id"]: item for item in plan.threads}

    assert rows["local-thread"]["state"] == "local_only"
    assert rows["local-thread"]["action"] == "push"
    assert rows["remote-thread"]["state"] == "remote_only"
    assert rows["remote-thread"]["action"] == "pull"


def test_plan_sync_uses_base_state_for_local_ahead_and_remote_ahead(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sync_dir = tmp_path / "sync"
    sessions = home / "sessions"
    session_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)

    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="machine-a")
    synced = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])
    assert synced.threads[0]["state"] == "synced"

    _append_token_event(session_path, "2026-04-29T10:00:03Z", 180)
    local_ahead = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])
    assert local_ahead.threads[0]["state"] == "local_ahead"
    assert local_ahead.threads[0]["action"] == "push"

    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="machine-a")
    remote_path = sync_dir / "threads" / "thread-1" / "session.jsonl"
    _append_token_event(remote_path, "2026-04-29T10:00:04Z", 240)
    remote_ahead = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])

    assert remote_ahead.threads[0]["state"] == "remote_ahead"
    assert remote_ahead.threads[0]["action"] == "pull"


def test_plan_sync_fast_forwards_prefix_changes_and_stops_on_divergence(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sync_dir = tmp_path / "sync"
    sessions = home / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)

    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="machine-a")
    remote_path = sync_dir / "threads" / "thread-1" / "session.jsonl"

    _append_token_event(local_path, "2026-04-29T10:00:03Z", 180)
    fast_push = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])
    assert fast_push.threads[0]["state"] == "local_ahead"
    assert fast_push.threads[0]["action"] == "push"

    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="machine-a")
    local_path.write_bytes(remote_path.read_bytes())
    _append_token_event(remote_path, "2026-04-29T10:00:04Z", 240)
    fast_pull = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])
    assert fast_pull.threads[0]["state"] == "remote_ahead"
    assert fast_pull.threads[0]["action"] == "pull"

    _append_token_event(local_path, "2026-04-29T10:00:05Z", 300)
    _append_token_event(remote_path, "2026-04-29T10:00:06Z", 360)
    conflict = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])

    assert conflict.threads[0]["state"] == "conflict"
    assert conflict.threads[0]["action"] == "conflict"
    assert "diverged" in str(conflict.threads[0]["reason"])


def test_plan_sync_without_base_state_uses_prefix_fallback(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sync_dir = tmp_path / "sync"
    sessions = home / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)

    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="machine-a")
    state_root = home / ".codex-sync-state"
    if state_root.exists():
        import shutil

        shutil.rmtree(state_root)
    _append_token_event(local_path, "2026-04-29T10:00:03Z", 180)

    plan = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])

    assert plan.threads[0]["state"] == "fast_forward_push"
    assert plan.threads[0]["action"] == "push"


def test_export_writes_sync_state_and_extended_manifest(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sync_dir = tmp_path / "sync"
    sessions = home / "sessions"
    session_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)

    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="machine-a")

    manifest = json.loads((sync_dir / "threads" / "thread-1" / "manifest.json").read_text(encoding="utf-8"))
    status = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"]).threads[0]

    assert manifest["session_size_bytes"] == session_path.stat().st_size
    assert status["state"] == "synced"
    assert status["base_sha256"] == status["local_sha256"] == status["remote_sha256"]


def test_import_fast_forward_pull_updates_local_and_state(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    target_home = tmp_path / "target"
    sync_dir = tmp_path / "sync"
    source_sessions = source_home / "sessions"
    target_sessions = target_home / "sessions"
    source_path = _write_session(source_sessions, "thread-1", tmp_path / "repo", total=120)
    export_threads(session_dirs=[source_sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="source")
    target_path = _copy_remote_session_to_local(sync_dir, target_sessions, "thread-1")
    export_threads(session_dirs=[target_sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="target")

    _append_token_event(source_path, "2026-04-29T10:00:03Z", 220)
    export_threads(session_dirs=[source_sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="source")

    before = plan_sync(session_dirs=[target_sessions], sync_dir=sync_dir, thread_ids=["thread-1"]).threads[0]
    assert before["state"] == "remote_ahead"
    result = import_threads(session_dirs=[target_sessions], sync_dir=sync_dir, thread_ids=["thread-1"])
    after = plan_sync(session_dirs=[target_sessions], sync_dir=sync_dir, thread_ids=["thread-1"]).threads[0]

    assert result.imported == ["thread-1"]
    assert result.conflicts == []
    assert target_path.read_bytes() == (sync_dir / "threads" / "thread-1" / "session.jsonl").read_bytes()
    assert after["state"] == "synced"


def test_import_true_conflict_preserves_local_and_saves_remote_candidate(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sync_dir = tmp_path / "sync"
    sessions = home / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="machine-a")
    remote_path = sync_dir / "threads" / "thread-1" / "session.jsonl"

    _append_token_event(local_path, "2026-04-29T10:00:03Z", 180)
    local_before = local_path.read_bytes()
    _append_token_event(remote_path, "2026-04-29T10:00:04Z", 240)

    result = import_threads(
        session_dirs=[sessions],
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        backup_label="true-conflict",
    )

    assert result.imported == []
    assert result.conflicts == ["thread-1"]
    assert local_path.read_bytes() == local_before
    assert result.backup_dir is not None
    assert (result.backup_dir / "thread-1" / "remote-conflict-session.jsonl").is_file()


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


def _append_token_event(path: Path, timestamp: str, total: int) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps(_token_count_event(timestamp, total)))


def _copy_remote_session_to_local(sync_dir: Path, sessions_dir: Path, thread_id: str) -> Path:
    manifest = json.loads((sync_dir / "threads" / thread_id / "manifest.json").read_text(encoding="utf-8"))
    relative_path = str(manifest["source_relative_path"])
    target = sessions_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((sync_dir / "threads" / thread_id / "session.jsonl").read_bytes())
    return target


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
