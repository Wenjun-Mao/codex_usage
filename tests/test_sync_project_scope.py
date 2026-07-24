from __future__ import annotations

from pathlib import Path

from codex_usage.sync.constants import REMOTE_TRANSFER_FORMAT_VERSION
from codex_usage.sync.models import (
    LocalInventory,
    RemoteIndex,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
)
from codex_usage.sync.project_scope import transfer_project_scope_issues
from codex_usage.threads import ThreadInfo


def local_inventory(*tasks: ThreadInfo) -> LocalInventory:
    return LocalInventory(
        session_dirs=(Path("sessions"),),
        threads={task.thread_id: task for task in tasks},
        index_entries={},
        discovered_count=len(tasks),
    )


def remote_inventory(*tasks: RemoteThreadEntry) -> RemoteInventory:
    index = RemoteIndex(
        format_version=REMOTE_TRANSFER_FORMAT_VERSION,
        updated_at="",
        threads={task.thread_id: task for task in tasks},
    )
    files = {
        task.thread_id: SyncFileSnapshot(
            path=Path("sync") / task.file,
            exists=True,
            sha256=task.sha256,
            size_bytes=task.size_bytes,
        )
        for task in tasks
    }
    return RemoteInventory(
        persisted_index=index,
        index=index,
        index_snapshot=SyncFileSnapshot(None, False),
        files=files,
        repaired_thread_ids=(),
        issues=(),
    )


def empty_remote_inventory() -> RemoteInventory:
    return remote_inventory()


def task(
    thread_id: str,
    *,
    project_key: str,
    project_aliases: tuple[str, ...] = (),
) -> ThreadInfo:
    return ThreadInfo(
        thread_id=thread_id,
        title=thread_id,
        updated_at="2026-07-23T12:00:00Z",
        session_path=Path("sessions") / f"{thread_id}.jsonl",
        project_key=project_key,
        project_label=project_key,
        project_aliases=project_aliases,
        total_tokens=0,
        session_bytes=100,
        estimated_sync_bytes=4196,
    )


def remote_task(
    thread_id: str,
    *,
    project_key: str,
    project_aliases: tuple[str, ...] = (),
) -> RemoteThreadEntry:
    return RemoteThreadEntry(
        thread_id=thread_id,
        file=f"tasks/{thread_id}.jsonl",
        source_relative_path=f"2026/07/23/{thread_id}.jsonl",
        index_entry={"id": thread_id},
        project_key=project_key,
        project_label=project_key,
        project_aliases=project_aliases,
        sha256=f"sha-{thread_id}",
        size_bytes=100,
        session_updated_at="2026-07-23T12:00:00Z",
        exported_at="2026-07-23T12:00:00Z",
        source_machine_id="machine-a",
    )


def test_one_matching_project_has_no_scope_issue() -> None:
    issues = transfer_project_scope_issues(
        local=local_inventory(task("task-1", project_key="repo-a")),
        remote=empty_remote_inventory(),
        thread_ids=("task-1",),
        expected_project_key="repo-a",
    )

    assert issues == ()


def test_cross_project_selection_is_rejected() -> None:
    issues = transfer_project_scope_issues(
        local=local_inventory(
            task("task-1", project_key="repo-a"),
            task("task-2", project_key="repo-b"),
        ),
        remote=empty_remote_inventory(),
        thread_ids=("task-1", "task-2"),
        expected_project_key="repo-a",
    )

    assert [issue.code for issue in issues] == ["cross_project_selection"]
    assert "one project at a time" in issues[0].message


def test_mixed_known_and_unknown_selection_is_rejected() -> None:
    issues = transfer_project_scope_issues(
        local=local_inventory(task("task-1", project_key="repo-a")),
        remote=empty_remote_inventory(),
        thread_ids=("task-1", "unknown"),
        expected_project_key="repo-a",
    )

    assert [issue.code for issue in issues] == ["unresolved_selected_task"]
    assert issues[0].thread_id == "unknown"


def test_declared_project_must_match_selected_project() -> None:
    issues = transfer_project_scope_issues(
        local=local_inventory(task("task-1", project_key="repo-a")),
        remote=empty_remote_inventory(),
        thread_ids=("task-1",),
        expected_project_key="repo-b",
    )

    assert [issue.code for issue in issues] == ["project_scope_mismatch"]


def test_matching_local_and_remote_aliases_use_remote_picker_key() -> None:
    issues = transfer_project_scope_issues(
        local=local_inventory(
            task(
                "task-1",
                project_key="/old/path",
                project_aliases=("https://github.com/example/repo",),
            )
        ),
        remote=remote_inventory(
            remote_task(
                "task-1",
                project_key="https://github.com/example/repo",
                project_aliases=("/old/path",),
            )
        ),
        thread_ids=("task-1",),
        expected_project_key="https://github.com/example/repo",
    )

    assert issues == ()
