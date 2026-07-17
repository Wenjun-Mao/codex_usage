from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock, Timeout

from codex_usage.sync.constants import (
    REMOTE_TRANSFER_FORMAT_VERSION,
    SYNC_INDEX_FILENAME,
    TRANSFER_TASKS_DIRNAME,
)
from codex_usage.sync.errors import (
    ConcurrentRemoteChangeError,
    MalformedSyncIndexError,
)
from codex_usage.sync.format_migration import migrate_remote_layout_v2_to_v3
from codex_usage.sync.io import (
    atomic_copy,
    atomic_write_json,
    list_directory,
    path_kind,
    read_bytes_with_snapshot,
    snapshot_file,
)
from codex_usage.sync.models import (
    RemoteIndex,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
)
from codex_usage.sync.paths import (
    is_direct_jsonl_filename,
    is_direct_task_path,
    portable_thread_filename,
)
from codex_usage.sync.remote_reconciliation import (
    materialize_selected_remote,
    reconcile_remote_discovery,
)


class RemoteStore:
    """Read and update a flat, file-authoritative remote sync catalog."""

    def __init__(self, root: Path, *, lock_timeout: float = 10.0) -> None:
        self.root = root
        self.index_path = root / SYNC_INDEX_FILENAME
        self.tasks_path = root / TRANSFER_TASKS_DIRNAME
        self.lock_path = root.parent / f".{root.name}.codex-usage.lock"
        self._lock_timeout = lock_timeout
        self._lock = FileLock(self.lock_path)

    @contextmanager
    def transaction(self) -> Iterator[RemoteStore]:
        try:
            acquired = self._lock.acquire(timeout=self._lock_timeout)
        except Timeout as error:
            raise ConcurrentRemoteChangeError(
                f"Timed out acquiring remote transaction lock {self.lock_path}"
            ) from error
        with acquired:
            yield self

    def load_inventory(self) -> RemoteInventory:
        if self._lock.is_locked:
            return self._load_inventory_locked()
        with self.transaction():
            return self._load_inventory_locked()

    def _load_inventory_locked(self) -> RemoteInventory:
        self._require_transaction()
        migrate_remote_layout_v2_to_v3(self.root)
        return self._load_current_inventory()

    def _load_current_inventory(self) -> RemoteInventory:
        persisted_index, index_snapshot = self._read_index()
        discovered_files = self._list_task_files()
        return reconcile_remote_discovery(
            self.root,
            persisted_index,
            index_snapshot,
            discovered_files,
            self._guard_task_target,
            directory_name=TRANSFER_TASKS_DIRNAME,
            format_version=REMOTE_TRANSFER_FORMAT_VERSION,
        )

    def materialize_selected(
        self,
        inventory: RemoteInventory,
        selected_thread_ids: tuple[str, ...],
    ) -> RemoteInventory:
        return materialize_selected_remote(
            self.root,
            inventory,
            selected_thread_ids,
            self._guard_task_target,
        )

    def validate_selected(
        self,
        expected_entries: dict[str, RemoteThreadEntry | None],
        expected_files: dict[str, SyncFileSnapshot],
    ) -> None:
        if expected_entries.keys() != expected_files.keys():
            raise ValueError("selected remote entries and files must have the same thread ids")

        latest, _ = self._read_index()
        self._validate_selected_entries(expected_entries, latest)
        for thread_id, expected in expected_files.items():
            path = self._selected_file_path(thread_id, expected_entries[thread_id], expected)
            self._guard_task_target(path)
            actual = snapshot_file(path)
            if actual != expected:
                raise ConcurrentRemoteChangeError(
                    f"Remote task file changed after planning for thread {thread_id!r}"
                )

    def write_task(
        self,
        source: Path,
        filename: str,
        expected_target: SyncFileSnapshot,
    ) -> SyncFileSnapshot:
        self._require_transaction()
        if not is_direct_jsonl_filename(filename):
            raise ValueError("remote task target must be a direct JSONL filename")
        target = self.tasks_path / filename
        if expected_target.path != target:
            raise ValueError("expected remote task snapshot path must match target")
        self._guard_task_target(target)
        return atomic_copy(
            source,
            target,
            expected_target=expected_target,
            target_label="task",
            path_guard=lambda: self._guard_task_target(target),
        )

    def commit_index(
        self,
        base: RemoteInventory,
        changed: dict[str, RemoteThreadEntry],
        written: dict[str, SyncFileSnapshot],
        *,
        expected_entries: dict[str, RemoteThreadEntry | None],
        expected_files: dict[str, SyncFileSnapshot],
    ) -> RemoteIndex:
        self._require_transaction()
        self._validate_commit_inputs(
            base,
            changed,
            written,
            expected_entries,
            expected_files,
        )
        repaired = {
            thread_id: base.index.threads[thread_id]
            for thread_id in base.repaired_thread_ids
            if thread_id in base.index.threads
        }
        validated_entries = dict(expected_entries)
        validated_files = dict(expected_files)
        for thread_id in repaired | changed:
            validated_entries.setdefault(
                thread_id,
                base.persisted_index.threads.get(thread_id),
            )

        latest, latest_snapshot = self._read_index()
        self._validate_selected_entries(validated_entries, latest)

        merged = dict(base.index.threads)
        merged.update(latest.threads)
        merged.update(repaired)
        merged.update(changed)
        self._validate_file_claims(merged)
        for thread_id in repaired | changed:
            if thread_id not in validated_files:
                expected = written.get(thread_id, base.files.get(thread_id))
                if expected is None:
                    raise ValueError(
                        f"missing expected remote file snapshot for {thread_id!r}"
                    )
                validated_files[thread_id] = expected
        self._validate_commit_files(validated_files, written, merged)
        committed = RemoteIndex(
            format_version=REMOTE_TRANSFER_FORMAT_VERSION,
            updated_at=_now_iso(),
            threads=merged,
        )
        atomic_write_json(
            self.index_path,
            committed.to_dict(),
            expected_target=latest_snapshot,
            target_label="index",
            path_guard=self._guard_index_target,
        )
        return committed

    def _read_index(
        self,
        expected_snapshot: SyncFileSnapshot | None = None,
    ) -> tuple[RemoteIndex, SyncFileSnapshot]:
        try:
            index_kind = self._index_path_kind()
            if index_kind == "missing":
                contents = None
                index_snapshot = SyncFileSnapshot(path=self.index_path, exists=False)
            else:
                contents, index_snapshot = read_bytes_with_snapshot(self.index_path)
            if expected_snapshot is not None and index_snapshot != expected_snapshot:
                raise ConcurrentRemoteChangeError(
                    "Remote index changed after its visible snapshot"
                )
            if index_kind == "file" and contents is None:
                raise ConcurrentRemoteChangeError("Remote index changed while it was being read")
            if contents is None:
                return (
                    RemoteIndex(
                        format_version=REMOTE_TRANSFER_FORMAT_VERSION,
                        updated_at="",
                        threads={},
                    ),
                    index_snapshot,
                )
            value = json.loads(contents)
            if not isinstance(value, dict):
                raise ValueError(f"Expected a JSON object in {self.index_path}")
            index = RemoteIndex.from_dict(
                value,
                expected_format_version=REMOTE_TRANSFER_FORMAT_VERSION,
            )
            self._validate_file_claims(index.threads)
            return index, index_snapshot
        except ConcurrentRemoteChangeError:
            raise
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as error:
            raise MalformedSyncIndexError(f"Malformed {SYNC_INDEX_FILENAME}: {error}") from error

    def _index_path_kind(self) -> str:
        kind = path_kind(self.index_path)
        if kind in {"symlink", "junction"}:
            raise MalformedSyncIndexError(f"{SYNC_INDEX_FILENAME} must not be a {kind}")
        if kind not in {"missing", "file"}:
            raise MalformedSyncIndexError(f"{SYNC_INDEX_FILENAME} must be a regular file")
        return kind

    def _guard_index_target(self) -> None:
        self._index_path_kind()

    def _list_task_files(self) -> dict[str, Path]:
        tasks_kind = self._tasks_directory_kind()
        if tasks_kind == "missing":
            return {}

        discovered: dict[str, Path] = {}
        paths = sorted(
            (path for path in list_directory(self.tasks_path) if path.suffix == ".jsonl"),
            key=lambda item: item.name,
        )
        for path in paths:
            if self._task_path_kind(path) != "file":
                raise MalformedSyncIndexError(f"Remote task {path.name} must be a regular file")
            relative_path = f"{TRANSFER_TASKS_DIRNAME}/{path.name}"
            discovered[relative_path] = path
        return discovered

    def _tasks_directory_kind(self) -> str:
        kind = path_kind(self.tasks_path)
        if kind in {"symlink", "junction"}:
            raise MalformedSyncIndexError(f"tasks directory must not be a {kind}")
        if kind not in {"missing", "directory"}:
            raise MalformedSyncIndexError(f"{TRANSFER_TASKS_DIRNAME} must be a directory")
        return kind

    def _task_path_kind(self, path: Path) -> str:
        kind = path_kind(path)
        if kind in {"symlink", "junction"}:
            raise MalformedSyncIndexError(
                f"Remote task {path.name} must not be a {kind}"
            )
        return kind

    def _guard_task_target(self, path: Path) -> None:
        if path.parent != self.tasks_path:
            raise ValueError("remote task target must be inside tasks/")
        self._tasks_directory_kind()
        if self._task_path_kind(path) not in {"missing", "file"}:
            raise MalformedSyncIndexError(
                f"Remote task {path.name} must be a regular file"
            )

    def _require_transaction(self) -> None:
        if not self._lock.is_locked:
            raise RuntimeError("Remote store mutation requires a held transaction")

    def _validate_file_claims(self, threads: dict[str, RemoteThreadEntry]) -> None:
        owners: dict[str, str] = {}
        for thread_id, entry in threads.items():
            owner_key = entry.file.casefold()
            owner = owners.setdefault(owner_key, thread_id)
            if owner != thread_id:
                raise MalformedSyncIndexError(
                    f"Threads {owner!r} and {thread_id!r} claim the same remote file {entry.file!r}"
                )
        for thread_id, entry in threads.items():
            if not is_direct_task_path(entry.file, TRANSFER_TASKS_DIRNAME):
                raise MalformedSyncIndexError(
                    f"Thread {thread_id!r} file must be a relative direct child of "
                    f"{TRANSFER_TASKS_DIRNAME}/"
                )

    def _validate_selected_entries(
        self,
        expected_entries: dict[str, RemoteThreadEntry | None],
        latest: RemoteIndex,
    ) -> None:
        for thread_id, expected in expected_entries.items():
            if latest.threads.get(thread_id) != expected:
                raise ConcurrentRemoteChangeError(
                    f"Remote index entry changed after planning for thread {thread_id!r}"
                )

    def _selected_file_path(
        self,
        thread_id: str,
        expected_entry: RemoteThreadEntry | None,
        expected_snapshot: SyncFileSnapshot,
    ) -> Path:
        if expected_snapshot.path is not None:
            path = expected_snapshot.path
        elif expected_entry is not None:
            path = self.root / expected_entry.file
        else:
            path = self.tasks_path / portable_thread_filename(thread_id)
        if expected_entry is not None and path != self.root / expected_entry.file:
            raise ValueError(f"selected remote snapshot path does not match index entry for {thread_id!r}")
        if path.parent != self.tasks_path or path.suffix != ".jsonl":
            raise ValueError(f"selected remote file for thread {thread_id!r} is outside tasks/")
        return path

    def _validate_commit_inputs(
        self,
        _base: RemoteInventory,
        changed: dict[str, RemoteThreadEntry],
        written: dict[str, SyncFileSnapshot],
        expected_entries: dict[str, RemoteThreadEntry | None],
        expected_files: dict[str, SyncFileSnapshot],
    ) -> None:
        if expected_entries.keys() != expected_files.keys():
            raise ValueError("selected remote entries and files must have the same thread ids")
        invalid_entries = [
            thread_id
            for thread_id, entry in changed.items()
            if thread_id != entry.thread_id
        ]
        if invalid_entries:
            raise ValueError("changed remote index keys must match entry.thread_id")
        if not written.keys() <= changed.keys():
            raise ValueError("every written task must have a changed remote index entry")
        for thread_id, snapshot in written.items():
            entry = changed[thread_id]
            expected_path = self.root / entry.file
            if snapshot.path != expected_path:
                raise ValueError(f"written task path does not match index entry for {thread_id!r}")
            if (entry.sha256, entry.size_bytes) != (snapshot.sha256, snapshot.size_bytes):
                raise ValueError(f"written task fingerprint does not match index entry for {thread_id!r}")

    def _validate_commit_files(
        self,
        expected_files: dict[str, SyncFileSnapshot],
        written: dict[str, SyncFileSnapshot],
        committed_entries: dict[str, RemoteThreadEntry],
    ) -> None:
        for thread_id, planned in expected_files.items():
            expected = written.get(thread_id, planned)
            path = self._selected_file_path(
                thread_id,
                committed_entries.get(thread_id),
                expected,
            )
            self._guard_task_target(path)
            actual = snapshot_file(path)
            if actual != expected:
                label = "written task file" if thread_id in written else "task file"
                raise ConcurrentRemoteChangeError(
                    f"Remote {label} changed after planning for thread {thread_id!r}"
                )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
