import json
import os
from pathlib import Path
from types import SimpleNamespace

import codex_usage.sync.runner as runner_module
import pytest
from codex_usage.session_cache import load_cached_session_data
from codex_usage.sync import ProjectResolutionRequest, pull_sync, push_sync


def test_run_sync_pushes_flat_bytes_and_one_index(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    source = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")

    result = push_sync(
        data=data,
        sync_dir=tmp_path / "sync",
        thread_ids=["thread-1"],
        machine_id="a",
    )

    assert result.outcome == "completed"
    assert result.pushed == ("thread-1",)
    assert (
        tmp_path / "sync" / "tasks" / "thread-1.jsonl"
    ).read_bytes() == source.read_bytes()
    assert (tmp_path / "sync" / "sync-index.json").is_file()
    assert not (tmp_path / "sync" / "threads").exists()


def test_new_task_in_same_project_remains_excluded_after_initial_selection(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "sessions"
    _write_session(sessions, "selected-a", tmp_path / "repo", total=100)
    _write_session(sessions, "selected-b", tmp_path / "repo", total=100)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")

    first = push_sync(
        data=data,
        sync_dir=tmp_path / "sync",
        thread_ids=["selected-a", "selected-b"],
        machine_id="a",
    )

    _write_session(sessions, "future", tmp_path / "repo", total=100)
    refreshed = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    second = push_sync(
        data=refreshed,
        sync_dir=tmp_path / "sync",
        thread_ids=["selected-a", "selected-b"],
        machine_id="a",
    )

    assert set(first.pushed) == {"selected-a", "selected-b"}
    assert second.pushed == ()
    assert not (tmp_path / "sync" / "tasks" / "future.jsonl").exists()


@pytest.fixture
def mixed_direction_fixture(tmp_path: Path) -> SimpleNamespace:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    sync_dir = tmp_path / "sync"
    project = tmp_path / "repo"
    pull_path = _write_session(
        sessions, "pull-thread", project, total=120
    )
    push_path = _write_session(
        sessions, "push-thread", project, total=120
    )
    initial_data = load_cached_session_data(
        [sessions], cache_dir=tmp_path / "cache"
    )
    initial = push_sync(
        data=initial_data,
        sync_dir=sync_dir,
        thread_ids=["pull-thread", "push-thread"],
        machine_id="source",
    )
    assert set(initial.pushed) == {"pull-thread", "push-thread"}

    remote_pull_path = sync_dir / "tasks" / "pull-thread.jsonl"
    remote_push_path = sync_dir / "tasks" / "push-thread.jsonl"
    _append_token_event(remote_pull_path, "2026-07-13T12:01:00Z", 240)
    _append_token_event(push_path, "2026-07-13T12:02:00Z", 240)
    refreshed_data = load_cached_session_data(
        [sessions], cache_dir=tmp_path / "cache"
    )
    baseline_paths = tuple(
        sorted((home / ".codex-sync-state").rglob("*.json"))
    )
    assert len(baseline_paths) == 2
    authoritative_paths = (
        pull_path,
        push_path,
        remote_pull_path,
        remote_push_path,
        sync_dir / "sync-index.json",
        *baseline_paths,
    )

    return SimpleNamespace(
        pull_kwargs={
            "data": refreshed_data,
            "sync_dir": sync_dir,
            "thread_ids": ["pull-thread", "push-thread"],
            "project_resolution": ProjectResolutionRequest(),
        },
        push_kwargs={
            "data": refreshed_data,
            "sync_dir": sync_dir,
            "thread_ids": ["pull-thread", "push-thread"],
            "machine_id": "target",
        },
        snapshots={path: path.read_bytes() for path in authoritative_paths},
    )


def test_pull_opposite_direction_blocker_copies_nothing(
    mixed_direction_fixture: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        runner_module, "execute_pulls", lambda *args: copied.append("pull")
    )

    result = pull_sync(**mixed_direction_fixture.pull_kwargs)

    assert result.outcome == "issue"
    assert result.pulled == ()
    assert copied == []
    assert {issue.code for issue in result.issues} == {"pull_requires_push"}
    assert {
        path: path.read_bytes() for path in mixed_direction_fixture.snapshots
    } == mixed_direction_fixture.snapshots


def test_push_opposite_direction_blocker_copies_nothing(
    mixed_direction_fixture: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        runner_module, "execute_pushes", lambda *args: copied.append("push")
    )

    result = push_sync(**mixed_direction_fixture.push_kwargs)

    assert result.outcome == "issue"
    assert result.pushed == ()
    assert copied == []
    assert {issue.code for issue in result.issues} == {"push_requires_pull"}
    assert {
        path: path.read_bytes() for path in mixed_direction_fixture.snapshots
    } == mixed_direction_fixture.snapshots


def test_remote_task_pull_rebinds_cwd_to_matching_saved_local_project(
    tmp_path: Path,
) -> None:
    repository_url = "https://github.com/example/persona_generators.git"
    source_home = tmp_path / "source-codex"
    source_project = tmp_path / "windows-checkout" / "persona_generators"
    target_home = tmp_path / "target-codex"
    target_project = tmp_path / "mac-checkout" / "persona_generators"
    sync_dir = tmp_path / "sync"
    _write_git_origin(source_project, repository_url)
    _write_git_origin(target_project, repository_url)
    _write_saved_projects(target_home, [target_project])
    source_path = _write_session(
        source_home / "sessions",
        "thread-1",
        source_project,
        total=120,
    )
    source_data = load_cached_session_data(
        [source_home / "sessions"], cache_dir=tmp_path / "source-cache"
    )
    push_sync(
        data=source_data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="source",
    )
    target_data = load_cached_session_data(
        [target_home / "sessions"], cache_dir=tmp_path / "target-cache"
    )

    first = pull_sync(
        data=target_data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        project_resolution=ProjectResolutionRequest(),
    )

    target_path = target_home / "sessions" / source_path.relative_to(source_home / "sessions")
    target_rows = [json.loads(line) for line in target_path.read_text(encoding="utf-8").splitlines()]
    remote_rows = [
        json.loads(line)
        for line in (sync_dir / "tasks" / "thread-1.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert first.outcome == "completed"
    assert first.pulled == ("thread-1",)
    assert target_rows[0]["payload"]["cwd"] == str(target_project)
    assert remote_rows[0]["payload"]["cwd"] == str(source_project)
    assert target_rows[1:] == remote_rows[1:]

    refreshed = load_cached_session_data(
        [target_home / "sessions"], cache_dir=tmp_path / "target-cache"
    )
    second = pull_sync(
        data=refreshed,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        project_resolution=ProjectResolutionRequest(),
    )

    assert second.outcome == "completed"
    assert second.pulled == ()
    assert second.pushed == ()
    assert second.threads[0].state == "synced"


def test_remote_task_pull_requires_a_unique_matching_saved_project(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / "source-codex"
    source_project = tmp_path / "source-project"
    _write_git_origin(source_project, "https://github.com/example/repo.git")
    source_path = _write_session(
        source_home / "sessions", "thread-1", source_project, total=120
    )
    source_data = load_cached_session_data(
        [source_home / "sessions"], cache_dir=tmp_path / "source-cache"
    )
    sync_dir = tmp_path / "sync"
    push_sync(
        data=source_data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="source",
    )
    target_sessions = tmp_path / "target-codex" / "sessions"
    target_data = load_cached_session_data(
        [target_sessions], cache_dir=tmp_path / "target-cache"
    )

    result = pull_sync(
        data=target_data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        project_resolution=ProjectResolutionRequest(),
    )

    assert result.outcome == "issue"
    assert result.issues[-1].code == "missing_local_project"
    assert "Add the project to Codex" in result.issues[-1].message
    assert not (target_sessions / source_path.relative_to(source_home / "sessions")).exists()
    remote_index = json.loads((sync_dir / "sync-index.json").read_text(encoding="utf-8"))
    assert set(remote_index["threads"]) == {"thread-1"}


def test_remote_task_pull_rejects_ambiguous_matching_saved_projects(
    tmp_path: Path,
) -> None:
    repository_url = "https://github.com/example/repo.git"
    source_home = tmp_path / "source-codex"
    source_project = tmp_path / "source-project"
    target_home = tmp_path / "target-codex"
    first_target = tmp_path / "first-target"
    second_target = tmp_path / "second-target"
    for project in (source_project, first_target, second_target):
        _write_git_origin(project, repository_url)
    _write_saved_projects(target_home, [first_target, second_target])
    source_path = _write_session(
        source_home / "sessions", "thread-1", source_project, total=120
    )
    sync_dir = tmp_path / "sync"
    push_sync(
        data=load_cached_session_data(
            [source_home / "sessions"], cache_dir=tmp_path / "source-cache"
        ),
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        project_resolution=ProjectResolutionRequest(),
        machine_id="source",
    )
    target_sessions = target_home / "sessions"

    result = pull_sync(
        data=load_cached_session_data(
            [target_sessions], cache_dir=tmp_path / "target-cache"
        ),
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        project_resolution=ProjectResolutionRequest(),
    )

    assert result.outcome == "issue"
    assert result.issues[-1].code == "ambiguous_local_project"
    assert not (
        target_sessions / source_path.relative_to(source_home / "sessions")
    ).exists()


def test_push_rejects_non_native_existing_project_path_without_rebinding(
    tmp_path: Path,
) -> None:
    repository_url = "https://github.com/example/repo.git"
    source_home = tmp_path / "source-codex"
    target_home = tmp_path / "target-codex"
    source_project = tmp_path / "source-project"
    target_project = tmp_path / "target-project"
    _write_git_origin(source_project, repository_url)
    _write_git_origin(target_project, repository_url)
    _write_saved_projects(target_home, [target_project])
    source_path = _write_session(
        source_home / "sessions", "thread-1", source_project, total=120
    )
    sync_dir = tmp_path / "sync"
    push_sync(
        data=load_cached_session_data(
            [source_home / "sessions"], cache_dir=tmp_path / "source-cache"
        ),
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="source",
    )
    target_sessions = target_home / "sessions"
    pull_sync(
        data=load_cached_session_data(
            [target_sessions], cache_dir=tmp_path / "target-cache"
        ),
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        project_resolution=ProjectResolutionRequest(),
    )
    target_path = target_sessions / source_path.relative_to(source_home / "sessions")
    foreign_cwd = "/foreign/project" if os.name == "nt" else r"D:\Projects\repo"
    _replace_session_cwd(target_path, foreign_cwd)
    _append_token_event(target_path, "2026-07-13T12:03:00Z", 240)

    result = push_sync(
        data=load_cached_session_data(
            [target_sessions], cache_dir=tmp_path / "target-cache"
        ),
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="target",
    )

    assert result.outcome == "issue"
    assert result.issues[-1].code == "existing_project_path_not_native"
    assert result.pushed == ()


def test_conflict_preflight_changes_no_authoritative_files(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    sync_dir = tmp_path / "sync"
    initial = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    push_sync(
        data=initial,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )
    remote_path = sync_dir / "tasks" / "thread-1.jsonl"
    _append_token_event(local_path, "2026-07-13T12:01:00Z", 180)
    _append_token_event(remote_path, "2026-07-13T12:02:00Z", 240)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    local_before = local_path.read_bytes()
    remote_before = remote_path.read_bytes()
    index_before = (sync_dir / "sync-index.json").read_bytes()

    result = pull_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        project_resolution=ProjectResolutionRequest(),
    )

    assert result.outcome == "conflict"
    assert local_path.read_bytes() == local_before
    assert remote_path.read_bytes() == remote_before
    assert (sync_dir / "sync-index.json").read_bytes() == index_before
    conflict_candidates = list(
        (home / ".codex-sync-backups").rglob("remote-conflict-session.jsonl")
    )
    assert len(conflict_candidates) == 1
    assert conflict_candidates[0].read_bytes() == remote_before


def _write_session(sessions_dir: Path, thread_id: str, cwd: Path, total: int) -> Path:
    cwd.mkdir(parents=True, exist_ok=True)
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
