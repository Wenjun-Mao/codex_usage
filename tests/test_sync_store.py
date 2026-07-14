from __future__ import annotations

import errno
import json
import os
import queue
import stat
import subprocess
import sys
import textwrap
import threading
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import codex_usage.sync.io as sync_io
import codex_usage.sync.store as sync_store
from codex_usage.sync.constants import SYNC_FORMAT_VERSION
from codex_usage.sync.errors import (
    ConcurrentLocalChangeError,
    ConcurrentRemoteChangeError,
    LegacySyncLayoutError,
    MalformedSyncIndexError,
    MissingRemoteConversationError,
    SyncStoreError,
)
from codex_usage.sync.io import atomic_copy, atomic_write_json, read_json_object, snapshot_file
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
from codex_usage.sync.store import RemoteStore


_WINDOWS_MOUNT_POINT_REPARSE_TAG = 0xA0000003


class _TemporaryFileProxy:
    def __init__(
        self,
        wrapped: Any,
        *,
        write_callback: Any = None,
        flush_callback: Any = None,
    ) -> None:
        self._wrapped = wrapped
        self._write_callback = write_callback
        self._flush_callback = flush_callback

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)

    def __enter__(self) -> _TemporaryFileProxy:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def write(self, data: Any) -> int:
        if self._write_callback is not None:
            return self._write_callback(self._wrapped, data)
        return self._wrapped.write(data)

    def flush(self) -> None:
        if self._flush_callback is not None:
            self._flush_callback(self._wrapped)
            return
        self._wrapped.flush()


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


def test_atomic_copy_streams_held_temp_and_resets_after_partial_write_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.jsonl"
    source_bytes = b"first-line\n" + (b"x" * (2 * 1024 * 1024)) + b"\nlast-line\n"
    source.write_bytes(source_bytes)
    target = tmp_path / "remote" / "thread-1.jsonl"
    original_named_temporary_file = sync_io.tempfile.NamedTemporaryFile
    original_fsync = os.fsync
    write_sizes: list[int] = []
    temporary_files: list[_TemporaryFileProxy] = []
    flush_calls = 0
    fsync_calls = 0
    injected_partial_failure = False

    def write_with_one_partial_failure(wrapped: Any, data: Any) -> int:
        nonlocal injected_partial_failure
        payload = bytes(data)
        write_sizes.append(len(payload))
        if not injected_partial_failure:
            injected_partial_failure = True
            wrapped.write(payload[:17])
            raise OSError(errno.EBUSY, "temporary file write is busy")
        return wrapped.write(payload)

    def track_flush(wrapped: Any) -> None:
        nonlocal flush_calls
        flush_calls += 1
        wrapped.flush()

    def faulting_temporary_file(*args: Any, **kwargs: Any) -> _TemporaryFileProxy:
        proxy = _TemporaryFileProxy(
            original_named_temporary_file(*args, **kwargs),
            write_callback=write_with_one_partial_failure,
            flush_callback=track_flush,
        )
        temporary_files.append(proxy)
        return proxy

    def track_fsync(file_descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        original_fsync(file_descriptor)

    monkeypatch.setattr(sync_io.tempfile, "NamedTemporaryFile", faulting_temporary_file)
    monkeypatch.setattr(os, "fsync", track_fsync)

    atomic_copy(source, target)

    assert target.read_bytes() == source_bytes
    assert injected_partial_failure
    assert len(write_sizes) >= 3
    assert max(write_sizes) < len(source_bytes)
    assert flush_calls >= 1
    assert fsync_calls >= 1
    assert temporary_files[0].closed
    assert not list(target.parent.glob("*.tmp"))


def test_atomic_copy_retries_transient_source_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.jsonl"
    source_bytes = b"source bytes read through a retried stream\n"
    source.write_bytes(source_bytes)
    target = tmp_path / "remote" / "thread-1.jsonl"
    original_open = Path.open
    source_opens = 0
    injected_read_failure = False

    class _TransientReadProxy:
        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped

        def __getattr__(self, name: str) -> Any:
            return getattr(self._wrapped, name)

        def __enter__(self) -> _TransientReadProxy:
            return self

        def __exit__(self, *_args: Any) -> None:
            self._wrapped.close()

        def read(self, size: int = -1) -> bytes:
            nonlocal injected_read_failure
            if not injected_read_failure:
                injected_read_failure = True
                raise OSError(errno.EBUSY, "source read is busy")
            return self._wrapped.read(size)

    def open_with_transient_source_read(
        path: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> Any:
        nonlocal source_opens
        opened = original_open(
            path,
            mode=mode,
            buffering=buffering,
            encoding=encoding,
            errors=errors,
            newline=newline,
        )
        if path == source and mode == "rb":
            source_opens += 1
            return _TransientReadProxy(opened)
        return opened

    monkeypatch.setattr(Path, "open", open_with_transient_source_read)

    atomic_copy(source, target)

    assert source_opens == 2
    assert injected_read_failure
    assert target.read_bytes() == source_bytes


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


@pytest.mark.parametrize("operation", ["parent-mkdir", "temporary-file"])
def test_atomic_write_retries_transient_setup_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    target = tmp_path / "remote" / "sync-index.json"
    attempts = 0

    if operation == "parent-mkdir":
        original_mkdir = Path.mkdir

        def flaky_mkdir(
            path: Path,
            mode: int = 0o777,
            parents: bool = False,
            exist_ok: bool = False,
        ) -> None:
            nonlocal attempts
            if path == target.parent:
                attempts += 1
                if attempts < 3:
                    raise OSError(errno.EBUSY, "cloud directory creation is busy")
            original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

        monkeypatch.setattr(Path, "mkdir", flaky_mkdir)
    else:
        target.parent.mkdir(parents=True)
        original_named_temporary_file = sync_io.tempfile.NamedTemporaryFile

        def flaky_named_temporary_file(*args: Any, **kwargs: Any) -> Any:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise OSError(errno.EBUSY, "cloud temporary-file creation is busy")
            return original_named_temporary_file(*args, **kwargs)

        monkeypatch.setattr(sync_io.tempfile, "NamedTemporaryFile", flaky_named_temporary_file)

    atomic_write_json(target, {"format_version": 2, "threads": {}})

    assert attempts == 3
    assert json.loads(target.read_text(encoding="utf-8"))["format_version"] == 2
    assert not list(target.parent.glob("*.tmp"))


@pytest.mark.parametrize("operation", ["parent-mkdir", "temporary-file"])
def test_atomic_write_does_not_retry_permanent_setup_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    target = tmp_path / "remote" / "sync-index.json"
    attempts = 0

    if operation == "parent-mkdir":
        original_mkdir = Path.mkdir

        def denied_mkdir(
            path: Path,
            mode: int = 0o777,
            parents: bool = False,
            exist_ok: bool = False,
        ) -> None:
            nonlocal attempts
            if path == target.parent:
                attempts += 1
                raise PermissionError(errno.EACCES, "directory creation denied")
            original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

        monkeypatch.setattr(Path, "mkdir", denied_mkdir)
    else:
        target.parent.mkdir(parents=True)

        def denied_named_temporary_file(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal attempts
            attempts += 1
            raise PermissionError(errno.EACCES, "temporary-file creation denied")

        monkeypatch.setattr(sync_io.tempfile, "NamedTemporaryFile", denied_named_temporary_file)

    with pytest.raises(PermissionError):
        atomic_write_json(target, {"format_version": 2, "threads": {}})

    assert attempts == 1
    assert not target.exists()
    assert not list(target.parent.glob("*.tmp"))


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


@pytest.mark.parametrize("thread_id", ["", " \t"], ids=["empty", "whitespace"])
def test_remote_index_rejects_blank_thread_ids(thread_id: str) -> None:
    entry = replace(_remote_entry(), thread_id=thread_id)

    with pytest.raises(ValueError, match="thread ids must not be blank"):
        RemoteIndex(
            format_version=SYNC_FORMAT_VERSION,
            updated_at="",
            threads={thread_id: entry},
        )


@pytest.mark.parametrize("thread_id", [" thread-1", "thread-1 "], ids=["leading", "trailing"])
def test_remote_index_rejects_padded_thread_keys_with_field_path(thread_id: str) -> None:
    entry = replace(_remote_entry(), thread_id=thread_id)

    with pytest.raises(ValueError, match=r"remote index threads\[.*\].*canonical"):
        RemoteIndex(
            format_version=SYNC_FORMAT_VERSION,
            updated_at="",
            threads={thread_id: entry},
        )


def test_remote_index_rejects_padded_entry_thread_id_with_field_path() -> None:
    entry = replace(_remote_entry(), thread_id=" thread-1 ")

    with pytest.raises(ValueError, match=r"remote index thread 'thread-1'.*thread_id.*canonical"):
        RemoteIndex(
            format_version=SYNC_FORMAT_VERSION,
            updated_at="",
            threads={"thread-1": entry},
        )


def test_remote_index_rejects_padded_index_entry_identity() -> None:
    entry = replace(_remote_entry(), index_entry={"id": " thread-1 "})

    with pytest.raises(ValueError, match=r"index_entry\.id.*canonical"):
        RemoteIndex(
            format_version=SYNC_FORMAT_VERSION,
            updated_at="",
            threads={entry.thread_id: entry},
        )


def test_remote_index_requires_index_entry_identity() -> None:
    entry = replace(_remote_entry(), index_entry={"thread_name": "Example"})

    with pytest.raises(ValueError, match=r"index_entry\.id.*required"):
        RemoteIndex(
            format_version=SYNC_FORMAT_VERSION,
            updated_at="",
            threads={entry.thread_id: entry},
        )


def test_remote_index_requires_index_entry_identity_to_match_thread() -> None:
    entry = replace(_remote_entry("task-a"), index_entry={"id": "task-b"})

    with pytest.raises(ValueError, match=r"index_entry\.id.*match.*thread_id"):
        RemoteIndex(
            format_version=SYNC_FORMAT_VERSION,
            updated_at="",
            threads={entry.thread_id: entry},
        )


def test_remote_index_rejects_padded_and_canonical_identity_collision() -> None:
    canonical = _remote_entry("thread-1")
    padded = replace(
        _remote_entry(" thread-1 "),
        file="conversations/padded.jsonl",
    )

    with pytest.raises(ValueError, match=r"remote index threads\[' thread-1 '\].*canonical"):
        RemoteIndex(
            format_version=SYNC_FORMAT_VERSION,
            updated_at="",
            threads={canonical.thread_id: canonical, padded.thread_id: padded},
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


def _session_jsonl(
    thread_id: str,
    *,
    cwd: str = "/Users/example/repo",
    repository_url: str = "https://github.com/example/repo.git",
) -> bytes:
    event = {
        "timestamp": "2026-07-13T12:00:00Z",
        "type": "session_meta",
        "payload": {
            "id": thread_id,
            "timestamp": "2026-07-13T12:00:00Z",
            "cwd": cwd,
            "git": {"repository_url": repository_url},
        },
    }
    return (json.dumps(event, separators=(",", ":")) + "\n").encode()


def _write_index(root: Path, entries: dict[str, RemoteThreadEntry], *, updated_at: str = "before") -> None:
    index = RemoteIndex(format_version=2, updated_at=updated_at, threads=entries)
    atomic_write_json(root / "sync-index.json", index.to_dict())


def _write_indexed_conversation(
    root: Path,
    thread_id: str,
    *,
    contents: bytes | None = None,
) -> RemoteThreadEntry:
    path = root / "conversations" / portable_thread_filename(thread_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents if contents is not None else _session_jsonl(thread_id))
    snapshot = snapshot_file(path)
    return replace(
        _remote_entry(thread_id),
        sha256=snapshot.sha256,
        size_bytes=snapshot.size_bytes,
    )


def _materialized_inventory(
    store: RemoteStore,
    *thread_ids: str,
) -> RemoteInventory:
    return store.materialize_selected(store.load_inventory(), tuple(thread_ids))


def _commit_index(
    store: RemoteStore,
    base: RemoteInventory,
    changed: dict[str, RemoteThreadEntry],
    written: dict[str, SyncFileSnapshot],
) -> RemoteIndex:
    selected_ids = tuple(thread_id for thread_id in changed if thread_id in base.files)
    return store.commit_index(
        base,
        changed,
        written,
        expected_entries={
            thread_id: base.persisted_index.threads.get(thread_id)
            for thread_id in selected_ids
        },
        expected_files={thread_id: base.files[thread_id] for thread_id in selected_ids},
    )


def test_remote_store_loads_empty_folder_without_writing(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    store = RemoteStore(root)

    inventory = store.load_inventory()

    assert inventory.index.format_version == 2
    assert inventory.index.threads == {}
    assert inventory.files == {}
    assert not root.exists()


def test_remote_store_rejects_version_1_layout_without_mutating_it(tmp_path: Path) -> None:
    legacy = tmp_path / "sync" / "threads" / "thread-1"
    legacy.mkdir(parents=True)
    (legacy / "session.jsonl").write_text("{}\n", encoding="utf-8")
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    with pytest.raises(LegacySyncLayoutError, match="empty the sync folder"):
        RemoteStore(tmp_path / "sync").load_inventory()

    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before


@pytest.mark.parametrize(
    "contents",
    [b"{not-json\n", b"[]\n", b'{"format_version":1,"updated_at":"","threads":{}}\n'],
    ids=["invalid-json", "not-object", "wrong-version"],
)
def test_remote_store_rejects_malformed_index_without_mutating_it(
    tmp_path: Path,
    contents: bytes,
) -> None:
    root = tmp_path / "sync"
    root.mkdir()
    index_path = root / "sync-index.json"
    index_path.write_bytes(contents)

    with pytest.raises(MalformedSyncIndexError):
        RemoteStore(root).load_inventory()

    assert index_path.read_bytes() == contents


@pytest.mark.parametrize(
    "thread_id",
    ["", " \t", " thread-1", "thread-1 "],
    ids=["empty", "whitespace", "leading", "trailing"],
)
def test_remote_store_rejects_noncanonical_thread_id_index_without_mutating_it(
    tmp_path: Path,
    thread_id: str,
) -> None:
    root = tmp_path / "sync"
    root.mkdir()
    index_path = root / "sync-index.json"
    contents = (
        json.dumps(
            {
                "format_version": 2,
                "updated_at": "",
                "threads": {thread_id: _remote_entry().to_dict()},
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    index_path.write_bytes(contents)
    store = RemoteStore(root)
    before = tuple(sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")))

    with pytest.raises(MalformedSyncIndexError, match="canonical"):
        store.load_inventory()

    assert index_path.read_bytes() == contents
    assert tuple(sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))) == before
    assert not store.lock_path.exists()


@pytest.mark.parametrize(
    ("nested_thread_id", "message"),
    [(None, "required"), ("task-b", "match")],
    ids=["missing", "mismatched"],
)
def test_remote_store_rejects_invalid_nested_thread_identity_without_mutation(
    tmp_path: Path,
    nested_thread_id: str | None,
    message: str,
) -> None:
    root = tmp_path / "sync"
    root.mkdir()
    entry_payload = _remote_entry("task-a").to_dict()
    if nested_thread_id is None:
        del entry_payload["index_entry"]["id"]
    else:
        entry_payload["index_entry"]["id"] = nested_thread_id
    contents = (
        json.dumps(
            {
                "format_version": 2,
                "updated_at": "",
                "threads": {"task-a": entry_payload},
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    index_path = root / "sync-index.json"
    index_path.write_bytes(contents)
    store = RemoteStore(root)
    before = tuple(sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")))

    with pytest.raises(MalformedSyncIndexError, match=message):
        store.load_inventory()

    assert index_path.read_bytes() == contents
    assert tuple(sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))) == before
    assert not store.lock_path.exists()


@pytest.mark.parametrize(
    "claimed_path",
    [
        "thread-1.jsonl",
        "../thread-1.jsonl",
        "conversations/nested/thread-1.jsonl",
        "conversations//thread-1.jsonl",
        "conversations\\thread-1.jsonl",
        "C:\\conversations\\thread-1.jsonl",
    ],
)
def test_remote_store_rejects_non_direct_conversation_file_claims(
    tmp_path: Path,
    claimed_path: str,
) -> None:
    root = tmp_path / "sync"
    entry = replace(_remote_entry(), file=claimed_path)
    _write_index(root, {entry.thread_id: entry})

    with pytest.raises(MalformedSyncIndexError, match="direct child"):
        RemoteStore(root).load_inventory()


@pytest.mark.parametrize(
    "relative_path",
    [
        "2026/CON/thread.jsonl",
        "2026/CONOUT$/thread.jsonl",
        "2026/COM¹/thread.jsonl",
        "2026/thread.jsonl:alternate",
        "2026/inva<lid/thread.jsonl",
        "2026/control\x01/thread.jsonl",
        "2026/trailing./thread.jsonl",
        "2026/trailing /thread.jsonl",
        "2026/thread.txt",
        "2026//thread.jsonl",
        "2026/./thread.jsonl",
    ],
)
def test_safe_session_target_path_rejects_nonportable_windows_paths(
    tmp_path: Path,
    relative_path: str,
) -> None:
    assert safe_session_target_path(tmp_path / "sessions", relative_path) is None


def test_remote_store_rejects_duplicate_remote_filename_claims(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    first = _remote_entry("thread-1")
    second = replace(_remote_entry("thread-2"), file=first.file)
    _write_index(root, {first.thread_id: first, second.thread_id: second})

    with pytest.raises(MalformedSyncIndexError, match="same remote file"):
        RemoteStore(root).load_inventory()


def test_remote_store_rejects_case_insensitive_remote_filename_collisions(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    first = replace(_remote_entry("thread-1"), file="conversations/shared.jsonl")
    second = replace(_remote_entry("thread-2"), file="conversations/SHARED.jsonl")
    _write_index(root, {first.thread_id: first, second.thread_id: second})

    with pytest.raises(MalformedSyncIndexError, match="same remote file"):
        RemoteStore(root).load_inventory()


def test_remote_store_reports_indexed_missing_file_without_writing(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    entry = _remote_entry()
    _write_index(root, {entry.thread_id: entry})
    before = (root / "sync-index.json").read_bytes()

    store = RemoteStore(root)
    inventory = _materialized_inventory(store, entry.thread_id)

    assert inventory.files[entry.thread_id] == SyncFileSnapshot(
        path=root / entry.file,
        exists=False,
    )
    assert inventory.issues == (
        SyncIssue(
            "missing_remote_file",
            f"Remote conversation {entry.file} is missing",
            entry.thread_id,
        ),
    )
    assert inventory.repaired_thread_ids == ()
    assert (root / "sync-index.json").read_bytes() == before


def test_remote_store_relinks_missing_index_claim_to_matching_unindexed_jsonl(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sync"
    stale = _remote_entry("thread-1")
    _write_index(root, {stale.thread_id: stale})
    path = root / "conversations" / "recovered.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(_session_jsonl(stale.thread_id))
    index_before = (root / "sync-index.json").read_bytes()

    store = RemoteStore(root)
    inventory = _materialized_inventory(store, stale.thread_id)

    repaired = inventory.index.threads[stale.thread_id]
    assert repaired.file == "conversations/recovered.jsonl"
    assert repaired.source_relative_path == stale.source_relative_path
    assert repaired.index_entry == stale.index_entry
    assert repaired.sha256 == snapshot_file(path).sha256
    assert repaired.size_bytes == snapshot_file(path).size_bytes
    assert inventory.files[stale.thread_id] == snapshot_file(path)
    assert inventory.repaired_thread_ids == (stale.thread_id,)
    assert inventory.issues == ()
    assert (root / "sync-index.json").read_bytes() == index_before


def test_remote_store_repairs_stale_hash_and_size_in_memory_only(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    actual = _write_indexed_conversation(root, "thread-1")
    stale = replace(actual, sha256="stale", size_bytes=1)
    _write_index(root, {stale.thread_id: stale})
    index_before = (root / "sync-index.json").read_bytes()
    file_path = root / stale.file
    file_before = file_path.read_bytes()

    store = RemoteStore(root)
    inventory = _materialized_inventory(store, stale.thread_id)

    assert inventory.persisted_index.threads[stale.thread_id] == stale
    assert inventory.index.threads[stale.thread_id] == actual
    assert inventory.files[stale.thread_id] == snapshot_file(file_path)
    assert inventory.repaired_thread_ids == (stale.thread_id,)
    assert inventory.issues == ()
    assert (root / "sync-index.json").read_bytes() == index_before
    assert file_path.read_bytes() == file_before


def test_remote_store_reports_index_and_jsonl_thread_identity_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1", contents=_session_jsonl("thread-2"))
    _write_index(root, {entry.thread_id: entry})
    file_path = root / entry.file
    before = file_path.read_bytes()

    store = RemoteStore(root)
    inventory = _materialized_inventory(store, entry.thread_id)

    assert inventory.index.threads[entry.thread_id] == entry
    assert inventory.repaired_thread_ids == ()
    assert len(inventory.issues) == 1
    assert inventory.issues[0].code == "unindexed_unreadable"
    assert inventory.issues[0].thread_id == entry.thread_id
    assert "contains thread id 'thread-2'" in inventory.issues[0].message
    assert file_path.read_bytes() == before


def test_remote_store_reconstructs_unindexed_jsonl_without_rewriting_it(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    path = root / "conversations" / "unindexed.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(_session_jsonl("Owner/Repo"))
    before = path.read_bytes()

    inventory = RemoteStore(root).load_inventory()

    repaired = inventory.index.threads["Owner/Repo"]
    assert inventory.persisted_index.threads == {}
    assert repaired.file == "conversations/unindexed.jsonl"
    assert repaired.source_relative_path == f"synced/{portable_thread_filename('Owner/Repo')}"
    assert repaired.index_entry == {"id": "Owner/Repo"}
    assert repaired.project_key == "https://github.com/example/repo"
    assert repaired.project_label == "repo"
    assert repaired.project_aliases == ("/users/example/repo",)
    assert repaired.sha256 == snapshot_file(path).sha256
    assert repaired.size_bytes == len(before)
    assert repaired.session_updated_at == "2026-07-13T12:00:00Z"
    assert inventory.files["Owner/Repo"] == snapshot_file(path)
    assert inventory.repaired_thread_ids == ("Owner/Repo",)
    assert inventory.issues == ()
    assert path.read_bytes() == before
    assert not (root / "sync-index.json").exists()


@pytest.mark.parametrize(
    "contents",
    [b"not-json\n", b'{"type":"session_meta","payload":{}}\n', b"\xff\xfe\n"],
    ids=["invalid-json", "missing-id", "invalid-utf8"],
)
def test_remote_store_reports_unindexed_unreadable_jsonl_without_mutation(
    tmp_path: Path,
    contents: bytes,
) -> None:
    root = tmp_path / "sync"
    path = root / "conversations" / "unreadable.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(contents)

    inventory = RemoteStore(root).load_inventory()

    assert inventory.index.threads == {}
    assert inventory.files == {}
    assert len(inventory.issues) == 1
    assert inventory.issues[0].code == "unindexed_unreadable"
    assert inventory.issues[0].thread_id == ""
    assert "conversations/unreadable.jsonl" in inventory.issues[0].message
    assert path.read_bytes() == contents
    assert not (root / "sync-index.json").exists()


def test_remote_store_omits_padded_unindexed_identity_without_mutation(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    path = root / "conversations" / "padded.jsonl"
    path.parent.mkdir(parents=True)
    contents = _session_jsonl(" thread-1 ")
    path.write_bytes(contents)

    inventory = RemoteStore(root).load_inventory()

    assert inventory.index.threads == {}
    assert inventory.files == {}
    assert len(inventory.issues) == 1
    assert inventory.issues[0].code == "unindexed_unreadable"
    assert inventory.issues[0].thread_id == ""
    assert path.read_bytes() == contents
    assert not (root / "sync-index.json").exists()


def test_remote_store_does_not_merge_padded_identity_with_canonical_task(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    conversations = root / "conversations"
    conversations.mkdir(parents=True)
    canonical_path = conversations / "canonical.jsonl"
    padded_path = conversations / "padded.jsonl"
    canonical_path.write_bytes(_session_jsonl("thread-1"))
    padded_path.write_bytes(_session_jsonl(" thread-1 "))

    inventory = RemoteStore(root).load_inventory()

    assert tuple(inventory.index.threads) == ("thread-1",)
    assert inventory.files["thread-1"] == snapshot_file(canonical_path)
    assert len(inventory.issues) == 1
    assert "conversations/padded.jsonl" in inventory.issues[0].message
    assert padded_path.read_bytes() == _session_jsonl(" thread-1 ")
    assert not (root / "sync-index.json").exists()


def test_remote_store_leaves_unportable_unindexed_jsonl_unrepaired(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    path = root / "conversations" / "Mixed-Case.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(_session_jsonl("thread-1"))

    inventory = RemoteStore(root).load_inventory()

    assert inventory.index.threads == {}
    assert inventory.files == {}
    assert len(inventory.issues) == 1
    assert inventory.issues[0].code == "unindexed_unreadable"
    assert "portable direct JSONL path" in inventory.issues[0].message
    assert path.read_bytes() == _session_jsonl("thread-1")


def test_remote_store_reports_duplicate_reconstructed_thread_identity(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    conversations = root / "conversations"
    conversations.mkdir(parents=True)
    (conversations / "first.jsonl").write_bytes(_session_jsonl("thread-1"))
    (conversations / "second.jsonl").write_bytes(_session_jsonl("thread-1"))

    inventory = RemoteStore(root).load_inventory()

    assert inventory.index.threads == {}
    assert inventory.files == {}
    assert len(inventory.issues) == 2
    assert {issue.code for issue in inventory.issues} == {"unindexed_unreadable"}
    assert all("multiple remote files" in issue.message for issue in inventory.issues)


def test_remote_store_transaction_contends_releases_and_stays_outside_store(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    first = RemoteStore(root, lock_timeout=0)
    second = RemoteStore(root, lock_timeout=0)

    assert first.lock_path.parent == root.parent
    assert root not in first.lock_path.parents

    with first.transaction():
        with first.transaction():
            pass
        with pytest.raises(ConcurrentRemoteChangeError, match="transaction lock"):
            with second.transaction():
                pass

    with second.transaction():
        pass

    assert not root.exists()
    assert first.lock_path == second.lock_path


def test_remote_store_transaction_releases_after_body_failure(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    first = RemoteStore(root, lock_timeout=0)
    second = RemoteStore(root, lock_timeout=0)

    with pytest.raises(RuntimeError, match="body failed"):
        with first.transaction():
            raise RuntimeError("body failed")

    with second.transaction():
        pass


def test_remote_store_transaction_contends_and_releases_across_processes(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    child_code = textwrap.dedent(
        """
        import sys
        from pathlib import Path

        from codex_usage.sync.store import RemoteStore

        store = RemoteStore(Path(sys.argv[1]), lock_timeout=2)
        with store.transaction():
            print("locked", flush=True)
            sys.stdin.readline()
        """
    )
    environment = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_root, environment.get("PYTHONPATH", "")) if part
    )
    process = subprocess.Popen(
        [sys.executable, "-c", child_code, str(root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    output: queue.Queue[str] = queue.Queue()
    assert process.stdout is not None
    assert process.stdin is not None
    assert process.stderr is not None
    reader = threading.Thread(target=lambda: output.put(process.stdout.readline()), daemon=True)
    reader.start()

    try:
        assert output.get(timeout=5).strip() == "locked"
        with pytest.raises(ConcurrentRemoteChangeError, match="transaction lock"):
            with RemoteStore(root, lock_timeout=0).transaction():
                pass

        process.stdin.write("\n")
        process.stdin.flush()
        assert process.wait(timeout=5) == 0, process.stderr.read()

        with RemoteStore(root, lock_timeout=0).transaction():
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_remote_store_mutations_require_held_transaction(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    store = RemoteStore(root)
    source = tmp_path / "source.jsonl"
    source.write_bytes(_session_jsonl("thread-1"))
    target = root / "conversations" / "thread-1.jsonl"
    base = store.load_inventory()

    with pytest.raises(RuntimeError, match="held transaction"):
        store.write_conversation(source, target.name, SyncFileSnapshot(target, False))
    with pytest.raises(RuntimeError, match="held transaction"):
        store.commit_index(base, {}, {}, expected_entries={}, expected_files={})

    assert not root.exists()


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable: {error}")


def test_write_conversation_rejects_parent_swap_before_temp_population_without_external_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    base = _materialized_inventory(store, entry.thread_id)
    source = tmp_path / "source.jsonl"
    source.write_bytes(_session_jsonl("thread-1") + b"our-change\n")
    conversations = root / "conversations"
    target = conversations / portable_thread_filename(entry.thread_id)
    target_before = target.read_bytes()
    detached = tmp_path / "detached-conversations"
    external = tmp_path / "external-conversations"
    collision_bytes = b"external temp sentinel\n"
    original_named_temporary_file = sync_io.tempfile.NamedTemporaryFile
    temporary_name = ""
    temporary_files: list[Any] = []

    def create_then_swap_parent(*args: Any, **kwargs: Any) -> Any:
        nonlocal temporary_name
        temporary = original_named_temporary_file(*args, **kwargs)
        temporary_files.append(temporary)
        if Path(kwargs["dir"]) != conversations:
            return temporary
        temporary_name = Path(temporary.name).name
        try:
            conversations.rename(detached)
        except OSError as error:
            temporary.close()
            pytest.skip(f"cannot swap a directory containing an open temp file: {error}")
        external.mkdir()
        (external / temporary_name).write_bytes(collision_bytes)
        (external / target.name).write_bytes(target_before)
        try:
            conversations.symlink_to(external, target_is_directory=True)
        except OSError as error:
            temporary.close()
            detached.rename(conversations)
            pytest.skip(f"directory symlinks are unavailable: {error}")
        return temporary

    monkeypatch.setattr(sync_io.tempfile, "NamedTemporaryFile", create_then_swap_parent)

    with store.transaction():
        with pytest.raises(MalformedSyncIndexError, match="directory must not be a symlink"):
            store.write_conversation(source, target.name, base.files[entry.thread_id])

    assert temporary_name
    assert (external / temporary_name).read_bytes() == collision_bytes
    assert (external / target.name).read_bytes() == target_before
    assert temporary_files[0].closed


def test_write_conversation_rejects_parent_swap_during_temp_population_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    base = _materialized_inventory(store, entry.thread_id)
    source = tmp_path / "source.jsonl"
    source.write_bytes(_session_jsonl("thread-1") + b"our-change\n")
    conversations = root / "conversations"
    target = conversations / portable_thread_filename(entry.thread_id)
    target_before = target.read_bytes()
    detached = tmp_path / "detached-conversations"
    external = tmp_path / "external-conversations"
    collision_bytes = b"retry collision sentinel\n"
    original_named_temporary_file = sync_io.tempfile.NamedTemporaryFile
    temporary_files: list[_TemporaryFileProxy] = []
    temporary_name = ""
    write_attempts = 0

    def write_then_swap(wrapped: Any, data: Any) -> int:
        nonlocal temporary_name, write_attempts
        write_attempts += 1
        payload = bytes(data)
        wrapped.write(payload[:11])
        temporary_name = Path(wrapped.name).name
        try:
            conversations.rename(detached)
        except OSError as error:
            wrapped.close()
            pytest.skip(f"cannot swap a directory containing an open temp file: {error}")
        external.mkdir()
        (external / temporary_name).write_bytes(collision_bytes)
        (external / target.name).write_bytes(target_before)
        try:
            conversations.symlink_to(external, target_is_directory=True)
        except OSError as error:
            wrapped.close()
            detached.rename(conversations)
            pytest.skip(f"directory symlinks are unavailable: {error}")
        raise OSError(errno.EBUSY, "temporary population is busy")

    def faulting_temporary_file(*args: Any, **kwargs: Any) -> _TemporaryFileProxy:
        proxy = _TemporaryFileProxy(
            original_named_temporary_file(*args, **kwargs),
            write_callback=write_then_swap,
        )
        temporary_files.append(proxy)
        return proxy

    monkeypatch.setattr(sync_io.tempfile, "NamedTemporaryFile", faulting_temporary_file)

    with store.transaction():
        with pytest.raises(MalformedSyncIndexError, match="directory must not be a symlink"):
            store.write_conversation(source, target.name, base.files[entry.thread_id])

    assert write_attempts == 1
    assert temporary_name
    assert (external / temporary_name).read_bytes() == collision_bytes
    assert (external / target.name).read_bytes() == target_before
    assert temporary_files[0].closed


def test_atomic_write_json_does_not_reopen_temp_after_guarded_parent_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "index-store"
    parent.mkdir()
    target = parent / "sync-index.json"
    target.write_bytes(b'{"format_version":2,"threads":{},"updated_at":"before"}\n')
    expected = snapshot_file(target)
    target_before = target.read_bytes()
    detached = tmp_path / "detached-index-store"
    external = tmp_path / "external-index-store"
    collision_bytes = b"external JSON temp sentinel\n"
    original_named_temporary_file = sync_io.tempfile.NamedTemporaryFile
    temporary_name = ""
    temporary_files: list[Any] = []

    def guard_parent() -> None:
        if sync_io.path_kind(parent) == "symlink":
            raise MalformedSyncIndexError("index parent must not be a symlink")

    def create_then_swap_parent(*args: Any, **kwargs: Any) -> Any:
        nonlocal temporary_name
        temporary = original_named_temporary_file(*args, **kwargs)
        temporary_files.append(temporary)
        temporary_name = Path(temporary.name).name
        try:
            parent.rename(detached)
        except OSError as error:
            temporary.close()
            pytest.skip(f"cannot swap a directory containing an open temp file: {error}")
        external.mkdir()
        (external / temporary_name).write_bytes(collision_bytes)
        (external / target.name).write_bytes(target_before)
        try:
            parent.symlink_to(external, target_is_directory=True)
        except OSError as error:
            temporary.close()
            detached.rename(parent)
            pytest.skip(f"directory symlinks are unavailable: {error}")
        return temporary

    monkeypatch.setattr(sync_io.tempfile, "NamedTemporaryFile", create_then_swap_parent)

    with pytest.raises(MalformedSyncIndexError, match="index parent must not be a symlink"):
        atomic_write_json(
            target,
            {"format_version": 2, "threads": {}, "updated_at": "after"},
            expected_target=expected,
            target_label="index",
            path_guard=guard_parent,
        )

    assert temporary_name
    assert (external / temporary_name).read_bytes() == collision_bytes
    assert (external / target.name).read_bytes() == target_before
    assert temporary_files[0].closed


def test_remote_store_rejects_symlinked_index_without_reading_external_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    external = tmp_path / "external-index.json"
    external.write_bytes(b'{"format_version":2,"threads":{},"updated_at":""}\n')
    before = external.read_bytes()
    root = tmp_path / "sync"
    root.mkdir()
    index_path = root / "sync-index.json"
    _symlink_or_skip(index_path, external)
    original_read_bytes = Path.read_bytes
    read_attempts = 0

    def reject_index_read(path: Path) -> bytes:
        nonlocal read_attempts
        if path == index_path:
            read_attempts += 1
            raise AssertionError("symlinked index bytes must not be read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_index_read)

    with pytest.raises(MalformedSyncIndexError, match="sync-index.json.*symlink"):
        RemoteStore(root).load_inventory()

    assert read_attempts == 0
    assert external.read_bytes() == before
    assert index_path.is_symlink()


def test_remote_store_rejects_directory_at_index_path_without_reading_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sync"
    index_path = root / "sync-index.json"
    index_path.mkdir(parents=True)
    external_bytes = b"do not read or mutate\n"
    marker = index_path / "external-metadata.json"
    marker.write_bytes(external_bytes)
    original_read_bytes = Path.read_bytes
    read_attempts = 0

    def reject_index_read(path: Path) -> bytes:
        nonlocal read_attempts
        if path == index_path:
            read_attempts += 1
            raise AssertionError("directory index bytes must not be read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_index_read)

    with pytest.raises(MalformedSyncIndexError, match="sync-index.json.*regular file"):
        RemoteStore(root).load_inventory()

    assert read_attempts == 0
    assert marker.read_bytes() == external_bytes


def test_remote_store_rejects_symlinked_conversation_without_reading_external_bytes(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external.jsonl"
    external.write_bytes(_session_jsonl("thread-1"))
    root = tmp_path / "sync"
    conversations = root / "conversations"
    conversations.mkdir(parents=True)
    link = conversations / "thread-1.jsonl"
    _symlink_or_skip(link, external)
    before = external.read_bytes()

    with pytest.raises(MalformedSyncIndexError, match="symlink"):
        RemoteStore(root).load_inventory()

    assert external.read_bytes() == before
    assert link.is_symlink()
    assert not (root / "sync-index.json").exists()


def test_remote_store_rejects_symlinked_conversations_directory_without_external_reads(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external"
    external.mkdir()
    external_file = external / "thread-1.jsonl"
    external_file.write_bytes(_session_jsonl("thread-1"))
    root = tmp_path / "sync"
    root.mkdir()
    _symlink_or_skip(root / "conversations", external, target_is_directory=True)
    before = external_file.read_bytes()

    with pytest.raises(MalformedSyncIndexError, match="symlink"):
        RemoteStore(root).load_inventory()

    assert external_file.read_bytes() == before
    assert not (root / "sync-index.json").exists()


def test_remote_store_rejects_simulated_conversations_junction_before_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sync"
    conversations = root / "conversations"
    conversations.mkdir(parents=True)
    marker = conversations / "thread-1.jsonl"
    marker_bytes = _session_jsonl("thread-1")
    marker.write_bytes(marker_bytes)
    original_lstat = Path.lstat
    original_iterdir = Path.iterdir
    enumeration_attempts = 0

    def mount_point_lstat(path: Path) -> Any:
        if path == conversations:
            result = original_lstat(path)
            return SimpleNamespace(
                st_mode=result.st_mode,
                st_reparse_tag=_WINDOWS_MOUNT_POINT_REPARSE_TAG,
            )
        return original_lstat(path)

    def reject_enumeration(path: Path) -> Any:
        nonlocal enumeration_attempts
        if path == conversations:
            enumeration_attempts += 1
            raise AssertionError("junction contents must not be enumerated")
        return original_iterdir(path)

    monkeypatch.setattr(
        stat,
        "IO_REPARSE_TAG_MOUNT_POINT",
        _WINDOWS_MOUNT_POINT_REPARSE_TAG,
        raising=False,
    )
    monkeypatch.setattr(Path, "lstat", mount_point_lstat)
    monkeypatch.setattr(Path, "iterdir", reject_enumeration)

    with pytest.raises(MalformedSyncIndexError, match="junction"):
        RemoteStore(root).load_inventory()

    assert enumeration_attempts == 0
    assert marker.read_bytes() == marker_bytes


@pytest.mark.parametrize(
    ("mode", "reparse_tag", "expected_kind"),
    [
        (stat.S_IFDIR | 0o755, _WINDOWS_MOUNT_POINT_REPARSE_TAG, "junction"),
        (stat.S_IFLNK | 0o777, _WINDOWS_MOUNT_POINT_REPARSE_TAG, "symlink"),
        (stat.S_IFDIR | 0o755, None, "directory"),
    ],
    ids=["mount-point", "true-symlink", "posix-directory"],
)
def test_path_kind_uses_one_lstat_result_for_reparse_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: int,
    reparse_tag: int | None,
    expected_kind: str,
) -> None:
    path = tmp_path / "entry"
    attempts = 0

    def injected_lstat(candidate: Path) -> Any:
        nonlocal attempts
        assert candidate == path
        attempts += 1
        values: dict[str, Any] = {"st_mode": mode}
        if reparse_tag is not None:
            values["st_reparse_tag"] = reparse_tag
        return SimpleNamespace(**values)

    monkeypatch.setattr(
        stat,
        "IO_REPARSE_TAG_MOUNT_POINT",
        _WINDOWS_MOUNT_POINT_REPARSE_TAG,
        raising=False,
    )
    monkeypatch.setattr(Path, "lstat", injected_lstat)

    assert sync_io.path_kind(path) == expected_kind
    assert attempts == 1


@pytest.mark.skipif(os.name != "nt", reason="native junctions are Windows-only")
def test_path_kind_classifies_available_native_windows_junction() -> None:
    user_profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
    program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    candidates = (
        user_profile / "Application Data",
        user_profile / "Local Settings",
        user_profile / "My Documents",
        program_data / "Application Data",
    )
    mount_point_tag = stat.IO_REPARSE_TAG_MOUNT_POINT

    def reparse_tag(candidate: Path) -> int | None:
        try:
            return getattr(candidate.lstat(), "st_reparse_tag", None)
        except OSError:
            return None

    junction = next(
        (
            candidate
            for candidate in candidates
            if reparse_tag(candidate) == mount_point_tag
        ),
        None,
    )
    if junction is None:
        pytest.skip("no standard native Windows junction is available to this CI account")

    assert sync_io.path_kind(junction) == "junction"


def test_validate_selected_rejects_conversations_directory_swapped_to_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    inventory = _materialized_inventory(store, entry.thread_id)
    external = tmp_path / "external-conversations"
    (root / "conversations").rename(external)
    _symlink_or_skip(root / "conversations", external, target_is_directory=True)
    external_path = external / portable_thread_filename(entry.thread_id)
    before = external_path.read_bytes()

    with pytest.raises(MalformedSyncIndexError, match="directory must not be a symlink"):
        store.validate_selected(
            {entry.thread_id: entry},
            {entry.thread_id: inventory.files[entry.thread_id]},
        )

    assert external_path.read_bytes() == before


def test_remote_store_supports_root_below_symlinked_parent(tmp_path: Path) -> None:
    actual_parent = tmp_path / "actual"
    actual_parent.mkdir()
    visible_parent = tmp_path / "visible"
    _symlink_or_skip(visible_parent, actual_parent, target_is_directory=True)
    root = visible_parent / "sync"
    path = root / "conversations" / "thread-1.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(_session_jsonl("thread-1"))

    inventory = RemoteStore(root).load_inventory()

    assert tuple(inventory.index.threads) == ("thread-1",)
    assert inventory.files["thread-1"].path == path


@pytest.mark.parametrize("operation", ["inspection", "enumeration"])
def test_remote_store_retries_transient_directory_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    root = tmp_path / "sync"
    conversations = root / "conversations"
    conversations.mkdir(parents=True)
    attempts = 0

    if operation == "inspection":
        original = Path.lstat

        def flaky(path: Path) -> object:
            nonlocal attempts
            if path == conversations:
                attempts += 1
                if attempts < 3:
                    raise OSError(errno.EBUSY, "cloud directory is busy")
            return original(path)

        monkeypatch.setattr(Path, "lstat", flaky)
    else:
        original_iterdir = Path.iterdir

        def flaky_iterdir(path: Path) -> object:
            nonlocal attempts
            if path == conversations:
                attempts += 1
                if attempts < 3:
                    raise OSError(errno.EBUSY, "cloud enumeration is busy")
            return original_iterdir(path)

        monkeypatch.setattr(Path, "iterdir", flaky_iterdir)

    RemoteStore(root).load_inventory()

    assert attempts == 3


@pytest.mark.parametrize("operation", ["inspection", "enumeration"])
def test_remote_store_does_not_retry_permanent_directory_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    root = tmp_path / "sync"
    conversations = root / "conversations"
    conversations.mkdir(parents=True)
    attempts = 0

    if operation == "inspection":
        original = Path.lstat

        def denied(path: Path) -> object:
            nonlocal attempts
            if path == conversations:
                attempts += 1
                raise PermissionError(errno.EACCES, "directory access denied")
            return original(path)

        monkeypatch.setattr(Path, "lstat", denied)
    else:

        def denied_iterdir(path: Path) -> object:
            nonlocal attempts
            if path == conversations:
                attempts += 1
            raise PermissionError(errno.EACCES, "directory enumeration denied")

        monkeypatch.setattr(Path, "iterdir", denied_iterdir)

    with pytest.raises(PermissionError):
        RemoteStore(root).load_inventory()

    assert attempts == 1


def test_remote_store_write_conversation_preserves_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    source.write_bytes(b'{"type":"session_meta"}\n\xff\x00')
    store = RemoteStore(tmp_path / "sync")
    target = tmp_path / "sync" / "conversations" / "thread-1.jsonl"

    with store.transaction():
        written = store.write_conversation(
            source,
            "thread-1.jsonl",
            SyncFileSnapshot(target, False),
        )

    assert target.read_bytes() == source.read_bytes()
    assert written == snapshot_file(target)


@pytest.mark.parametrize(
    "filename",
    [
        "../escape.jsonl",
        "nested/thread.jsonl",
        "/tmp/thread.jsonl",
        "CON.jsonl",
        "Mixed-Case.jsonl",
    ],
)
def test_remote_store_write_conversation_rejects_non_filename_targets(
    tmp_path: Path,
    filename: str,
) -> None:
    source = tmp_path / "source.jsonl"
    source.write_bytes(b"{}\n")
    store = RemoteStore(tmp_path / "sync")
    expected = SyncFileSnapshot(tmp_path / "sync" / "conversations" / filename, False)

    with store.transaction():
        with pytest.raises(ValueError, match="direct JSONL filename"):
            store.write_conversation(source, filename, expected)

    assert not (tmp_path / "sync").exists()


def test_write_conversation_rejects_target_changed_after_earlier_validation(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    base = _materialized_inventory(store, entry.thread_id)
    store.validate_selected(
        {entry.thread_id: entry},
        {entry.thread_id: base.files[entry.thread_id]},
    )
    target = root / entry.file
    concurrent = target.read_bytes() + b"external-change\n"
    target.write_bytes(concurrent)
    source = tmp_path / "source.jsonl"
    source.write_bytes(_session_jsonl("thread-1") + b"our-change\n")

    with store.transaction():
        with pytest.raises(ConcurrentRemoteChangeError, match="before conversation replacement"):
            store.write_conversation(
                source,
                portable_thread_filename("thread-1"),
                base.files[entry.thread_id],
            )

    assert target.read_bytes() == concurrent


def test_write_conversation_verifies_bytes_after_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sync"
    store = RemoteStore(root)
    source = tmp_path / "source.jsonl"
    source.write_bytes(_session_jsonl("thread-1"))
    target = root / "conversations" / "thread-1.jsonl"
    original_replace = Path.replace

    def replace_then_change(path: Path, destination: Path) -> Path:
        result = original_replace(path, destination)
        if destination == target:
            destination.write_bytes(b"external-after-replace\n")
        return result

    monkeypatch.setattr(Path, "replace", replace_then_change)

    with store.transaction():
        with pytest.raises(ConcurrentRemoteChangeError, match="after conversation replacement"):
            store.write_conversation(source, target.name, SyncFileSnapshot(target, False))

    assert target.read_bytes() == b"external-after-replace\n"


def test_write_conversation_revalidates_target_before_replace_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    base = _materialized_inventory(store, entry.thread_id)
    source = tmp_path / "source.jsonl"
    source.write_bytes(_session_jsonl("thread-1") + b"our-change\n")
    target = root / entry.file
    concurrent = target.read_bytes() + b"external-during-retry\n"
    original_replace = Path.replace
    attempts = 0

    def transient_then_external_change(path: Path, destination: Path) -> Path:
        nonlocal attempts
        if destination == target:
            attempts += 1
            if attempts == 1:
                target.write_bytes(concurrent)
                raise OSError(errno.EBUSY, "cloud replacement is busy")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", transient_then_external_change)

    with store.transaction():
        with pytest.raises(ConcurrentRemoteChangeError, match="before conversation replacement"):
            store.write_conversation(
                source,
                portable_thread_filename(entry.thread_id),
                base.files[entry.thread_id],
            )

    assert attempts == 1
    assert target.read_bytes() == concurrent


def test_write_conversation_rejects_directory_symlink_swap_before_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    base = _materialized_inventory(store, entry.thread_id)
    source = tmp_path / "source.jsonl"
    source.write_bytes(_session_jsonl("thread-1") + b"our-change\n")
    conversations = root / "conversations"
    target = conversations / portable_thread_filename(entry.thread_id)
    external = tmp_path / "external-conversations"
    before = target.read_bytes()
    original_replace_if_expected = sync_io._replace_if_expected

    def swap_before_guarded_replace(
        temporary: Path,
        destination: Path,
        expected: SyncFileSnapshot,
        target_label: str,
        *,
        path_guard: Any = None,
    ) -> None:
        conversations.rename(external)
        _symlink_or_skip(conversations, external, target_is_directory=True)
        if path_guard is None:
            original_replace_if_expected(temporary, destination, expected, target_label)
        else:
            original_replace_if_expected(
                temporary,
                destination,
                expected,
                target_label,
                path_guard=path_guard,
            )

    monkeypatch.setattr(sync_io, "_replace_if_expected", swap_before_guarded_replace)

    with store.transaction():
        with pytest.raises(MalformedSyncIndexError, match="directory must not be a symlink"):
            store.write_conversation(
                source,
                target.name,
                base.files[entry.thread_id],
            )

    assert (external / target.name).read_bytes() == before


def test_write_conversation_rejects_directory_symlink_swap_before_replace_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    base = _materialized_inventory(store, entry.thread_id)
    source = tmp_path / "source.jsonl"
    source.write_bytes(_session_jsonl("thread-1") + b"our-change\n")
    conversations = root / "conversations"
    target = conversations / portable_thread_filename(entry.thread_id)
    external = tmp_path / "external-conversations"
    before = target.read_bytes()
    original_replace = Path.replace
    attempts = 0

    def swap_then_transient_error(path: Path, destination: Path) -> Path:
        nonlocal attempts
        if destination == target:
            attempts += 1
            if attempts == 1:
                conversations.rename(external)
                _symlink_or_skip(conversations, external, target_is_directory=True)
                raise OSError(errno.EBUSY, "cloud replacement is busy")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", swap_then_transient_error)

    with store.transaction():
        with pytest.raises(MalformedSyncIndexError, match="directory must not be a symlink"):
            store.write_conversation(
                source,
                target.name,
                base.files[entry.thread_id],
            )

    assert attempts == 1
    assert (external / target.name).read_bytes() == before


def test_validate_selected_detects_selected_index_change(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    inventory = _materialized_inventory(store, entry.thread_id)
    changed = replace(entry, project_label="changed elsewhere")
    _write_index(root, {changed.thread_id: changed}, updated_at="after")

    with pytest.raises(ConcurrentRemoteChangeError, match="index entry"):
        RemoteStore(root).validate_selected(
            {entry.thread_id: entry},
            {entry.thread_id: inventory.files[entry.thread_id]},
        )


def test_validate_selected_detects_selected_file_change(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    inventory = _materialized_inventory(store, entry.thread_id)
    (root / entry.file).write_bytes(_session_jsonl("thread-1") + b"changed\n")

    with pytest.raises(ConcurrentRemoteChangeError, match="conversation file"):
        RemoteStore(root).validate_selected(
            {entry.thread_id: entry},
            {entry.thread_id: inventory.files[entry.thread_id]},
        )


def test_validate_selected_ignores_unrelated_index_and_file_changes(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    selected = _write_indexed_conversation(root, "thread-1")
    unrelated = _write_indexed_conversation(root, "thread-2")
    _write_index(root, {selected.thread_id: selected, unrelated.thread_id: unrelated})
    store = RemoteStore(root)
    inventory = _materialized_inventory(store, selected.thread_id)
    unrelated_path = root / unrelated.file
    unrelated_path.write_bytes(unrelated_path.read_bytes() + b"changed\n")
    unrelated_snapshot = snapshot_file(unrelated_path)
    unrelated = replace(
        unrelated,
        sha256=unrelated_snapshot.sha256,
        size_bytes=unrelated_snapshot.size_bytes,
    )
    _write_index(root, {selected.thread_id: selected, unrelated.thread_id: unrelated}, updated_at="after")

    RemoteStore(root).validate_selected(
        {selected.thread_id: selected},
        {selected.thread_id: inventory.files[selected.thread_id]},
    )


def test_read_index_classifies_disappearance_after_visible_snapshot_as_concurrent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    visible = snapshot_file(root / "sync-index.json")
    (root / "sync-index.json").unlink()

    with pytest.raises(ConcurrentRemoteChangeError, match="changed after its visible snapshot"):
        store._read_index(visible)


def test_read_index_classifies_malformed_change_after_visible_snapshot_as_concurrent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    visible = snapshot_file(root / "sync-index.json")
    (root / "sync-index.json").write_bytes(b"{changed-and-malformed\n")

    with pytest.raises(ConcurrentRemoteChangeError, match="changed after its visible snapshot"):
        store._read_index(visible)


def test_commit_index_rejects_change_after_latest_merge_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    base = _materialized_inventory(store, entry.thread_id)
    concurrent = RemoteIndex(
        format_version=2,
        updated_at="external",
        threads={entry.thread_id: replace(entry, project_label="external")},
    )
    concurrent_bytes = (json.dumps(concurrent.to_dict(), indent=2, sort_keys=True) + "\n").encode()
    original_atomic_write = sync_store.atomic_write_json

    def change_before_guarded_write(
        path: Path,
        value: dict[str, Any],
        *,
        expected_target: SyncFileSnapshot | None = None,
        target_label: str = "file",
        path_guard: Any = None,
    ) -> object:
        path.write_bytes(concurrent_bytes)
        if expected_target is None:
            return original_atomic_write(
                path,
                value,
                target_label=target_label,
                path_guard=path_guard,
            )
        return original_atomic_write(
            path,
            value,
            expected_target=expected_target,
            target_label=target_label,
            path_guard=path_guard,
        )

    monkeypatch.setattr(sync_store, "atomic_write_json", change_before_guarded_write)

    with store.transaction():
        with pytest.raises(ConcurrentRemoteChangeError, match="before index replacement"):
            _commit_index(store, base, {entry.thread_id: replace(entry, exported_at="ours")}, {})

    assert (root / "sync-index.json").read_bytes() == concurrent_bytes


def test_commit_index_rejects_index_symlink_swap_after_latest_merge_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    base = _materialized_inventory(store, entry.thread_id)
    index_path = root / "sync-index.json"
    external = tmp_path / "external-index.json"
    external.write_bytes(index_path.read_bytes())
    before = external.read_bytes()
    original_index = tmp_path / "original-index.json"
    original_atomic_write = sync_store.atomic_write_json

    def swap_before_guarded_write(
        path: Path,
        value: dict[str, Any],
        *,
        expected_target: SyncFileSnapshot | None = None,
        target_label: str = "file",
        path_guard: Any = None,
    ) -> object:
        path.rename(original_index)
        _symlink_or_skip(path, external)
        return original_atomic_write(
            path,
            value,
            expected_target=expected_target,
            target_label=target_label,
            path_guard=path_guard,
        )

    monkeypatch.setattr(sync_store, "atomic_write_json", swap_before_guarded_write)

    with store.transaction():
        with pytest.raises(MalformedSyncIndexError, match="sync-index.json.*symlink"):
            _commit_index(store, base, {entry.thread_id: replace(entry, exported_at="ours")}, {})

    assert external.read_bytes() == before
    assert original_index.read_bytes() == before


def test_commit_index_verifies_bytes_after_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    base = _materialized_inventory(store, entry.thread_id)
    index_path = root / "sync-index.json"
    original_replace = Path.replace

    def replace_then_change(path: Path, destination: Path) -> Path:
        result = original_replace(path, destination)
        if destination == index_path:
            destination.write_bytes(b'{"external":true}\n')
        return result

    monkeypatch.setattr(Path, "replace", replace_then_change)

    with store.transaction():
        with pytest.raises(ConcurrentRemoteChangeError, match="after index replacement"):
            _commit_index(store, base, {entry.thread_id: replace(entry, exported_at="ours")}, {})

    assert index_path.read_bytes() == b'{"external":true}\n'


def test_commit_index_merges_unrelated_latest_entries_without_deleting(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    selected = _write_indexed_conversation(root, "thread-1")
    retained = _write_indexed_conversation(root, "thread-2")
    _write_index(root, {selected.thread_id: selected, retained.thread_id: retained})
    store = RemoteStore(root)
    base = _materialized_inventory(store, selected.thread_id)

    source = tmp_path / "selected-source.jsonl"
    source.write_bytes(_session_jsonl("thread-1") + b'{"type":"response_item"}\n')
    with store.transaction():
        selected_written = store.write_conversation(
            source,
            portable_thread_filename("thread-1"),
            base.files[selected.thread_id],
        )
        selected_changed = replace(
            selected,
            sha256=selected_written.sha256,
            size_bytes=selected_written.size_bytes,
            exported_at="after",
        )

        added = _write_indexed_conversation(root, "thread-3")
        retained_latest = replace(retained, project_label="updated elsewhere")
        _write_index(
            root,
            {
                selected.thread_id: selected,
                retained_latest.thread_id: retained_latest,
                added.thread_id: added,
            },
            updated_at="concurrent",
        )

        committed = _commit_index(
            store,
            base,
            {selected.thread_id: selected_changed},
            {selected.thread_id: selected_written},
        )

    assert committed.threads == {
        selected.thread_id: selected_changed,
        retained_latest.thread_id: retained_latest,
        added.thread_id: added,
    }
    assert RemoteIndex.from_dict(read_json_object(root / "sync-index.json") or {}) == committed
    assert (root / retained.file).is_file()
    assert (root / added.file).is_file()


def test_commit_index_preserves_unrelated_base_entry_omitted_from_stale_latest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sync"
    selected = _write_indexed_conversation(root, "thread-1")
    unrelated = _write_indexed_conversation(root, "thread-2")
    _write_index(root, {selected.thread_id: selected, unrelated.thread_id: unrelated})
    store = RemoteStore(root)
    base = _materialized_inventory(store, selected.thread_id)

    _write_index(root, {selected.thread_id: selected}, updated_at="stale-latest")
    selected_changed = replace(selected, exported_at="ours")
    with store.transaction():
        committed = _commit_index(
            store,
            base,
            {selected.thread_id: selected_changed},
            {},
        )

    assert committed.threads == {
        selected.thread_id: selected_changed,
        unrelated.thread_id: unrelated,
    }
    assert RemoteIndex.from_dict(read_json_object(root / "sync-index.json") or {}) == committed
    assert (root / unrelated.file).is_file()


def test_commit_index_persists_safe_inventory_repairs(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    path = root / "conversations" / "orphan.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(_session_jsonl("thread-1"))
    store = RemoteStore(root)
    base = store.load_inventory()

    with store.transaction():
        committed = _commit_index(store, base, {}, {})

    assert committed.threads == base.index.threads
    assert RemoteIndex.from_dict(read_json_object(root / "sync-index.json") or {}) == committed
    assert path.read_bytes() == _session_jsonl("thread-1")


def test_commit_index_detects_selected_entry_change_after_planning(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    base = _materialized_inventory(store, entry.thread_id)
    concurrent = replace(entry, project_label="concurrent")
    _write_index(root, {entry.thread_id: concurrent}, updated_at="concurrent")

    with store.transaction():
        with pytest.raises(ConcurrentRemoteChangeError, match="index entry"):
            _commit_index(store, base, {entry.thread_id: replace(entry, exported_at="after")}, {})

    assert RemoteIndex.from_dict(read_json_object(root / "sync-index.json") or {}).threads == {
        entry.thread_id: concurrent
    }


def test_commit_index_detects_selected_entry_disappearance_after_planning(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    base = _materialized_inventory(store, entry.thread_id)
    _write_index(root, {}, updated_at="concurrent-removal")

    with store.transaction():
        with pytest.raises(ConcurrentRemoteChangeError, match="index entry"):
            _commit_index(store, base, {entry.thread_id: replace(entry, exported_at="after")}, {})

    assert RemoteIndex.from_dict(read_json_object(root / "sync-index.json") or {}).threads == {}


def test_commit_index_detects_selected_unwritten_file_change(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    base = _materialized_inventory(store, entry.thread_id)
    path = root / entry.file
    path.write_bytes(path.read_bytes() + b"concurrent\n")

    with store.transaction():
        with pytest.raises(ConcurrentRemoteChangeError, match="conversation file"):
            _commit_index(store, base, {entry.thread_id: replace(entry, exported_at="after")}, {})


def test_commit_index_detects_written_file_change_before_commit(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    base = _materialized_inventory(store, entry.thread_id)
    source = tmp_path / "source.jsonl"
    source.write_bytes(_session_jsonl("thread-1") + b"written\n")
    with store.transaction():
        written = store.write_conversation(
            source,
            portable_thread_filename("thread-1"),
            base.files[entry.thread_id],
        )
        changed = replace(entry, sha256=written.sha256, size_bytes=written.size_bytes)
        (root / entry.file).write_bytes(source.read_bytes() + b"concurrent\n")

        with pytest.raises(ConcurrentRemoteChangeError, match="written conversation file"):
            _commit_index(store, base, {entry.thread_id: changed}, {entry.thread_id: written})


def test_commit_index_rejects_unwritten_entry_pointing_to_another_file(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    entry = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {entry.thread_id: entry})
    store = RemoteStore(root)
    base = _materialized_inventory(store, entry.thread_id)
    redirected = replace(entry, file="conversations/other.jsonl")
    before = (root / "sync-index.json").read_bytes()

    with store.transaction():
        with pytest.raises(ValueError, match="snapshot path does not match"):
            _commit_index(store, base, {entry.thread_id: redirected}, {})

    assert (root / "sync-index.json").read_bytes() == before


def test_commit_index_rejects_duplicate_filename_before_writing(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    retained = _write_indexed_conversation(root, "thread-1")
    _write_index(root, {retained.thread_id: retained})
    store = RemoteStore(root)
    base = store.load_inventory()
    duplicate = replace(_remote_entry("thread-2"), file=retained.file)
    before = (root / "sync-index.json").read_bytes()

    with store.transaction():
        with pytest.raises(MalformedSyncIndexError, match="same remote file"):
            _commit_index(store, base, {duplicate.thread_id: duplicate}, {})

    assert (root / "sync-index.json").read_bytes() == before
