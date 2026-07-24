from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

import codex_usage.sync.planner as planner_module
import codex_usage.sync.runner as runner_module
import pytest

from codex_usage.project_identity import normalize_project_key
from codex_usage.session_cache import load_cached_session_data
from codex_usage.sync.constants import REMOTE_TRANSFER_FORMAT_VERSION
from codex_usage.sync.io import snapshot_file
from codex_usage.sync.models import (
    LocalInventory,
    ProjectBinding,
    ProjectResolutionRequest,
    RemoteIndex,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
)
from codex_usage.sync.planner import build_sync_plan
from codex_usage.sync.project_roots import resolve_local_project_root
from codex_usage.sync.runner import pull_sync, push_sync
from codex_usage.sync.store import RemoteStore
from codex_usage.threads import ThreadInfo


THREAD_ID = "task-1"


def _git_checkout(path: Path, origin: str) -> Path:
    path.mkdir(parents=True)
    git_dir = path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = {origin}\n',
        encoding="utf-8",
    )
    return path


def _remote_entry(
    project_key: str,
    *,
    aliases: tuple[str, ...] = (),
    thread_id: str = THREAD_ID,
) -> RemoteThreadEntry:
    return RemoteThreadEntry(
        thread_id=thread_id,
        file=f"tasks/{thread_id}.jsonl",
        source_relative_path=f"synced/{thread_id}.jsonl",
        index_entry={"id": thread_id},
        project_key=project_key,
        project_label="project",
        project_aliases=aliases,
        sha256="remote-sha",
        size_bytes=100,
        session_updated_at="2026-07-16T12:00:00Z",
        exported_at="2026-07-16T12:00:00Z",
        source_machine_id="source",
    )


def _local_thread(
    cwd: Path | str,
    project_key: str,
    *,
    thread_id: str = THREAD_ID,
    session_path: Path | None = None,
) -> ThreadInfo:
    return ThreadInfo(
        thread_id=thread_id,
        title="Local task",
        updated_at="2026-07-16T12:00:00Z",
        session_path=session_path or Path("sessions") / f"{thread_id}.jsonl",
        project_key=project_key,
        project_label="project",
        project_aliases=(),
        total_tokens=0,
        session_bytes=100,
        estimated_sync_bytes=4196,
        cwd=str(cwd),
    )


def _local_inventory(thread: ThreadInfo | None = None) -> LocalInventory:
    threads = {} if thread is None else {thread.thread_id: thread}
    return LocalInventory(
        session_dirs=(Path("sessions"),),
        threads=threads,
        index_entries={},
        discovered_count=len(threads),
        project_roots={},
    )


def _fallback_request(
    remote_entry: RemoteThreadEntry,
    fallback: Path,
) -> ProjectResolutionRequest:
    return ProjectResolutionRequest(
        candidate_roots=(fallback,),
        bindings=(
            ProjectBinding(
                remote_entry.project_key,
                fallback,
                confirmed_unverified=True,
            ),
        ),
    )


def test_cross_project_transfer_stops_before_project_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    sessions.mkdir(parents=True)
    sync_dir = tmp_path / "transfer"
    tasks = (
        _local_thread(
            tmp_path / "repo-a",
            "repo-a",
            thread_id="task-a",
            session_path=sessions / "task-a.jsonl",
        ),
        _local_thread(
            tmp_path / "repo-b",
            "repo-b",
            thread_id="task-b",
            session_path=sessions / "task-b.jsonl",
        ),
    )
    local = LocalInventory(
        session_dirs=(sessions,),
        threads={task.thread_id: task for task in tasks},
        index_entries={},
        discovered_count=2,
    )
    entries = (
        _remote_entry("repo-a", thread_id="task-a"),
        _remote_entry("repo-b", thread_id="task-b"),
    )
    index = RemoteIndex(
        REMOTE_TRANSFER_FORMAT_VERSION,
        "2026-07-23T12:00:00Z",
        {entry.thread_id: entry for entry in entries},
    )
    remote = RemoteInventory(
        persisted_index=index,
        index=index,
        index_snapshot=SyncFileSnapshot(sync_dir / "sync-index.json", False),
        files={
            entry.thread_id: SyncFileSnapshot(
                sync_dir / entry.file,
                True,
                entry.sha256,
                entry.size_bytes,
            )
            for entry in entries
        },
        repaired_thread_ids=(),
        issues=(),
    )
    resolution_calls: list[str] = []

    monkeypatch.setattr(runner_module, "build_local_inventory", lambda data: local)
    monkeypatch.setattr(RemoteStore, "load_inventory", lambda store: remote)
    monkeypatch.setattr(
        RemoteStore,
        "materialize_selected",
        lambda store, inventory, selected: inventory,
    )
    monkeypatch.setattr(
        planner_module,
        "resolve_local_project_root",
        lambda *args: resolution_calls.append("resolve") or (tmp_path / "repo-a", None),
    )

    result = pull_sync(
        data=object(),
        sync_dir=sync_dir,
        thread_ids=("task-a", "task-b"),
        project_resolution=ProjectResolutionRequest(),
        project_key="repo-a",
    )

    assert result.outcome == "issue"
    assert [issue.code for issue in result.issues] == ["cross_project_selection"]
    assert not sync_dir.exists()
    assert resolution_calls == []


def test_declared_project_mismatch_stops_before_directional_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    sessions.mkdir(parents=True)
    session_path = sessions / "task-a.jsonl"
    session_path.write_bytes(b'{"type":"session_meta"}\n')
    local = LocalInventory(
        session_dirs=(sessions,),
        threads={
            "task-a": _local_thread(
                tmp_path / "repo-a",
                "repo-a",
                thread_id="task-a",
                session_path=session_path,
            )
        },
        index_entries={},
        discovered_count=1,
    )
    execution_calls: list[str] = []

    monkeypatch.setattr(runner_module, "build_local_inventory", lambda data: local)
    monkeypatch.setattr(
        runner_module,
        "execute_pushes",
        lambda *args, **kwargs: execution_calls.append("push"),
    )

    sync_dir = tmp_path / "transfer"
    result = push_sync(
        data=object(),
        sync_dir=sync_dir,
        thread_ids=("task-a",),
        machine_id="machine-a",
        project_key="repo-b",
    )

    assert result.outcome == "issue"
    assert [issue.code for issue in result.issues] == ["project_scope_mismatch"]
    assert not sync_dir.exists()
    assert session_path.read_bytes() == b'{"type":"session_meta"}\n'
    assert execution_calls == []


def test_single_project_export_preserves_unrelated_remote_project_bytes(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    task_a = _write_session(sessions, "task-a", repo_a)
    _write_session(sessions, "task-b", repo_b)
    sync_dir = tmp_path / "transfer"
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")

    push_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=("task-a",),
        machine_id="machine-a",
        project_key=normalize_project_key(str(repo_a)),
    )
    push_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=("task-b",),
        machine_id="machine-a",
        project_key=normalize_project_key(str(repo_b)),
    )
    before_index = json.loads(
        (sync_dir / "sync-index.json").read_text(encoding="utf-8")
    )
    before_task_a = before_index["threads"]["task-a"]
    before_task_b = before_index["threads"]["task-b"]
    task_b_bytes = (sync_dir / "tasks" / "task-b.jsonl").read_bytes()

    with task_a.open("a", encoding="utf-8") as stream:
        stream.write('{"type":"event_msg","payload":{"type":"user_message"}}\n')
    refreshed = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    result = push_sync(
        data=refreshed,
        sync_dir=sync_dir,
        thread_ids=("task-a",),
        machine_id="machine-a",
        project_key=normalize_project_key(str(repo_a)),
    )

    after_index = json.loads(
        (sync_dir / "sync-index.json").read_text(encoding="utf-8")
    )
    assert result.outcome == "completed"
    assert result.pushed == ("task-a",)
    assert after_index["threads"]["task-a"] != before_task_a
    assert after_index["threads"]["task-b"] == before_task_b
    assert (sync_dir / "tasks" / "task-b.jsonl").read_bytes() == task_b_bytes


def test_remote_path_alias_cannot_authorize_wrong_origin_candidate(
    tmp_path: Path,
) -> None:
    wrong_checkout = _git_checkout(
        tmp_path / "wrong-candidate",
        "git@github.com:example/wrong.git",
    )
    remote_entry = _remote_entry(
        "https://github.com/example/right.git",
        aliases=(str(wrong_checkout),),
    )

    root, issue = resolve_local_project_root(
        _local_inventory(),
        None,
        remote_entry,
        ProjectResolutionRequest(candidate_roots=(wrong_checkout,)),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "missing_local_project"


def test_remote_path_alias_cannot_authorize_wrong_origin_binding(
    tmp_path: Path,
) -> None:
    wrong_checkout = _git_checkout(
        tmp_path / "wrong-binding",
        "git@github.com:example/wrong.git",
    )
    remote_entry = _remote_entry(
        "https://github.com/example/right.git",
        aliases=(str(wrong_checkout),),
    )

    root, issue = resolve_local_project_root(
        _local_inventory(),
        None,
        remote_entry,
        ProjectResolutionRequest(
            bindings=(
                ProjectBinding(
                    project_key=remote_entry.project_key,
                    path=wrong_checkout,
                ),
            ),
        ),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "project_binding_identity_mismatch"


def test_git_shaped_alias_cannot_authorize_non_git_candidate(
    tmp_path: Path,
) -> None:
    checkout = _git_checkout(
        tmp_path / "alias-candidate",
        "git@github.com:example/alias-only.git",
    )
    remote_entry = _remote_entry(
        "c:/remote-machine/project",
        aliases=("https://github.com/example/alias-only.git",),
    )

    root, issue = resolve_local_project_root(
        _local_inventory(),
        None,
        remote_entry,
        ProjectResolutionRequest(candidate_roots=(checkout,)),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "missing_local_project"


def test_git_shaped_alias_cannot_bypass_non_git_binding_confirmation(
    tmp_path: Path,
) -> None:
    checkout = _git_checkout(
        tmp_path / "alias-binding",
        "git@github.com:example/alias-only.git",
    )
    remote_entry = _remote_entry(
        "c:/remote-machine/project",
        aliases=("https://github.com/example/alias-only.git",),
    )

    root, issue = resolve_local_project_root(
        _local_inventory(),
        None,
        remote_entry,
        ProjectResolutionRequest(
            bindings=(ProjectBinding(remote_entry.project_key, checkout),),
        ),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "unverified_project_binding_confirmation_required"


def test_existing_counterpart_precedes_non_overlapping_project_metadata_and_binding(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "native-local-root"
    bound_root = tmp_path / "bound-root"
    local_root.mkdir()
    bound_root.mkdir()
    local_thread = _local_thread(local_root, "d:/local-machine/project")
    remote_entry = _remote_entry("c:/remote-machine/project")

    root, issue = resolve_local_project_root(
        _local_inventory(local_thread),
        local_thread,
        remote_entry,
        ProjectResolutionRequest(
            bindings=(
                ProjectBinding(
                    project_key=remote_entry.project_key,
                    path=bound_root,
                    confirmed_unverified=True,
                ),
            ),
        ),
    )

    assert root == local_root
    assert issue is None


def test_existing_counterpart_preserves_exact_symlink_cwd_spelling(
    tmp_path: Path,
) -> None:
    actual_root = tmp_path / "actual-root"
    linked_root = tmp_path / "linked-root"
    actual_root.mkdir()
    try:
        linked_root.symlink_to(actual_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    local_thread = _local_thread(linked_root, "shared-project-key")

    root, issue = resolve_local_project_root(
        _local_inventory(local_thread),
        local_thread,
        _remote_entry("shared-project-key"),
        ProjectResolutionRequest(),
    )

    assert root == linked_root
    assert str(root) == str(linked_root)
    assert issue is None


def test_existing_local_counterpart_with_missing_cwd_is_rejected(
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing-project"
    local_thread = _local_thread(
        missing_root,
        "https://github.com/example/project",
    )

    root, issue = resolve_local_project_root(
        _local_inventory(local_thread),
        local_thread,
        _remote_entry("https://github.com/example/project"),
        ProjectResolutionRequest(),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "existing_project_path_missing"
    assert str(missing_root) in issue.message


def test_existing_local_counterpart_with_file_cwd_is_rejected(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "project.txt"
    file_path.write_text("not a directory", encoding="utf-8")
    local_thread = _local_thread(
        file_path,
        "https://github.com/example/project",
    )

    root, issue = resolve_local_project_root(
        _local_inventory(local_thread),
        local_thread,
        _remote_entry("https://github.com/example/project"),
        ProjectResolutionRequest(),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "existing_project_path_not_directory"
    assert str(file_path) in issue.message


@pytest.mark.parametrize("cwd", ["", "   "])
def test_existing_local_counterpart_with_blank_cwd_never_uses_fallbacks(
    tmp_path: Path,
    cwd: str,
) -> None:
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    remote_entry = _remote_entry("source-project")
    local_thread = _local_thread(cwd, remote_entry.project_key)

    root, issue = resolve_local_project_root(
        _local_inventory(local_thread),
        local_thread,
        remote_entry,
        _fallback_request(remote_entry, fallback),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "existing_project_path_blank"


def test_existing_local_counterpart_with_relative_cwd_never_uses_fallbacks(
    tmp_path: Path,
) -> None:
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    remote_entry = _remote_entry("source-project")
    local_thread = _local_thread("relative/project", remote_entry.project_key)

    root, issue = resolve_local_project_root(
        _local_inventory(local_thread),
        local_thread,
        remote_entry,
        _fallback_request(remote_entry, fallback),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "existing_project_path_not_absolute"


def test_existing_local_counterpart_with_foreign_cwd_never_uses_fallbacks(
    tmp_path: Path,
) -> None:
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    remote_entry = _remote_entry("source-project")
    foreign_cwd = "/foreign/project" if os.name == "nt" else r"C:\foreign\project"
    local_thread = _local_thread(foreign_cwd, remote_entry.project_key)

    root, issue = resolve_local_project_root(
        _local_inventory(local_thread),
        local_thread,
        remote_entry,
        _fallback_request(remote_entry, fallback),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "existing_project_path_not_native"


def test_blank_existing_cwd_blocks_mixed_import_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    sessions.mkdir(parents=True)
    sync_dir = tmp_path / "transfer"
    tasks_dir = sync_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    remote_only_root = tmp_path / "remote-only-root"
    remote_only_root.mkdir()

    existing_id = "existing-task"
    remote_only_id = "remote-only-task"
    local_path = sessions / f"{existing_id}.jsonl"
    existing_remote_path = tasks_dir / f"{existing_id}.jsonl"
    remote_only_path = tasks_dir / f"{remote_only_id}.jsonl"
    local_path.write_bytes(b"matching existing task\n")
    existing_remote_path.write_bytes(local_path.read_bytes())
    remote_only_path.write_bytes(b"remote-only task\n")

    existing_snapshot = snapshot_file(existing_remote_path)
    remote_only_snapshot = snapshot_file(remote_only_path)
    existing_entry = replace(
        _remote_entry("existing-project", thread_id=existing_id),
        source_relative_path=f"{existing_id}.jsonl",
        sha256=existing_snapshot.sha256,
        size_bytes=existing_snapshot.size_bytes,
    )
    remote_only_entry = replace(
        _remote_entry(existing_entry.project_key, thread_id=remote_only_id),
        source_relative_path=f"{remote_only_id}.jsonl",
        sha256=remote_only_snapshot.sha256,
        size_bytes=remote_only_snapshot.size_bytes,
    )
    index = RemoteIndex(
        REMOTE_TRANSFER_FORMAT_VERSION,
        "2026-07-16T12:00:00Z",
        {existing_id: existing_entry, remote_only_id: remote_only_entry},
    )
    remote = RemoteInventory(
        persisted_index=index,
        index=index,
        index_snapshot=SyncFileSnapshot(sync_dir / "sync-index.json", False),
        files={existing_id: existing_snapshot, remote_only_id: remote_only_snapshot},
        repaired_thread_ids=(),
        issues=(),
    )
    existing_thread = _local_thread(
        "",
        existing_entry.project_key,
        thread_id=existing_id,
        session_path=local_path,
    )
    local = LocalInventory(
        session_dirs=(sessions,),
        threads={existing_id: existing_thread},
        index_entries={},
        discovered_count=1,
    )
    request = ProjectResolutionRequest(
        bindings=(
            ProjectBinding(existing_entry.project_key, remote_only_root, True),
        ),
    )
    selected = (existing_id, remote_only_id)
    plan = build_sync_plan(
        local,
        remote,
        selected,
        sync_dir,
        project_resolution=request,
    )
    execution_calls: list[str] = []

    monkeypatch.setattr(runner_module, "build_local_inventory", lambda data: local)
    monkeypatch.setattr(
        runner_module,
        "prepare_direction_plan",
        lambda *args, **kwargs: (remote, plan, ()),
    )
    monkeypatch.setattr(RemoteStore, "validate_selected", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner_module,
        "repair_matching_bookkeeping",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        runner_module,
        "execute_pulls",
        lambda *args, **kwargs: execution_calls.append("pull") or (),
    )

    result = pull_sync(
        data=object(),
        sync_dir=sync_dir,
        thread_ids=selected,
        project_resolution=request,
        project_key=existing_entry.project_key,
    )

    assert result.outcome == "issue"
    assert result.pulled == ()
    assert {issue.code for issue in result.issues} == {"existing_project_path_blank"}
    assert execution_calls == []


def _write_session(sessions: Path, thread_id: str, cwd: Path) -> Path:
    day = sessions / "2026" / "07" / "23"
    day.mkdir(parents=True, exist_ok=True)
    session_path = day / f"{thread_id}.jsonl"
    session_path.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-23T12:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": thread_id,
                    "timestamp": "2026-07-23T12:00:00Z",
                    "cwd": str(cwd),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return session_path
