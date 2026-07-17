from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codex_usage.sync.constants import (
    LEGACY_TRANSFER_CONVERSATIONS_DIRNAME,
    SYNC_INDEX_FILENAME,
    TRANSFER_TASKS_DIRNAME,
)
from codex_usage.sync.errors import (
    ConcurrentRemoteChangeError,
    TransferFormatMigrationError,
)
from codex_usage.sync.format_migration_layout import (
    LayoutScan,
    guard_index,
    guard_legacy_file,
    guard_task_file,
    jsonl_files,
    scan_layout,
    validate_file_claims,
)
from codex_usage.sync.io import snapshot_file
from codex_usage.sync.models import RemoteIndex, SyncFileSnapshot
from codex_usage.sync.remote_reconciliation import materialize_remote_task


@dataclass(frozen=True)
class CleanupAuthority:
    index_snapshot: SyncFileSnapshot
    task_snapshots: dict[str, SyncFileSnapshot]


def prepare_cleanup(
    root: Path,
    index: RemoteIndex,
    index_snapshot: SyncFileSnapshot,
    layout: LayoutScan,
) -> tuple[CleanupAuthority, dict[str, SyncFileSnapshot]]:
    validate_file_claims(index, TRANSFER_TASKS_DIRNAME)
    indexed_paths = {entry.file for entry in index.threads.values()}
    task_files = jsonl_files(layout.task_files, TRANSFER_TASKS_DIRNAME)
    if set(task_files) != indexed_paths:
        unexpected = sorted(set(task_files) - indexed_paths)
        missing = sorted(indexed_paths - set(task_files))
        path = (unexpected or missing)[0]
        raise TransferFormatMigrationError(
            f"Version-3 task {path} is not represented consistently by the index"
        )

    task_snapshots: dict[str, SyncFileSnapshot] = {}
    for thread_id, entry in index.threads.items():
        snapshot, metadata = materialize_remote_task(
            root / entry.file,
            lambda path: guard_task_file(root, path),
            propagate_io_errors=True,
        )
        if metadata is None or metadata.session_id != thread_id:
            raise TransferFormatMigrationError(
                f"Version-3 task {entry.file} has no matching readable task identity"
            )
        if (snapshot.sha256, snapshot.size_bytes) != (entry.sha256, entry.size_bytes):
            raise TransferFormatMigrationError(
                f"Version-3 task {entry.file} does not match its indexed fingerprint"
            )
        task_snapshots[entry.file] = snapshot

    legacy_files = jsonl_files(
        layout.legacy_files,
        LEGACY_TRANSFER_CONVERSATIONS_DIRNAME,
    )
    verified_legacy: dict[str, SyncFileSnapshot] = {}
    legacy_owners: dict[str, str] = {}
    for relative_path, path in legacy_files.items():
        snapshot, metadata = materialize_remote_task(
            path,
            lambda candidate: guard_legacy_file(root, candidate),
            propagate_io_errors=True,
        )
        if metadata is None or metadata.session_id not in index.threads:
            raise TransferFormatMigrationError(
                f"Legacy task {relative_path} is not represented by the version-3 index"
            )
        owner_path = legacy_owners.setdefault(metadata.session_id, relative_path)
        if owner_path != relative_path:
            raise TransferFormatMigrationError(
                f"Legacy tasks {owner_path} and {relative_path} claim the same task identity"
            )
        task_path = index.threads[metadata.session_id].file
        expected = task_snapshots[task_path]
        if (snapshot.sha256, snapshot.size_bytes) != (
            expected.sha256,
            expected.size_bytes,
        ):
            raise TransferFormatMigrationError(
                f"Legacy task {relative_path} differs from {task_path}"
            )
        verified_legacy[relative_path] = snapshot

    return CleanupAuthority(index_snapshot, task_snapshots), verified_legacy


def validate_cleanup_boundary(
    root: Path,
    authority: CleanupAuthority,
    expected_legacy: dict[str, SyncFileSnapshot],
) -> None:
    layout = scan_layout(root)
    if not layout.legacy_exists:
        raise ConcurrentRemoteChangeError(
            "Legacy directory changed before cleanup operation"
        )
    guard_index(root)
    if snapshot_file(root / SYNC_INDEX_FILENAME) != authority.index_snapshot:
        raise ConcurrentRemoteChangeError(
            "Version-3 index changed before legacy cleanup"
        )

    task_files = jsonl_files(layout.task_files, TRANSFER_TASKS_DIRNAME)
    if set(task_files) != set(authority.task_snapshots):
        raise ConcurrentRemoteChangeError(
            "Version-3 task layout changed before legacy cleanup"
        )
    for relative_path, expected in authority.task_snapshots.items():
        if expected.path is None or task_files.get(relative_path) != expected.path:
            raise ConcurrentRemoteChangeError(
                f"Version-3 task {relative_path} changed before legacy cleanup"
            )
        guard_task_file(root, expected.path)
        if snapshot_file(expected.path) != expected:
            raise ConcurrentRemoteChangeError(
                f"Version-3 task {relative_path} changed before legacy cleanup"
            )

    legacy_files = jsonl_files(
        layout.legacy_files,
        LEGACY_TRANSFER_CONVERSATIONS_DIRNAME,
    )
    if set(legacy_files) != set(expected_legacy):
        raise ConcurrentRemoteChangeError(
            "Legacy task layout changed before cleanup operation"
        )
    for relative_path, expected in expected_legacy.items():
        if expected.path is None or legacy_files.get(relative_path) != expected.path:
            raise ConcurrentRemoteChangeError(
                f"Legacy task {relative_path} changed before cleanup"
            )
        guard_legacy_file(root, expected.path)
        if snapshot_file(expected.path) != expected:
            raise ConcurrentRemoteChangeError(
                f"Legacy task {relative_path} changed before cleanup"
            )
