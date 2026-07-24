from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

import codex_usage.sync.runner as runner_module
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
from codex_usage.sync.runner import pull_sync
from codex_usage.sync.store import RemoteStore
from codex_usage.threads import ThreadInfo


THREAD_ID = "task-1"


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
        "probe_direction_scope",
        lambda *args, **kwargs: (remote, plan, ()),
    )
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
    assert {issue.code for issue in result.issues} == {
        "existing_project_path_blank"
    }
    assert execution_calls == []
