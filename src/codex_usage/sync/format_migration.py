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
    LegacySyncLayoutError,
    MalformedSyncIndexError,
    TransferFormatMigrationError,
)
from codex_usage.sync.io import (
    atomic_copy,
    atomic_write_json,
    list_directory,
    path_kind,
    read_bytes_with_snapshot,
    snapshot_file,
)
from codex_usage.sync.models import RemoteIndex, RemoteInventory, SyncFileSnapshot
from codex_usage.sync.paths import is_direct_task_path, portable_thread_filename
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


@dataclass(frozen=True)
class _LayoutScan:
    legacy_exists: bool
    legacy_files: dict[str, Path]
    task_files: dict[str, Path]


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
            cleaned_legacy=_cleanup_legacy(root, index, layout),
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
    )
    inventory = materialize_selected_remote(
        root,
        inventory,
        inventory.index.threads,
        lambda path: _guard_legacy_file(root, path),
    )
    _validate_v2_inventory(inventory)
    staged = _stage_tasks(root, inventory, layout.task_files)
    precommit = _scan_layout(root)
    expected_legacy = {entry.file for entry in inventory.index.threads.values()}
    expected_tasks = {f"{TRANSFER_TASKS_DIRNAME}/{item[0]}" for item in staged.values()}
    if set(precommit.legacy_files) != expected_legacy or set(precommit.task_files) != expected_tasks:
        raise ConcurrentRemoteChangeError("Remote layout changed before migration commit")
    for _, source, target in staged.values():
        if source.path is None or target.path is None:
            raise TransferFormatMigrationError("Migration lost a verified task path")
        _guard_legacy_file(root, source.path)
        _guard_task_file(root, target.path)
        if snapshot_file(source.path) != source or snapshot_file(target.path) != target:
            raise ConcurrentRemoteChangeError("Remote task changed before migration commit")

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
        path_guard=lambda: _guard_index(root),
    )

    committed_value, _ = _read_index_value(root)
    if committed_value is None:
        raise ConcurrentRemoteChangeError("Remote index disappeared after migration commit")
    committed = _parse_index(committed_value, REMOTE_TRANSFER_FORMAT_VERSION)
    committed_layout = _scan_layout(root)
    cleaned = (
        _cleanup_legacy(root, committed, committed_layout)
        if committed_layout.legacy_exists
        else False
    )
    return MigrationResult(migrated=True, cleaned_legacy=cleaned)


def _validate_v2_inventory(inventory: RemoteInventory) -> None:
    if inventory.issues:
        details = "; ".join(issue.message for issue in inventory.issues)
        raise TransferFormatMigrationError(f"Version-2 migration validation failed: {details}")

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
        )
        if target_snapshot != replace(source_snapshot, path=target) or (
            metadata is None or metadata.session_id != thread_id
        ):
            raise TransferFormatMigrationError(
                f"Staged task {relative_path} differs from verified source"
            )
        staged[thread_id] = (filename, source_snapshot, target_snapshot)

    for thread_id, (filename, source_snapshot, target_snapshot) in tuple(staged.items()):
        if target_snapshot.exists:
            continue
        source = inventory.files[thread_id].path
        if source is None:
            raise TransferFormatMigrationError(f"Missing verified source for thread {thread_id!r}")
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


def _cleanup_legacy(root: Path, index: RemoteIndex, layout: _LayoutScan) -> bool:
    _validate_file_claims(index, TRANSFER_TASKS_DIRNAME)
    indexed_paths = {entry.file for entry in index.threads.values()}
    task_files = _jsonl_files(layout.task_files, TRANSFER_TASKS_DIRNAME)
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
            lambda path: _guard_task_file(root, path),
        )
        if metadata is None or metadata.session_id != thread_id:
            raise TransferFormatMigrationError(
                f"Version-3 task {entry.file} has no matching readable task identity"
            )
        if (snapshot.sha256, snapshot.size_bytes) != (entry.sha256, entry.size_bytes):
            raise TransferFormatMigrationError(
                f"Version-3 task {entry.file} does not match its indexed fingerprint"
            )
        task_snapshots[thread_id] = snapshot

    legacy_files = _jsonl_files(
        layout.legacy_files,
        LEGACY_TRANSFER_CONVERSATIONS_DIRNAME,
    )
    verified_legacy: list[SyncFileSnapshot] = []
    legacy_owners: dict[str, str] = {}
    for relative_path, path in legacy_files.items():
        snapshot, metadata = materialize_remote_task(
            path,
            lambda candidate: _guard_legacy_file(root, candidate),
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
        expected = task_snapshots[metadata.session_id]
        if (snapshot.sha256, snapshot.size_bytes) != (
            expected.sha256,
            expected.size_bytes,
        ):
            raise TransferFormatMigrationError(
                f"Legacy task {relative_path} differs from {index.threads[metadata.session_id].file}"
            )
        verified_legacy.append(snapshot)

    for expected in verified_legacy:
        if expected.path is None:
            raise TransferFormatMigrationError("Legacy cleanup lost a verified path")
        _guard_legacy_file(root, expected.path)
        if snapshot_file(expected.path) != expected:
            raise ConcurrentRemoteChangeError(
                f"Legacy task {expected.path.name} changed before cleanup"
            )
        _unlink(expected.path)
    _guard_directory(root / LEGACY_TRANSFER_CONVERSATIONS_DIRNAME, "conversations")
    _rmdir(root / LEGACY_TRANSFER_CONVERSATIONS_DIRNAME)
    return True


def _scan_layout(root: Path) -> _LayoutScan:
    root_kind = path_kind(root)
    if root_kind not in {"missing", "directory"}:
        raise MalformedSyncIndexError(f"Transfer folder must not be a {root_kind}")
    threads_kind = path_kind(root / "threads")
    if threads_kind != "missing":
        raise _legacy_layout_error()
    _guard_index(root)
    legacy = root / LEGACY_TRANSFER_CONVERSATIONS_DIRNAME
    tasks = root / TRANSFER_TASKS_DIRNAME
    legacy_kind = path_kind(legacy)
    task_kind = path_kind(tasks)
    if legacy_kind not in {"missing", "directory"}:
        raise MalformedSyncIndexError(
            f"conversations directory must not be a {legacy_kind}"
        )
    if task_kind not in {"missing", "directory"}:
        raise MalformedSyncIndexError(f"tasks directory must not be a {task_kind}")
    return _LayoutScan(
        legacy_exists=legacy_kind == "directory",
        legacy_files=_scan_directory(legacy, "conversations") if legacy_kind == "directory" else {},
        task_files=_scan_directory(tasks, "tasks") if task_kind == "directory" else {},
    )


def _scan_directory(path: Path, label: str) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for child in list_directory(path):
        kind = path_kind(child)
        if kind != "file":
            raise MalformedSyncIndexError(
                f"{label} entry {child.name} must not be a {kind}"
            )
        files[f"{label}/{child.name}"] = child
    return files


def _jsonl_files(files: dict[str, Path], directory: str) -> dict[str, Path]:
    invalid = sorted(path for path in files if not path.endswith(".jsonl"))
    if invalid:
        raise TransferFormatMigrationError(
            f"Unrepresented file {invalid[0]} blocks safe migration cleanup"
        )
    return files


def _validate_file_claims(index: RemoteIndex, directory: str) -> None:
    owners: dict[str, str] = {}
    for thread_id, entry in index.threads.items():
        if not is_direct_task_path(entry.file, directory):
            raise MalformedSyncIndexError(
                f"Thread {thread_id!r} file must be a relative direct child of {directory}/"
            )
        owner = owners.setdefault(entry.file.casefold(), thread_id)
        if owner != thread_id:
            raise MalformedSyncIndexError(
                f"Threads {owner!r} and {thread_id!r} claim the same remote file {entry.file!r}"
            )


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
        raise MalformedSyncIndexError(f"Malformed {SYNC_INDEX_FILENAME}: {error}") from error


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
        raise MalformedSyncIndexError(f"Malformed {SYNC_INDEX_FILENAME}: {error}") from error


def _guard_index(root: Path) -> None:
    kind = path_kind(root / SYNC_INDEX_FILENAME)
    if kind in {"symlink", "junction"}:
        raise MalformedSyncIndexError(f"{SYNC_INDEX_FILENAME} must not be a {kind}")
    if kind not in {"missing", "file"}:
        raise MalformedSyncIndexError(f"{SYNC_INDEX_FILENAME} must be a regular file")


def _guard_directory(path: Path, label: str) -> None:
    kind = path_kind(path)
    if kind != "directory":
        raise MalformedSyncIndexError(f"{label} directory must not be a {kind}")


def _guard_legacy_file(root: Path, path: Path) -> None:
    directory = root / LEGACY_TRANSFER_CONVERSATIONS_DIRNAME
    if path.parent != directory:
        raise TransferFormatMigrationError("Legacy task must stay inside conversations/")
    _guard_directory(directory, "conversations")
    kind = path_kind(path)
    if kind not in {"missing", "file"}:
        raise MalformedSyncIndexError(f"Legacy task {path.name} must not be a {kind}")


def _guard_task_file(root: Path, path: Path) -> None:
    directory = root / TRANSFER_TASKS_DIRNAME
    if path.parent != directory:
        raise TransferFormatMigrationError("Staged task must stay inside tasks/")
    kind = path_kind(directory)
    if kind not in {"missing", "directory"}:
        raise MalformedSyncIndexError(f"tasks directory must not be a {kind}")
    file_kind = path_kind(path)
    if file_kind not in {"missing", "file"}:
        raise MalformedSyncIndexError(f"Staged task {path.name} must not be a {file_kind}")


def _legacy_layout_error() -> LegacySyncLayoutError:
    return LegacySyncLayoutError(
        "Legacy version-1 sync layout detected; empty the sync folder and run sync again. "
        "Automatic migration is not supported."
    )


def _is_transient_filesystem_error(error: BaseException) -> bool:
    return isinstance(error, OSError) and error.errno in _TRANSIENT_ERRNOS


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _unlink(path: Path) -> None:
    path.unlink()


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _rmdir(path: Path) -> None:
    path.rmdir()
