from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codex_usage.sync.constants import (
    LEGACY_TRANSFER_CONVERSATIONS_DIRNAME,
    SYNC_INDEX_FILENAME,
    TRANSFER_TASKS_DIRNAME,
)
from codex_usage.sync.errors import (
    LegacySyncLayoutError,
    MalformedSyncIndexError,
    TransferFormatMigrationError,
)
from codex_usage.sync.io import list_directory, path_kind
from codex_usage.sync.models import RemoteIndex
from codex_usage.sync.paths import is_direct_task_path


@dataclass(frozen=True)
class LayoutScan:
    legacy_exists: bool
    legacy_files: dict[str, Path]
    task_files: dict[str, Path]


def scan_layout(root: Path) -> LayoutScan:
    root_kind = path_kind(root)
    if root_kind not in {"missing", "directory"}:
        raise MalformedSyncIndexError(f"Transfer folder must not be a {root_kind}")
    threads_kind = path_kind(root / "threads")
    if threads_kind != "missing":
        raise legacy_layout_error()
    guard_index(root)
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
    return LayoutScan(
        legacy_exists=legacy_kind == "directory",
        legacy_files=(
            _scan_directory(legacy, "conversations")
            if legacy_kind == "directory"
            else {}
        ),
        task_files=(
            _scan_directory(tasks, "tasks") if task_kind == "directory" else {}
        ),
    )


def jsonl_files(files: dict[str, Path], directory: str) -> dict[str, Path]:
    invalid = sorted(path for path in files if not path.endswith(".jsonl"))
    if invalid:
        raise TransferFormatMigrationError(
            f"Unrepresented file {invalid[0]} blocks safe migration cleanup"
        )
    return files


def validate_file_claims(index: RemoteIndex, directory: str) -> None:
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


def guard_index(root: Path) -> None:
    _guard_root(root, allow_missing=True)
    kind = path_kind(root / SYNC_INDEX_FILENAME)
    if kind in {"symlink", "junction"}:
        raise MalformedSyncIndexError(f"{SYNC_INDEX_FILENAME} must not be a {kind}")
    if kind not in {"missing", "file"}:
        raise MalformedSyncIndexError(f"{SYNC_INDEX_FILENAME} must be a regular file")


def guard_directory(path: Path, label: str) -> None:
    kind = path_kind(path)
    if kind != "directory":
        raise MalformedSyncIndexError(f"{label} directory must not be a {kind}")


def guard_legacy_directory(root: Path, path: Path) -> None:
    _guard_root(root)
    if path != root / LEGACY_TRANSFER_CONVERSATIONS_DIRNAME:
        raise TransferFormatMigrationError(
            "Legacy directory cleanup target must be conversations/"
        )
    guard_directory(path, "conversations")


def guard_legacy_file(root: Path, path: Path) -> None:
    _guard_root(root)
    directory = root / LEGACY_TRANSFER_CONVERSATIONS_DIRNAME
    if path.parent != directory:
        raise TransferFormatMigrationError(
            "Legacy task must stay inside conversations/"
        )
    guard_directory(directory, "conversations")
    kind = path_kind(path)
    if kind not in {"missing", "file"}:
        raise MalformedSyncIndexError(f"Legacy task {path.name} must not be a {kind}")


def guard_task_file(root: Path, path: Path) -> None:
    _guard_root(root)
    directory = root / TRANSFER_TASKS_DIRNAME
    if path.parent != directory:
        raise TransferFormatMigrationError("Staged task must stay inside tasks/")
    kind = path_kind(directory)
    if kind not in {"missing", "directory"}:
        raise MalformedSyncIndexError(f"tasks directory must not be a {kind}")
    file_kind = path_kind(path)
    if file_kind not in {"missing", "file"}:
        raise MalformedSyncIndexError(
            f"Staged task {path.name} must not be a {file_kind}"
        )


def legacy_layout_error() -> LegacySyncLayoutError:
    return LegacySyncLayoutError(
        "Legacy version-1 sync layout detected; empty the sync folder and run sync again. "
        "Automatic migration is not supported."
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


def _guard_root(root: Path, *, allow_missing: bool = False) -> None:
    kind = path_kind(root)
    if kind == "missing" and allow_missing:
        return
    if kind != "directory":
        raise MalformedSyncIndexError(f"Transfer folder must not be a {kind}")
