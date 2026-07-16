import inspect
import json
from pathlib import Path

import codex_usage.sync.runner as runner_module
import pytest
from codex_usage.session_cache import load_cached_session_data
from codex_usage.sync import ProjectResolutionRequest, pull_sync, push_sync
from codex_usage.sync.runner import sync_status as transaction_status
from codex_usage.sync.store import RemoteStore

def test_conflict_result_includes_completed_planning_timing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    sync_dir = tmp_path / "sync"
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    push_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )
    _append_token_event(local_path, "2026-07-13T12:01:00Z", 180)
    _append_token_event(
        sync_dir / "tasks" / "thread-1.jsonl", "2026-07-13T12:02:00Z", 240
    )
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    clock = iter((1_000_000, 3_000_000, 4_000_000, 9_000_000))
    monkeypatch.setattr(runner_module, "perf_counter_ns", lambda: next(clock))

    result = pull_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        project_resolution=ProjectResolutionRequest(),
    )

    assert result.timings_ms.planning == 7


def test_runner_public_interfaces_are_keyword_only(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")

    with pytest.raises(TypeError):
        push_sync(data, tmp_path / "sync", ["thread-1"], "a")
    with pytest.raises(TypeError):
        transaction_status(data, tmp_path / "sync", ["thread-1"])
    assert (
        inspect.signature(pull_sync).parameters["project_resolution"].default
        is inspect.Parameter.empty
    )
    assert (
        inspect.signature(transaction_status)
        .parameters["project_resolution"]
        .default
        is inspect.Parameter.empty
    )


def test_pull_backs_up_local_and_merges_remote_session_index(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    sync_dir = tmp_path / "sync"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    original_index = {
        "id": "thread-1",
        "thread_name": "Original",
        "updated_at": "2026-04-29T10:05:00Z",
    }
    _write_index(home, original_index)
    initial = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    push_sync(
        data=initial,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )
    remote_path = sync_dir / "tasks" / "thread-1.jsonl"
    _append_token_event(remote_path, "2026-07-13T12:02:00Z", 240)
    before_pull = local_path.read_bytes()
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")

    result = pull_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        project_resolution=ProjectResolutionRequest(),
    )

    assert result.pulled == ("thread-1",)
    assert local_path.read_bytes() == remote_path.read_bytes()
    local_backups = list((home / ".codex-sync-backups").rglob("thread-1/session.jsonl"))
    index_backups = list((home / ".codex-sync-backups").rglob("session_index.jsonl"))
    assert len(local_backups) == 1
    assert local_backups[0].read_bytes() == before_pull
    assert len(index_backups) == 1
    assert json.loads(index_backups[0].read_text(encoding="utf-8")) == original_index
    merged_entries = [
        json.loads(line)
        for line in (home / "session_index.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert merged_entries == [original_index]


def test_pull_rejects_mismatched_remote_index_identity_before_local_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_sessions = tmp_path / "source" / "sessions"
    target_sessions = tmp_path / "target" / "sessions"
    sync_dir = tmp_path / "sync"
    project = tmp_path / "repo"
    project.mkdir()
    _write_saved_projects(target_sessions.parent, [project])
    source_path = _write_session(
        source_sessions,
        "task-a",
        project,
        total=120,
    )
    source_data = load_cached_session_data(
        [source_sessions], cache_dir=tmp_path / "source-cache"
    )
    push_sync(
        data=source_data,
        sync_dir=sync_dir,
        thread_ids=["task-a"],
        machine_id="source",
    )
    target_data = load_cached_session_data(
        [target_sessions], cache_dir=tmp_path / "target-cache"
    )
    original_validate = RemoteStore.validate_selected

    def corrupt_nested_identity_after_validation(
        self: RemoteStore,
        expected_entries,
        expected_files,
    ) -> None:
        original_validate(self, expected_entries, expected_files)
        entry = expected_entries["task-a"]
        assert entry is not None
        entry.index_entry["id"] = "task-b"

    monkeypatch.setattr(
        RemoteStore,
        "validate_selected",
        corrupt_nested_identity_after_validation,
    )
    target_path = target_sessions / source_path.relative_to(source_sessions)

    with pytest.raises(ValueError, match=r"index_entry\.id.*match"):
        pull_sync(
            data=target_data,
            sync_dir=sync_dir,
            thread_ids=["task-a"],
            project_resolution=ProjectResolutionRequest(),
        )

    assert not target_path.exists()
    assert not (target_sessions.parent / "session_index.jsonl").exists()
    assert not (target_sessions.parent / ".codex-sync-state").exists()


def test_pull_preflights_all_remote_identities_before_batch_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_sessions = tmp_path / "source" / "sessions"
    target_sessions = tmp_path / "target" / "sessions"
    sync_dir = tmp_path / "sync"
    project = tmp_path / "repo"
    project.mkdir()
    _write_saved_projects(target_sessions.parent, [project])
    source_paths = {
        thread_id: _write_session(
            source_sessions,
            thread_id,
            project,
            total=120,
        )
        for thread_id in ("task-a", "task-b")
    }
    source_data = load_cached_session_data(
        [source_sessions], cache_dir=tmp_path / "source-cache"
    )
    push_sync(
        data=source_data,
        sync_dir=sync_dir,
        thread_ids=["task-a", "task-b"],
        machine_id="source",
    )
    target_data = load_cached_session_data(
        [target_sessions], cache_dir=tmp_path / "target-cache"
    )
    original_validate = RemoteStore.validate_selected

    def corrupt_second_identity_after_validation(
        self: RemoteStore,
        expected_entries,
        expected_files,
    ) -> None:
        original_validate(self, expected_entries, expected_files)
        second_entry = expected_entries["task-b"]
        assert second_entry is not None
        second_entry.index_entry["id"] = "different-task"

    monkeypatch.setattr(
        RemoteStore,
        "validate_selected",
        corrupt_second_identity_after_validation,
    )

    with pytest.raises(ValueError, match=r"index_entry\.id.*match"):
        pull_sync(
            data=target_data,
            sync_dir=sync_dir,
            thread_ids=["task-a", "task-b"],
            project_resolution=ProjectResolutionRequest(),
        )

    for source_path in source_paths.values():
        target_path = target_sessions / source_path.relative_to(source_sessions)
        assert not target_path.exists()
    assert not (target_sessions.parent / "session_index.jsonl").exists()
    assert not (target_sessions.parent / ".codex-sync-state").exists()
    assert not (target_sessions.parent / ".codex-sync-backups").exists()


def test_run_sync_returns_typed_issue_when_local_changes_after_planning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    original_validate = RemoteStore.validate_selected

    def change_local_after_planning(self, expected_entries, expected_files) -> None:
        original_validate(self, expected_entries, expected_files)
        _append_token_event(local_path, "2026-07-13T12:03:00Z", 180)

    monkeypatch.setattr(RemoteStore, "validate_selected", change_local_after_planning)

    result = push_sync(
        data=data,
        sync_dir=tmp_path / "sync",
        thread_ids=["thread-1"],
        machine_id="a",
    )

    assert result.outcome == "issue"
    assert result.pushed == ()
    assert result.issues[-1].code == "concurrent_local_change"
    assert not (tmp_path / "sync" / "tasks" / "thread-1.jsonl").exists()


def test_run_sync_returns_typed_issue_for_visible_remote_change(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    sync_dir = tmp_path / "sync"
    initial = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    push_sync(
        data=initial,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )
    _append_token_event(local_path, "2026-07-13T12:03:00Z", 180)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    remote_path = sync_dir / "tasks" / "thread-1.jsonl"
    original_validate = runner_module.validate_local_selected

    def change_remote_after_planning(plan) -> None:
        original_validate(plan)
        _append_token_event(remote_path, "2026-07-13T12:04:00Z", 240)

    monkeypatch.setattr(
        runner_module, "validate_local_selected", change_remote_after_planning
    )

    result = push_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )

    assert result.outcome == "issue"
    assert result.pushed == ()
    assert result.issues[-1].code == "concurrent_remote_change"


def _write_session(sessions_dir: Path, thread_id: str, cwd: Path, total: int) -> Path:
    day_dir = sessions_dir / "2026" / "04" / "29"
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"rollout-2026-04-29T10-00-00-{thread_id}.jsonl"
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
        {
            "timestamp": "2026-04-29T10:00:01Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.5"},
        },
        _token_count_event("2026-04-29T10:00:02Z", total),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _write_git_origin(project: Path, repository_url: str) -> None:
    git_dir = project / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = {repository_url}\n',
        encoding="utf-8",
    )


def _write_saved_projects(codex_home: Path, projects: list[Path]) -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / ".codex-global-state.json").write_text(
        json.dumps({"electron-saved-workspace-roots": [str(project) for project in projects]}),
        encoding="utf-8",
    )


def _append_token_event(path: Path, timestamp: str, total: int) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps(_token_count_event(timestamp, total)))


def _replace_session_cwd(path: Path, cwd: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    metadata = json.loads(lines[0])
    metadata["payload"]["cwd"] = cwd
    lines[0] = json.dumps(metadata)
    path.write_text("\n".join(lines), encoding="utf-8")


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
