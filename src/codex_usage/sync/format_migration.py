from __future__ import annotations

import errno
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from codex_usage.sync.constants import (
    LEGACY_REMOTE_TRANSFER_FORMAT_VERSION,
    LEGACY_TRANSFER_CONVERSATIONS_DIRNAME,
    REMOTE_TRANSFER_FORMAT_VERSION,
    SYNC_INDEX_FILENAME,
    TRANSFER_TASKS_DIRNAME,
)
from codex_usage.sync.errors import (
    ConcurrentRemoteChangeError,
    MalformedSyncIndexError,
    TransferFormatMigrationError,
)
from codex_usage.sync.format_migration_cleanup import (
    CleanupAuthority as _CleanupAuthority,
    prepare_cleanup as _prepare_cleanup,
    validate_cleanup_boundary as _validate_cleanup_boundary,
)
from codex_usage.sync.format_migration_layout import (
    LayoutScan as _LayoutScan,
    guard_index as _guard_index,
    guard_legacy_directory as _guard_legacy_directory,
    guard_legacy_file as _guard_legacy_file,
    guard_task_file as _guard_task_file,
    jsonl_files as _jsonl_files,
    legacy_layout_error as _legacy_layout_error,
    scan_layout as _scan_layout,
    validate_file_claims as _validate_file_claims,
)
from codex_usage.sync.io import (
    atomic_copy,
    atomic_write_json,
    read_bytes_with_snapshot,
    snapshot_file,
)
from codex_usage.sync.models import RemoteIndex, RemoteInventory, SyncFileSnapshot
from codex_usage.sync.paths import portable_thread_filename
from codex_usage.sync.remote_reconciliation import (
    materialize_remote_task,
    materialize_selected_remote,
    reconcile_remote_discovery,
)


_TRANSIENT_ERRNOS = frozenset(
    value
    for name in ("EAGAIN", "EBUSY", "EINTR", "ESTALE", "ETIMEDOUT", "ETXTBSY")
    if (value := getattr(errno, name, None)) is not None
)


@dataclass(frozen=True)
class MigrationResult:
    migrated: bool
    cleaned_legacy: bool


def migrate_remote_layout_v2_to_v3(root: Path) -> MigrationResult:
    """Migrate a valid v2 transfer folder, preserving an authoritative resume state."""
    layout = _scan_layout(root)
    index_value, index_snapshot = _read_index_value(root)
    if index_value is None:
        if layout.legacy_exists:
            raise TransferFormatMigrationError(
                f"Cannot migrate {LEGACY_TRANSFER_CONVERSATIONS_DIRNAME}/ without "
                f"{SYNC_INDEX_FILENAME}"
            )
        return MigrationResult(migrated=False, cleaned_legacy=False)

    format_version = _format_version(index_value)
    if format_version == 1:
        raise _legacy_layout_error()
    if format_version == LEGACY_REMOTE_TRANSFER_FORMAT_VERSION:
        return _migrate_v2(root, index_value, index_snapshot, layout)
    if format_version == REMOTE_TRANSFER_FORMAT_VERSION:
        if not layout.legacy_exists:
            return MigrationResult(migrated=False, cleaned_legacy=False)
        index = _parse_index(index_value, REMOTE_TRANSFER_FORMAT_VERSION)
        _validate_file_claims(index, TRANSFER_TASKS_DIRNAME)
        return MigrationResult(
            migrated=False,
            cleaned_legacy=_cleanup_legacy(root, index, index_snapshot),
        )
    raise MalformedSyncIndexError(
        f"Unsupported remote transfer format version {format_version}"
    )


def _migrate_v2(
    root: Path,
    index_value: dict[str, Any],
    index_snapshot: SyncFileSnapshot,
    layout: _LayoutScan,
) -> MigrationResult:
    persisted = _parse_index(index_value, LEGACY_REMOTE_TRANSFER_FORMAT_VERSION)
    _validate_file_claims(persisted, LEGACY_TRANSFER_CONVERSATIONS_DIRNAME)
    discovered = _jsonl_files(
        layout.legacy_files,
        LEGACY_TRANSFER_CONVERSATIONS_DIRNAME,
    )
    inventory = reconcile_remote_discovery(
        root,
        persisted,
        index_snapshot,
        discovered,
        lambda path: _guard_legacy_file(root, path),
        directory_name=LEGACY_TRANSFER_CONVERSATIONS_DIRNAME,
        format_version=LEGACY_REMOTE_TRANSFER_FORMAT_VERSION,
        propagate_io_errors=True,
    )
    inventory = materialize_selected_remote(
        root,
        inventory,
        inventory.index.threads,
        lambda path: _guard_legacy_file(root, path),
        propagate_io_errors=True,
    )
    _validate_v2_inventory(inventory)
    staged = _stage_tasks(root, inventory, layout.task_files)
    expected_legacy = {entry.file for entry in inventory.index.threads.values()}
    expected_tasks = {f"{TRANSFER_TASKS_DIRNAME}/{item[0]}" for item in staged.values()}

    def validate_commit() -> None:
        _validate_v2_commit(root, staged, expected_legacy, expected_tasks)

    validate_commit()

    v3_index = RemoteIndex(
        format_version=REMOTE_TRANSFER_FORMAT_VERSION,
        updated_at=persisted.updated_at,
        threads={
            thread_id: replace(entry, file=f"{TRANSFER_TASKS_DIRNAME}/{filename}")
            for thread_id, (filename, _, _) in staged.items()
            for entry in (inventory.index.threads[thread_id],)
        },
    )
    atomic_write_json(
        root / SYNC_INDEX_FILENAME,
        v3_index.to_dict(),
        expected_target=index_snapshot,
        target_label="index",
        path_guard=validate_commit,
    )

    committed_value, committed_snapshot = _read_index_value(root)
    if committed_value is None:
        raise ConcurrentRemoteChangeError(
            "Remote index disappeared after migration commit"
        )
    committed = _parse_index(committed_value, REMOTE_TRANSFER_FORMAT_VERSION)
    committed_layout = _scan_layout(root)
    cleaned = (
        _cleanup_legacy(root, committed, committed_snapshot)
        if committed_layout.legacy_exists
        else False
    )
    return MigrationResult(migrated=True, cleaned_legacy=cleaned)


def _validate_v2_commit(
    root: Path,
    staged: dict[str, tuple[str, SyncFileSnapshot, SyncFileSnapshot]],
    expected_legacy: set[str],
    expected_tasks: set[str],
) -> None:
    layout = _scan_layout(root)
    if (
        set(layout.legacy_files) != expected_legacy
        or set(layout.task_files) != expected_tasks
    ):
        raise ConcurrentRemoteChangeError(
            "Remote layout changed before migration commit"
        )
    for _, source, target in staged.values():
        if source.path is None or target.path is None:
            raise TransferFormatMigrationError("Migration lost a verified task path")
        _guard_legacy_file(root, source.path)
        _guard_task_file(root, target.path)
        if snapshot_file(source.path) != source or snapshot_file(target.path) != target:
            raise ConcurrentRemoteChangeError(
                "Remote task changed before migration commit"
            )


def _validate_v2_inventory(inventory: RemoteInventory) -> None:
    if inventory.issues:
        details = "; ".join(issue.message for issue in inventory.issues)
        raise TransferFormatMigrationError(
            f"Version-2 migration validation failed: {details}"
        )

    _validate_file_claims(inventory.index, LEGACY_TRANSFER_CONVERSATIONS_DIRNAME)
    for thread_id, entry in inventory.index.threads.items():
        snapshot = inventory.files.get(thread_id)
        if snapshot is None or not snapshot.exists:
            raise TransferFormatMigrationError(f"Remote task {entry.file} is missing")
        persisted_entry = inventory.persisted_index.threads.get(thread_id)
        if persisted_entry is None or persisted_entry.file != entry.file:
            continue
        mismatches: list[str] = []
        if persisted_entry.sha256 != snapshot.sha256:
            mismatches.append("sha256")
        if persisted_entry.size_bytes != snapshot.size_bytes:
            mismatches.append("size_bytes")
        if mismatches:
            fields = " and ".join(mismatches)
            raise TransferFormatMigrationError(
                f"Remote task {entry.file} does not match indexed {fields}"
            )


def _stage_tasks(
    root: Path,
    inventory: RemoteInventory,
    existing_task_files: dict[str, Path],
) -> dict[str, tuple[str, SyncFileSnapshot, SyncFileSnapshot]]:
    staged: dict[str, tuple[str, SyncFileSnapshot, SyncFileSnapshot]] = {}
    target_owners: dict[str, str] = {}
    for thread_id, entry in inventory.index.threads.items():
        filename = portable_thread_filename(thread_id)
        target_key = filename.casefold()
        owner = target_owners.setdefault(target_key, thread_id)
        if owner != thread_id:
            raise TransferFormatMigrationError(
                f"Threads {owner!r} and {thread_id!r} map to the same tasks/{filename}"
            )
        source_snapshot = inventory.files[thread_id]
        target = root / TRANSFER_TASKS_DIRNAME / filename
        staged[thread_id] = (
            filename,
            source_snapshot,
            SyncFileSnapshot(path=target, exists=False),
        )

    expected_paths = {f"{TRANSFER_TASKS_DIRNAME}/{item[0]}" for item in staged.values()}
    unexpected = sorted(existing_task_files.keys() - expected_paths)
    if unexpected:
        raise TransferFormatMigrationError(
            f"Unrepresented staged task {unexpected[0]} blocks version-2 migration"
        )

    for thread_id, (filename, source_snapshot, _) in staged.items():
        relative_path = f"{TRANSFER_TASKS_DIRNAME}/{filename}"
        target = root / relative_path
        if relative_path not in existing_task_files:
            continue
        target_snapshot, metadata = materialize_remote_task(
            target,
            lambda path: _guard_task_file(root, path),
            propagate_io_errors=True,
        )
        if target_snapshot != replace(source_snapshot, path=target) or (
            metadata is None or metadata.session_id != thread_id
        ):
            raise TransferFormatMigrationError(
                f"Staged task {relative_path} differs from verified source"
            )
        staged[thread_id] = (filename, source_snapshot, target_snapshot)

    for thread_id, (filename, source_snapshot, target_snapshot) in tuple(
        staged.items()
    ):
        if target_snapshot.exists:
            continue
        source = inventory.files[thread_id].path
        if source is None:
            raise TransferFormatMigrationError(
                f"Missing verified source for thread {thread_id!r}"
            )
        target = root / TRANSFER_TASKS_DIRNAME / filename
        copied = atomic_copy(
            source,
            target,
            expected_target=target_snapshot,
            target_label="task",
            path_guard=lambda target=target: _guard_task_file(root, target),
        )
        verified, metadata = materialize_remote_task(
            target,
            lambda path: _guard_task_file(root, path),
            propagate_io_errors=True,
        )
        if copied != verified or verified != replace(source_snapshot, path=target):
            raise TransferFormatMigrationError(
                f"Staged task tasks/{filename} does not match verified source bytes"
            )
        if metadata is None or metadata.session_id != thread_id:
            raise TransferFormatMigrationError(
                f"Staged task tasks/{filename} has the wrong task identity"
            )
        staged[thread_id] = (filename, source_snapshot, verified)
    return staged


def _cleanup_legacy(
    root: Path,
    index: RemoteIndex,
    index_snapshot: SyncFileSnapshot,
) -> bool:
    layout = _scan_layout(root)
    if not layout.legacy_exists:
        return False
    authority, verified_legacy = _prepare_cleanup(
        root,
        index,
        index_snapshot,
        layout,
    )
    pending_legacy = dict(verified_legacy)
    for relative_path in tuple(pending_legacy):
        expected = pending_legacy[relative_path]
        if expected.path is None:
            raise TransferFormatMigrationError("Legacy cleanup lost a verified path")
        _unlink(
            expected.path,
            root=root,
            authority=authority,
            expected_legacy=dict(pending_legacy),
        )
        del pending_legacy[relative_path]
    _rmdir(
        root / LEGACY_TRANSFER_CONVERSATIONS_DIRNAME,
        root=root,
        authority=authority,
        expected_legacy=pending_legacy,
    )
    return True


def _read_index_value(
    root: Path,
) -> tuple[dict[str, Any] | None, SyncFileSnapshot]:
    path = root / SYNC_INDEX_FILENAME
    _guard_index(root)
    contents, snapshot = read_bytes_with_snapshot(path)
    if contents is None:
        return None, snapshot
    try:
        value = json.loads(contents)
        if not isinstance(value, dict):
            raise ValueError(f"Expected a JSON object in {path}")
        return value, snapshot
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as error:
        raise MalformedSyncIndexError(
            f"Malformed {SYNC_INDEX_FILENAME}: {error}"
        ) from error


def _format_version(value: dict[str, Any]) -> int:
    version = value.get("format_version")
    if type(version) is not int:
        raise MalformedSyncIndexError(
            f"Malformed {SYNC_INDEX_FILENAME}: format_version must be an integer"
        )
    return version


def _parse_index(value: dict[str, Any], expected_version: int) -> RemoteIndex:
    try:
        return RemoteIndex.from_dict(value, expected_format_version=expected_version)
    except (ValueError, TypeError) as error:
        raise MalformedSyncIndexError(
            f"Malformed {SYNC_INDEX_FILENAME}: {error}"
        ) from error


def _is_transient_filesystem_error(error: BaseException) -> bool:
    return isinstance(error, OSError) and error.errno in _TRANSIENT_ERRNOS


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _unlink(
    path: Path,
    *,
    root: Path,
    authority: _CleanupAuthority,
    expected_legacy: dict[str, SyncFileSnapshot],
) -> None:
    _validate_cleanup_boundary(root, authority, expected_legacy)
    expected = next(
        (snapshot for snapshot in expected_legacy.values() if snapshot.path == path),
        None,
    )
    if expected is None:
        raise TransferFormatMigrationError("Legacy cleanup target was not validated")
    _guard_legacy_file(root, path)
    if snapshot_file(path) != expected:
        raise ConcurrentRemoteChangeError(
            f"Legacy task {path.name} changed before cleanup"
        )
    path.unlink()


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _rmdir(
    path: Path,
    *,
    root: Path,
    authority: _CleanupAuthority,
    expected_legacy: dict[str, SyncFileSnapshot],
) -> None:
    _validate_cleanup_boundary(root, authority, expected_legacy)
    _guard_legacy_directory(root, path)
    path.rmdir()
