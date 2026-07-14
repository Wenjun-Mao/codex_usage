from __future__ import annotations

import errno
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from codex_usage.sync.constants import SYNC_FORMAT_VERSION
from codex_usage.sync.errors import (
    ConcurrentLocalChangeError,
    ConcurrentRemoteChangeError,
    LegacySyncLayoutError,
    MalformedSyncIndexError,
    MissingRemoteConversationError,
    SyncStoreError,
)
from codex_usage.sync.io import atomic_copy, atomic_write_json, snapshot_file
from codex_usage.sync.models import (
    LocalInventory,
    LocalSyncState,
    RemoteIndex,
    RemoteInventory,
    RemoteThreadEntry,
    SyncCounts,
    SyncFileSnapshot,
    SyncIssue,
    SyncPlan,
    SyncPlanItem,
    SyncProgressEvent,
    SyncRunResult,
    SyncTimings,
)
from codex_usage.sync.paths import portable_thread_filename, safe_session_target_path


def test_portable_thread_filename_is_stable_and_windows_safe() -> None:
    assert portable_thread_filename("thread-1") == "thread-1.jsonl"
    assert portable_thread_filename("CON").startswith("id-")
    assert portable_thread_filename("Thread-1").startswith("id-")
    assert portable_thread_filename("Owner/Repo").startswith("id-")
    assert portable_thread_filename("Owner/Repo") == portable_thread_filename("Owner/Repo")
    assert "/" not in portable_thread_filename("Owner/Repo")


def test_safe_session_target_path_rejects_escape_and_absolute_paths(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    assert safe_session_target_path(sessions, "2026/07/13/thread.jsonl") == sessions / "2026/07/13/thread.jsonl"
    assert safe_session_target_path(sessions, "../outside.jsonl") is None
    assert safe_session_target_path(sessions, "/tmp/outside.jsonl") is None
    assert safe_session_target_path(sessions, "C:\\outside.jsonl") is None


def test_atomic_copy_preserves_source_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    target = tmp_path / "remote" / "thread-1.jsonl"
    source.write_bytes(b'{"type":"session_meta"}\n\xff\x00')
    atomic_copy(source, target)
    assert target.read_bytes() == source.read_bytes()
    assert not list(target.parent.glob("*.tmp"))


def test_atomic_write_retries_transient_replace_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "sync-index.json"
    original_replace = Path.replace
    attempts = 0

    def flaky_replace(path: Path, destination: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError(errno.EBUSY, "cloud folder is temporarily busy")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    atomic_write_json(target, {"format_version": 2, "threads": {}})
    assert attempts == 3
    assert json.loads(target.read_text(encoding="utf-8"))["format_version"] == 2


def _permission_error_with_winerror(winerror: int) -> PermissionError:
    error = PermissionError(errno.EACCES, "Windows filesystem error")
    error.winerror = winerror
    return error


def test_atomic_write_retries_windows_sharing_violations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "sync-index.json"
    original_replace = Path.replace
    sharing_violation = _permission_error_with_winerror(32)
    attempts = 0

    def flaky_replace(path: Path, destination: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise sharing_violation
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    atomic_write_json(target, {"format_version": 2, "threads": {}})

    assert attempts == 3
    assert json.loads(target.read_text(encoding="utf-8"))["format_version"] == 2


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(errno.ENOENT, "target parent disappeared"),
        PermissionError(errno.EACCES, "target is not writable"),
        _permission_error_with_winerror(5),
        OSError(errno.EINVAL, "invalid filesystem operation"),
    ],
    ids=["missing", "permission", "windows-access-denied", "permanent-oserror"],
)
def test_atomic_write_does_not_retry_permanent_replace_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: OSError,
) -> None:
    target = tmp_path / "sync-index.json"
    attempts = 0

    def failing_replace(_path: Path, _destination: Path) -> Path:
        nonlocal attempts
        attempts += 1
        raise error

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(type(error)):
        atomic_write_json(target, {"format_version": 2, "threads": {}})

    assert attempts == 1
    assert not list(tmp_path.glob("*.tmp"))


def _remote_entry(thread_id: str = "thread-1") -> RemoteThreadEntry:
    return RemoteThreadEntry(
        thread_id=thread_id,
        file=f"conversations/{portable_thread_filename(thread_id)}",
        source_relative_path=f"2026/07/13/{thread_id}.jsonl",
        index_entry={"id": thread_id, "thread_name": "Example"},
        project_key="https://github.com/example/repo",
        project_label="repo",
        project_aliases=("/Users/example/repo",),
        sha256="abc123",
        size_bytes=42,
        session_updated_at="2026-07-13T12:00:00Z",
        exported_at="2026-07-13T12:01:00Z",
        source_machine_id="machine-a",
    )


def _plan_item(
    tmp_path: Path,
    *,
    thread_id: str = "thread-1",
    state: str = "synced",
    action: str = "none",
    expected_remote_entry: RemoteThreadEntry | None = None,
    memory_database_rows: int = 0,
) -> SyncPlanItem:
    return SyncPlanItem(
        thread_id=thread_id,
        state=state,
        action=action,
        reason="test reason",
        local=SyncFileSnapshot(tmp_path / "local.jsonl", True, "local-hash", 10),
        remote=SyncFileSnapshot(tmp_path / "remote.jsonl", True, "remote-hash", 11),
        base_sha256="base-hash",
        updated_at="2026-07-13T12:00:00Z",
        source_relative_path=f"2026/07/13/{thread_id}.jsonl",
        project_key="repo",
        project_label="Repository",
        memory_database_rows=memory_database_rows,
        expected_remote_entry=expected_remote_entry,
    )


def test_version_2_index_round_trips_without_losing_original_thread_ids() -> None:
    entry = _remote_entry("Owner/Repo")
    index = RemoteIndex(
        format_version=SYNC_FORMAT_VERSION,
        updated_at="2026-07-13T12:01:00Z",
        threads={entry.thread_id: entry},
    )

    payload = index.to_dict()

    assert payload == {
        "format_version": 2,
        "updated_at": "2026-07-13T12:01:00Z",
        "threads": {
            "Owner/Repo": {
                "file": entry.file,
                "source_relative_path": entry.source_relative_path,
                "index_entry": {"id": "Owner/Repo", "thread_name": "Example"},
                "project_key": entry.project_key,
                "project_label": "repo",
                "project_aliases": ["/Users/example/repo"],
                "sha256": "abc123",
                "size_bytes": 42,
                "session_updated_at": "2026-07-13T12:00:00Z",
                "exported_at": "2026-07-13T12:01:00Z",
                "source_machine_id": "machine-a",
            }
        },
    }
    assert RemoteIndex.from_dict(payload) == index


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"format_version": 1, "updated_at": "", "threads": {}},
        {"format_version": 3, "updated_at": "", "threads": {}},
        {"format_version": "2", "updated_at": "", "threads": {}},
        {"format_version": 2, "updated_at": "", "threads": []},
        {"format_version": 2, "updated_at": "", "threads": {}, "extra": True},
    ],
)
def test_remote_index_from_dict_rejects_non_contract_payloads(payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        RemoteIndex.from_dict(payload)


def test_remote_index_rejects_thread_mapping_key_identity_mismatch() -> None:
    with pytest.raises(ValueError, match="thread mapping key"):
        RemoteIndex(
            format_version=SYNC_FORMAT_VERSION,
            updated_at="",
            threads={"thread-1": _remote_entry("thread-2")},
        )


def test_local_sync_state_round_trips_with_version_2_marker() -> None:
    state = LocalSyncState(
        thread_id="thread-1",
        sync_dir_fingerprint="folder-hash",
        base_sha256="base-hash",
        base_size_bytes=42,
        base_updated_at="2026-07-13T12:00:00Z",
        last_remote_sha256="remote-hash",
        last_local_sha256="local-hash",
        source_relative_path="2026/07/13/thread-1.jsonl",
        project_key="repo",
        project_label="Repository",
        synced_at="2026-07-13T12:01:00Z",
    )

    payload = state.to_dict()

    assert payload["sync_version"] == 2
    assert LocalSyncState.from_dict(payload) == state


def test_sync_plan_derives_optimistic_expectations_and_flat_diagnostics(tmp_path: Path) -> None:
    entry = _remote_entry()
    item = _plan_item(tmp_path, expected_remote_entry=entry, memory_database_rows=3)
    plan = SyncPlan(items=(item,), issues=(SyncIssue("warning", "Review this", item.thread_id),), discovered_count=2, remote_count=1, selected_count=1)

    payload = plan.to_dict()

    assert plan.expected_remote_entries() == {item.thread_id: entry}
    assert plan.expected_remote_snapshots() == {item.thread_id: item.remote}
    assert plan.has_issues is True
    assert plan.has_conflicts is False
    assert payload == {
        "threads": [
            {
                "thread_id": "thread-1",
                "state": "synced",
                "action": "none",
                "reason": "test reason",
                "local_path": str(tmp_path / "local.jsonl"),
                "remote_path": str(tmp_path / "remote.jsonl"),
                "local_sha256": "local-hash",
                "remote_sha256": "remote-hash",
                "base_sha256": "base-hash",
                "updated_at": "2026-07-13T12:00:00Z",
                "source_relative_path": "2026/07/13/thread-1.jsonl",
                "project_key": "repo",
                "project_label": "Repository",
                "memory_database_rows": 3,
                "memory_note": "memory database rows detected, not synced by this beta",
            }
        ],
        "issues": [{"code": "warning", "message": "Review this", "thread_id": "thread-1"}],
    }


@pytest.mark.parametrize(
    "issues",
    [(), (SyncIssue("missing_remote_file", "Another thread is missing", "thread-2"),)],
    ids=["missing-diagnostic", "wrong-thread-diagnostic"],
)
def test_sync_plan_rejects_issue_actions_without_matching_diagnostics(
    tmp_path: Path,
    issues: tuple[SyncIssue, ...],
) -> None:
    item = _plan_item(tmp_path, state="issue", action="issue")

    with pytest.raises(ValueError, match="structured SyncIssue"):
        SyncPlan(items=(item,), issues=issues, discovered_count=1, remote_count=0, selected_count=1)


def test_sync_plan_issue_actions_and_result_counts_share_diagnostics(tmp_path: Path) -> None:
    item = _plan_item(tmp_path, state="issue", action="issue")
    issue = SyncIssue("missing_remote_file", "Remote conversation is missing", item.thread_id)
    plan = SyncPlan(items=(item,), issues=(issue,), discovered_count=1, remote_count=0, selected_count=1)
    timings = SyncTimings(discovery=0, planning=1, pull=0, push=0, index=0, total=1)

    result = SyncRunResult.blocked(plan, timings)

    assert plan.has_issues is True
    assert result.issues == (issue,)
    assert result.counts.issues == 1
    assert result.to_dict()["issues"] == [issue.to_dict()]


def test_sync_run_result_constructors_derive_counts_and_exact_payload_keys(tmp_path: Path) -> None:
    unchanged = _plan_item(tmp_path)
    conflict = _plan_item(tmp_path, thread_id="thread-2", state="conflict", action="conflict")
    plan = SyncPlan(
        items=(unchanged, conflict),
        issues=(),
        discovered_count=3,
        remote_count=2,
        selected_count=2,
    )
    timings = SyncTimings(discovery=1, planning=2, pull=3, push=4, index=5, total=15)

    blocked = SyncRunResult.blocked(plan, timings)
    failed = SyncRunResult.failed(
        plan,
        SyncIssue("concurrent_local_change", "Local file changed", "thread-1"),
        pulled=("thread-3",),
        pushed=(),
        timings=timings,
    )
    completed = SyncRunResult.completed(plan, pulled=("thread-3",), pushed=("thread-4",), timings=timings)

    assert blocked.outcome == "conflict"
    assert failed.outcome == "issue"
    assert completed.outcome == "completed"
    assert completed.counts == SyncCounts(3, 2, 2, 1, 1, 1, 1, 0)
    assert set(completed.to_dict()) == {"outcome", "counts", "timings_ms", "threads", "pulled", "pushed", "issues"}
    assert completed.to_dict()["pulled"] == ["thread-3"]
    assert failed.counts.issues == 1


def test_external_payload_models_are_frozen() -> None:
    issue = SyncIssue("code", "message")
    progress = SyncProgressEvent("sync_progress", "planning")

    with pytest.raises(FrozenInstanceError):
        issue.code = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        progress.phase = "changed"  # type: ignore[misc]
    assert progress.to_dict() == {"type": "sync_progress", "phase": "planning"}


def test_inventory_models_keep_original_thread_id_keys() -> None:
    entry = _remote_entry("Owner/Repo")
    index = RemoteIndex(2, "", {entry.thread_id: entry})
    remote = RemoteInventory(index, index, SyncFileSnapshot(None, False), {entry.thread_id: SyncFileSnapshot(None, False)}, (), ())
    local = LocalInventory((), {}, {}, 0)

    assert tuple(remote.files) == ("Owner/Repo",)
    assert local.discovered_count == 0


def test_sync_store_errors_share_one_typed_base() -> None:
    for error_type in (
        LegacySyncLayoutError,
        MalformedSyncIndexError,
        MissingRemoteConversationError,
        ConcurrentLocalChangeError,
        ConcurrentRemoteChangeError,
    ):
        assert issubclass(error_type, SyncStoreError)


def test_snapshot_file_hashes_raw_bytes(tmp_path: Path) -> None:
    path = tmp_path / "conversation.jsonl"
    path.write_bytes(b"\xff\x00")

    snapshot = snapshot_file(path)

    assert snapshot == SyncFileSnapshot(
        path=path,
        exists=True,
        sha256="ea5dbf9596d187e9500f23e9a680109475341cf4e81f7e043f7d97152c10772f",
        size_bytes=2,
    )
