from __future__ import annotations

import hashlib
import json
import ntpath
import os
from dataclasses import replace
from pathlib import Path

import pytest

import codex_usage.sync.state as sync_state
from codex_usage.sync.constants import (
    LOCAL_BASELINE_STATE_VERSION,
    REMOTE_TRANSFER_FORMAT_VERSION,
    TRANSFER_TASKS_DIRNAME,
)
from codex_usage.sync.io import snapshot_file
from codex_usage.sync.errors import ConcurrentLocalChangeError
from codex_usage.sync.models import (
    LocalSyncState,
    SyncFileSnapshot,
    SyncIssue,
    SyncPlan,
    SyncPlanItem,
)
from codex_usage.sync.state import (
    LocalStateStore,
    backup_local_session,
    merge_session_index,
    save_conflict_candidate,
    sync_dir_fingerprint,
)


def _snapshot_bytes(tmp_path: Path, name: str, value: bytes | None) -> SyncFileSnapshot:
    path = tmp_path / name
    if value is None:
        return SyncFileSnapshot(path=path, exists=False)
    path.write_bytes(value)
    return snapshot_file(path)


def _plan_item(tmp_path: Path, *, state: str = "synced", action: str = "none") -> SyncPlanItem:
    missing = SyncFileSnapshot(path=tmp_path / "missing.jsonl", exists=False)
    return SyncPlanItem(
        thread_id="thread-1",
        state=state,
        action=action,
        reason="test",
        local=missing,
        remote=missing,
        base_sha256="",
        updated_at="2026-07-13T12:00:00Z",
        source_relative_path="synced/thread-1.jsonl",
        project_key="repo",
        project_label="Repo",
        memory_database_rows=0,
        expected_remote_entry=None,
    )


@pytest.mark.parametrize(
    ("state", "action"),
    [("issue", "push"), ("synced", "issue")],
)
def test_sync_plan_requires_issue_state_and_action_together(
    tmp_path: Path,
    state: str,
    action: str,
) -> None:
    item = _plan_item(tmp_path, state=state, action=action)

    with pytest.raises(ValueError, match="state and action must both be 'issue'"):
        SyncPlan(
            items=(item,),
            issues=(SyncIssue("test", "test", item.thread_id),),
            discovered_count=1,
            remote_count=0,
            selected_count=1,
        )


def test_sync_plan_has_one_selected_execution_gate(tmp_path: Path) -> None:
    diagnostic = SyncIssue("warning", "visible but unselected", "other")
    clear = SyncPlan((_plan_item(tmp_path),), (diagnostic,), 1, 0, 1)
    conflict = SyncPlan((_plan_item(tmp_path, state="conflict", action="conflict"),), (), 1, 0, 1)
    issue_item = _plan_item(tmp_path, state="issue", action="issue")
    issue = SyncPlan((issue_item,), (SyncIssue("test", "selected", "thread-1"),), 1, 0, 1)

    assert clear.has_issues
    assert not clear.blocks_execution
    assert conflict.blocks_execution
    assert issue.blocks_execution
    assert not hasattr(clear, "has_blocking_issues")


def _local_state(sync_dir: Path, thread_id: str = "thread-1") -> LocalSyncState:
    return LocalSyncState(
        thread_id=thread_id,
        sync_dir_fingerprint=sync_dir_fingerprint(sync_dir),
        base_sha256="abc",
        base_size_bytes=3,
        base_updated_at="2026-07-13T12:00:00Z",
        last_remote_sha256="abc",
        last_local_sha256="abc",
        source_relative_path=f"synced/{thread_id}.jsonl",
        project_key="repo",
        project_label="repo",
        synced_at="2026-07-13T12:00:01Z",
    )


def test_remote_format_v3_does_not_invalidate_local_v2_baseline() -> None:
    state = LocalSyncState(
        thread_id="task-1",
        sync_dir_fingerprint="folder",
        base_sha256="base",
        base_size_bytes=10,
        base_updated_at="2026-07-15T00:00:00Z",
        last_remote_sha256="remote",
        last_local_sha256="local",
        source_relative_path="2026/07/15/task-1.jsonl",
        project_key="repo",
        project_label="Repo",
        synced_at="2026-07-15T00:00:00Z",
    )

    assert REMOTE_TRANSFER_FORMAT_VERSION == 3
    assert LOCAL_BASELINE_STATE_VERSION == 2
    assert TRANSFER_TASKS_DIRNAME == "tasks"
    assert state.to_dict()["sync_version"] == 2
    assert LocalSyncState.from_dict(state.to_dict()) == state


def test_local_state_store_namespaces_records_by_sync_folder(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    first_sync = tmp_path / "first-sync"
    second_sync = tmp_path / "second-sync"
    first_store = LocalStateStore(sessions, first_sync)
    second_store = LocalStateStore(sessions, second_sync)
    state = _local_state(first_sync)

    first_store.write(state)

    assert first_store.read("thread-1") == state
    assert second_store.read("thread-1") is None
    assert first_store.path_for("thread-1") != second_store.path_for("thread-1")
    with pytest.raises(ValueError, match="different sync folder"):
        second_store.write(state)


@pytest.mark.skipif(os.name != "posix", reason="POSIX path case contract")
def test_sync_dir_fingerprint_preserves_posix_path_case(tmp_path: Path) -> None:
    assert sync_dir_fingerprint(tmp_path / "CodexSync") != sync_dir_fingerprint(
        tmp_path / "codexsync"
    )


def test_sync_dir_fingerprint_normalizes_windows_path_case() -> None:
    assert sync_state._fingerprint_resolved_sync_dir(
        r"C:\Users\Example\CodexSync",
        ntpath.normcase,
    ) == sync_state._fingerprint_resolved_sync_dir(
        r"c:\users\example\codexsync",
        ntpath.normcase,
    )


def test_local_sync_state_requires_exact_v2_version(tmp_path: Path) -> None:
    state = _local_state(tmp_path / "sync")
    valid = state.to_dict()

    assert LocalSyncState.from_dict(valid) == state
    for version in (None, 1, 3):
        payload = dict(valid)
        if version is None:
            payload.pop("sync_version")
        else:
            payload["sync_version"] = version
        assert LocalSyncState.from_dict(payload) is None


def test_local_state_store_rejects_record_for_different_requested_thread(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    sync_dir = tmp_path / "sync"
    store = LocalStateStore(sessions, sync_dir)
    path = store.path_for("requested")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_local_state(sync_dir, "other").to_dict()))

    assert store.read("requested") is None


@pytest.mark.parametrize(
    ("local_value", "remote_value", "expected_base"),
    [(b"local", b"remote", b"local"), (None, b"remote", b"remote")],
)
def test_local_state_store_record_success_persists_fields_and_selects_base(
    tmp_path: Path,
    local_value: bytes | None,
    remote_value: bytes | None,
    expected_base: bytes,
) -> None:
    sync_dir = tmp_path / "sync"
    store = LocalStateStore(tmp_path / "codex" / "sessions", sync_dir)
    local = _snapshot_bytes(tmp_path, "local-state.jsonl", local_value)
    remote = _snapshot_bytes(tmp_path, "remote-state.jsonl", remote_value)
    item = replace(
        _plan_item(tmp_path),
        local=local,
        remote=remote,
        updated_at="2026-07-13T15:00:00Z",
        source_relative_path="2026/07/13/thread-1.jsonl",
        project_key="project-key",
        project_label="Project Label",
    )

    store.record_success(item, local, remote)

    state = store.read("thread-1")
    assert state is not None
    assert state.sync_dir_fingerprint == sync_dir_fingerprint(sync_dir)
    assert state.base_sha256 == hashlib.sha256(expected_base).hexdigest()
    assert state.base_size_bytes == len(expected_base)
    assert state.base_updated_at == "2026-07-13T15:00:00Z"
    assert state.last_local_sha256 == local.sha256
    assert state.last_remote_sha256 == remote.sha256
    assert state.source_relative_path == "2026/07/13/thread-1.jsonl"
    assert state.project_key == "project-key"
    assert state.project_label == "Project Label"
    assert state.synced_at


def test_local_state_store_requires_a_task_snapshot(tmp_path: Path) -> None:
    missing = SyncFileSnapshot(path=tmp_path / "missing.jsonl", exists=False)
    item = replace(_plan_item(tmp_path), local=missing, remote=missing)
    store = LocalStateStore(tmp_path / "codex" / "sessions", tmp_path / "sync")

    with pytest.raises(
        ValueError,
        match="Successful sync state requires a local or remote task snapshot",
    ):
        store.record_success(item, missing, missing)


def test_local_state_store_ignores_malformed_base_record(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    store = LocalStateStore(sessions, tmp_path / "sync")
    store.path_for("thread-1").parent.mkdir(parents=True)
    store.path_for("thread-1").write_text(
        json.dumps(
            {
                "sync_version": 2,
                "thread_id": "thread-1",
                "sync_dir_fingerprint": sync_dir_fingerprint(tmp_path / "sync"),
                "base_sha256": "abc",
                "base_size_bytes": "not-an-integer",
            }
        )
    )

    assert store.read("thread-1") is None


def test_local_backup_and_conflict_candidate_preserve_original_bytes(tmp_path: Path) -> None:
    local_path = tmp_path / "sessions" / "local.jsonl"
    remote_path = tmp_path / "sync" / "tasks" / "remote.jsonl"
    local_path.parent.mkdir(parents=True)
    remote_path.parent.mkdir(parents=True)
    local_path.write_bytes(b"local before replace")
    remote_path.write_bytes(b"remote conflict")
    backup_dir = tmp_path / "backups" / "run"

    local_backup = backup_local_session(local_path, backup_dir, "thread/unsafe")
    conflict_backup = save_conflict_candidate(remote_path, backup_dir, "thread/unsafe")
    local_path.write_bytes(b"local after replace")

    assert local_backup.read_bytes() == b"local before replace"
    assert conflict_backup.read_bytes() == b"remote conflict"
    assert backup_dir in local_backup.parents
    assert backup_dir in conflict_backup.parents


def test_session_index_merge_keeps_newest_entry_and_backs_up_original(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    index_path = tmp_path / "codex" / "session_index.jsonl"
    index_path.parent.mkdir(parents=True)
    original = {"id": "thread-1", "thread_name": "old", "updated_at": "2026-07-13T10:00:00Z"}
    newer = {"id": "thread-1", "thread_name": "new", "updated_at": "2026-07-13T12:00:00Z"}
    other = {"id": "thread-2", "thread_name": "other", "updated_at": "2026-07-13T11:00:00Z"}
    original_bytes = (json.dumps(original) + "\n").encode()
    index_path.write_bytes(original_bytes)
    backup_dir = tmp_path / "backups" / "run"

    merge_session_index(sessions, [newer, other], backup_dir)

    rows = [json.loads(line) for line in index_path.read_text().splitlines()]
    assert rows == [other, newer]
    assert (backup_dir / "session_index.jsonl").read_bytes() == original_bytes


def test_session_index_merge_preserves_concurrent_codex_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    index_path = tmp_path / "codex" / "session_index.jsonl"
    index_path.parent.mkdir(parents=True)
    original = {
        "id": "thread-1",
        "thread_name": "original",
        "updated_at": "2026-07-13T10:00:00Z",
    }
    pulled = {
        "id": "thread-2",
        "thread_name": "pulled",
        "updated_at": "2026-07-13T11:00:00Z",
    }
    concurrent = {
        "id": "thread-3",
        "thread_name": "created by Codex",
        "updated_at": "2026-07-13T12:00:00Z",
    }
    index_path.write_text(json.dumps(original) + "\n", encoding="utf-8")
    original_atomic_write = sync_state.atomic_write_text

    def write_after_concurrent_update(path: Path, value: str, **kwargs: object):
        path.write_text(json.dumps(concurrent) + "\n", encoding="utf-8")
        return original_atomic_write(path, value, **kwargs)

    monkeypatch.setattr(sync_state, "atomic_write_text", write_after_concurrent_update)

    with pytest.raises(ConcurrentLocalChangeError, match="local session index changed"):
        merge_session_index(sessions, [pulled], tmp_path / "backups" / "run")

    assert index_path.read_text(encoding="utf-8") == json.dumps(concurrent) + "\n"
