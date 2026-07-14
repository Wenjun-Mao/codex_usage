from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from filelock import FileLock, Timeout

from codex_usage.models import SessionMetadata
from codex_usage.parser import parse_timestamp
from codex_usage.project_identity import resolve_project_identity
from codex_usage.sync.constants import (
    SYNC_CONVERSATIONS_DIRNAME,
    SYNC_FORMAT_VERSION,
    SYNC_INDEX_FILENAME,
)
from codex_usage.sync.errors import (
    ConcurrentRemoteChangeError,
    LegacySyncLayoutError,
    MalformedSyncIndexError,
)
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
    SyncIssue,
)
from codex_usage.sync.paths import portable_thread_filename


class RemoteStore:
    """Read and update a flat, file-authoritative remote sync catalog."""

    def __init__(self, root: Path, *, lock_timeout: float = 10.0) -> None:
        self.root = root
        self.index_path = root / SYNC_INDEX_FILENAME
        self.conversations_path = root / SYNC_CONVERSATIONS_DIRNAME
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
        self._reject_legacy_layout()
        persisted_index, index_snapshot = self._read_index()
        files = self._snapshot_conversation_files()
        index, repaired_thread_ids, issues = self._reconcile_index(persisted_index, files)
        return RemoteInventory(
            persisted_index=persisted_index,
            index=index,
            index_snapshot=index_snapshot,
            files=files,
            repaired_thread_ids=tuple(repaired_thread_ids),
            issues=tuple(issues),
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
        self._conversations_directory_kind()
        for thread_id, expected in expected_files.items():
            path = self._selected_file_path(thread_id, expected_entries[thread_id], expected)
            self._reject_symlinked_conversation(path)
            actual = snapshot_file(path)
            if actual != expected:
                raise ConcurrentRemoteChangeError(
                    f"Remote conversation file changed after planning for thread {thread_id!r}"
                )

    def write_conversation(
        self,
        source: Path,
        filename: str,
        expected_target: SyncFileSnapshot,
    ) -> SyncFileSnapshot:
        self._require_transaction()
        if not _is_direct_jsonl_filename(filename):
            raise ValueError("remote conversation target must be a direct JSONL filename")
        target = self.conversations_path / filename
        if expected_target.path != target:
            raise ValueError("expected remote conversation snapshot path must match target")
        self._conversations_directory_kind()
        self._reject_symlinked_conversation(target)
        return atomic_copy(
            source,
            target,
            expected_target=expected_target,
            target_label="conversation",
        )

    def commit_index(
        self,
        base: RemoteInventory,
        changed: dict[str, RemoteThreadEntry],
        written: dict[str, SyncFileSnapshot],
    ) -> RemoteIndex:
        self._require_transaction()
        self._validate_commit_inputs(base, changed, written)
        repaired = {
            thread_id: base.index.threads[thread_id]
            for thread_id in base.repaired_thread_ids
            if thread_id in base.index.threads
        }
        selected_entries = {thread_id: base.persisted_index.threads.get(thread_id) for thread_id in repaired | changed}

        latest, latest_snapshot = self._read_index()
        self._validate_selected_entries(selected_entries, latest)

        merged = dict(latest.threads)
        merged.update(repaired)
        merged.update(changed)
        self._validate_file_claims(merged)
        self._validate_commit_files(base, selected_entries, written, merged)
        committed = RemoteIndex(
            format_version=SYNC_FORMAT_VERSION,
            updated_at=_now_iso(),
            threads=merged,
        )
        atomic_write_json(
            self.index_path,
            committed.to_dict(),
            expected_target=latest_snapshot,
            target_label="index",
        )
        return committed

    def _reject_legacy_layout(self) -> None:
        legacy_path = self.root / "threads"
        if path_kind(legacy_path) != "missing":
            raise LegacySyncLayoutError(
                "Legacy version-1 sync layout detected; empty the sync folder and run sync again. "
                "Automatic migration is not supported."
            )

    def _read_index(
        self,
        expected_snapshot: SyncFileSnapshot | None = None,
    ) -> tuple[RemoteIndex, SyncFileSnapshot]:
        try:
            contents, index_snapshot = read_bytes_with_snapshot(self.index_path)
            if expected_snapshot is not None and index_snapshot != expected_snapshot:
                raise ConcurrentRemoteChangeError(
                    "Remote index changed after its visible snapshot"
                )
            if contents is None:
                return (
                    RemoteIndex(format_version=SYNC_FORMAT_VERSION, updated_at="", threads={}),
                    index_snapshot,
                )
            value = json.loads(contents)
            if not isinstance(value, dict):
                raise ValueError(f"Expected a JSON object in {self.index_path}")
            index = RemoteIndex.from_dict(value)
            self._validate_file_claims(index.threads)
            return index, index_snapshot
        except ConcurrentRemoteChangeError:
            raise
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as error:
            raise MalformedSyncIndexError(f"Malformed {SYNC_INDEX_FILENAME}: {error}") from error

    def _snapshot_conversation_files(self) -> dict[str, SyncFileSnapshot]:
        conversations_kind = self._conversations_directory_kind()
        if conversations_kind == "missing":
            return {}

        snapshots: dict[str, SyncFileSnapshot] = {}
        paths = sorted(
            (path for path in list_directory(self.conversations_path) if path.suffix == ".jsonl"),
            key=lambda item: item.name,
        )
        for path in paths:
            self._reject_symlinked_conversation(path)
            if path_kind(path) != "file":
                raise MalformedSyncIndexError(f"Remote conversation {path.name} must be a regular file")
            relative_path = f"{SYNC_CONVERSATIONS_DIRNAME}/{path.name}"
            snapshots[relative_path] = snapshot_file(path)
        return snapshots

    def _conversations_directory_kind(self) -> str:
        kind = path_kind(self.conversations_path)
        if kind == "symlink":
            raise MalformedSyncIndexError("conversations directory must not be a symlink")
        if kind not in {"missing", "directory"}:
            raise MalformedSyncIndexError(f"{SYNC_CONVERSATIONS_DIRNAME} must be a directory")
        return kind

    def _reject_symlinked_conversation(self, path: Path) -> None:
        if path_kind(path) == "symlink":
            raise MalformedSyncIndexError(
                f"Remote conversation {path.name} must not be a symlink"
            )

    def _require_transaction(self) -> None:
        if not self._lock.is_locked:
            raise RuntimeError("Remote store mutation requires a held transaction")

    def _reconcile_index(
        self,
        persisted_index: RemoteIndex,
        files: dict[str, SyncFileSnapshot],
    ) -> tuple[RemoteIndex, list[str], list[SyncIssue]]:
        effective_threads = dict(persisted_index.threads)
        files_by_thread: dict[str, SyncFileSnapshot] = {}
        repaired_thread_ids: list[str] = []
        issues: list[SyncIssue] = []
        missing_thread_ids: set[str] = set()

        claimed_paths = {entry.file for entry in persisted_index.threads.values()}
        for thread_id, entry in persisted_index.threads.items():
            snapshot = files.get(entry.file, SyncFileSnapshot(path=self.root / entry.file, exists=False))
            files_by_thread[thread_id] = snapshot
            if not snapshot.exists:
                missing_thread_ids.add(thread_id)
                continue

            metadata = _read_explicit_session_metadata(snapshot.path)
            if metadata is None:
                issues.append(
                    SyncIssue(
                        "unindexed_unreadable",
                        f"Remote conversation {entry.file} has no readable session_meta identity",
                        thread_id,
                    )
                )
                continue
            if metadata.session_id != thread_id:
                issues.append(
                    SyncIssue(
                        "unindexed_unreadable",
                        f"Remote conversation {entry.file} contains thread id {metadata.session_id!r}, "
                        f"not indexed id {thread_id!r}",
                        thread_id,
                    )
                )
                continue
            if entry.sha256 != snapshot.sha256 or entry.size_bytes != snapshot.size_bytes:
                effective_threads[thread_id] = replace(
                    entry,
                    sha256=snapshot.sha256,
                    size_bytes=snapshot.size_bytes,
                )
                repaired_thread_ids.append(thread_id)

        reconstruction_candidates: dict[str, list[tuple[str, SyncFileSnapshot, SessionMetadata]]] = {}
        for relative_path in sorted(files.keys() - claimed_paths):
            snapshot = files[relative_path]
            if not _is_direct_conversation_path(relative_path):
                issues.append(
                    SyncIssue(
                        "unindexed_unreadable",
                        f"Remote conversation {relative_path} is not a portable direct JSONL path and was "
                        "left untouched",
                    )
                )
                continue
            metadata = _read_explicit_session_metadata(snapshot.path)
            if metadata is None:
                issues.append(_unreadable_issue(relative_path))
                continue
            reconstruction_candidates.setdefault(metadata.session_id, []).append(
                (relative_path, snapshot, metadata)
            )

        for thread_id, candidates in reconstruction_candidates.items():
            if thread_id in missing_thread_ids and len(candidates) == 1:
                relative_path, snapshot, metadata = candidates[0]
                effective_threads[thread_id] = _relink_entry(
                    effective_threads[thread_id],
                    relative_path,
                    snapshot,
                    metadata,
                )
                files_by_thread[thread_id] = snapshot
                repaired_thread_ids.append(thread_id)
                missing_thread_ids.remove(thread_id)
                continue
            if thread_id in effective_threads or len(candidates) > 1:
                for relative_path, _, _ in candidates:
                    issues.append(
                        SyncIssue(
                            "unindexed_unreadable",
                            f"Remote conversation {relative_path} cannot be indexed because multiple remote "
                            f"files claim thread id {thread_id!r}",
                            thread_id if thread_id in effective_threads else "",
                        )
                    )
                continue

            relative_path, snapshot, metadata = candidates[0]
            repaired = _reconstruct_entry(relative_path, snapshot, metadata)
            effective_threads[thread_id] = repaired
            files_by_thread[thread_id] = snapshot
            repaired_thread_ids.append(thread_id)

        for thread_id in sorted(missing_thread_ids):
            entry = persisted_index.threads[thread_id]
            issues.append(
                SyncIssue(
                    "missing_remote_file",
                    f"Remote conversation {entry.file} is missing",
                    thread_id,
                )
            )

        files.clear()
        files.update(files_by_thread)
        return (
            RemoteIndex(
                format_version=SYNC_FORMAT_VERSION,
                updated_at=persisted_index.updated_at,
                threads=effective_threads,
            ),
            repaired_thread_ids,
            issues,
        )

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
            if not _is_direct_conversation_path(entry.file):
                raise MalformedSyncIndexError(
                    f"Thread {thread_id!r} file must be a relative direct child of "
                    f"{SYNC_CONVERSATIONS_DIRNAME}/"
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
            path = self.conversations_path / portable_thread_filename(thread_id)
        if expected_entry is not None and path != self.root / expected_entry.file:
            raise ValueError(f"selected remote snapshot path does not match index entry for {thread_id!r}")
        if path.parent != self.conversations_path or path.suffix != ".jsonl":
            raise ValueError(f"selected remote file for thread {thread_id!r} is outside conversations/")
        return path

    def _validate_commit_inputs(
        self,
        base: RemoteInventory,
        changed: dict[str, RemoteThreadEntry],
        written: dict[str, SyncFileSnapshot],
    ) -> None:
        invalid_entries = [
            thread_id
            for thread_id, entry in changed.items()
            if thread_id != entry.thread_id
        ]
        if invalid_entries:
            raise ValueError("changed remote index keys must match entry.thread_id")
        if not written.keys() <= changed.keys():
            raise ValueError("every written conversation must have a changed remote index entry")
        for thread_id, snapshot in written.items():
            entry = changed[thread_id]
            expected_path = self.root / entry.file
            if snapshot.path != expected_path:
                raise ValueError(f"written conversation path does not match index entry for {thread_id!r}")
            if (entry.sha256, entry.size_bytes) != (snapshot.sha256, snapshot.size_bytes):
                raise ValueError(f"written conversation fingerprint does not match index entry for {thread_id!r}")

    def _validate_commit_files(
        self,
        base: RemoteInventory,
        selected_entries: dict[str, RemoteThreadEntry | None],
        written: dict[str, SyncFileSnapshot],
        committed_entries: dict[str, RemoteThreadEntry],
    ) -> None:
        self._conversations_directory_kind()
        for thread_id in selected_entries:
            expected = written.get(thread_id, base.files.get(thread_id))
            if expected is None:
                raise ValueError(f"missing expected remote file snapshot for {thread_id!r}")
            path = self._selected_file_path(thread_id, committed_entries[thread_id], expected)
            self._reject_symlinked_conversation(path)
            actual = snapshot_file(path)
            if actual != expected:
                label = "written conversation file" if thread_id in written else "conversation file"
                raise ConcurrentRemoteChangeError(
                    f"Remote {label} changed after planning for thread {thread_id!r}"
                )


def _is_direct_conversation_path(value: str) -> bool:
    if value != value.strip() or "\\" in value:
        return False
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    return (
        not posix_path.is_absolute()
        and not windows_path.is_absolute()
        and not windows_path.drive
        and posix_path.parts == (SYNC_CONVERSATIONS_DIRNAME, posix_path.name)
        and _is_direct_jsonl_filename(posix_path.name)
    )


def _is_direct_jsonl_filename(value: str) -> bool:
    if value != value.strip() or not value or "\\" in value:
        return False
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    return (
        not posix_path.is_absolute()
        and not windows_path.is_absolute()
        and not windows_path.drive
        and len(posix_path.parts) == 1
        and len(windows_path.parts) == 1
        and posix_path.name == value
        and posix_path.suffix == ".jsonl"
        and portable_thread_filename(posix_path.stem) == value
    )


def _read_explicit_session_metadata(path: Path | None) -> SessionMetadata | None:
    if path is None:
        return None
    try:
        contents, _ = read_bytes_with_snapshot(path)
    except OSError:
        return None
    if contents is None:
        return None
    lines = contents.splitlines()
    for raw_line in lines:
        try:
            value = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(value, dict) or value.get("type") != "session_meta":
            continue
        payload = value.get("payload")
        if not isinstance(payload, dict):
            return None
        thread_id = payload.get("id")
        if not isinstance(thread_id, str) or not thread_id.strip():
            return None
        git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
        return SessionMetadata(
            session_id=thread_id,
            file_path=path,
            timestamp=parse_timestamp(payload.get("timestamp")) or parse_timestamp(value.get("timestamp")),
            cwd=str(payload.get("cwd") or ""),
            git_repository_url=str(git.get("repository_url") or ""),
        )
    return None


def _reconstruct_entry(
    relative_path: str,
    snapshot: SyncFileSnapshot,
    metadata: SessionMetadata,
) -> RemoteThreadEntry:
    identity = resolve_project_identity(metadata)
    return RemoteThreadEntry(
        thread_id=metadata.session_id,
        file=relative_path,
        source_relative_path=f"synced/{portable_thread_filename(metadata.session_id)}",
        index_entry={"id": metadata.session_id},
        project_key=identity.key,
        project_label=identity.label,
        project_aliases=identity.aliases,
        sha256=snapshot.sha256,
        size_bytes=snapshot.size_bytes,
        session_updated_at=_timestamp_iso(metadata),
        exported_at="",
        source_machine_id="",
    )


def _relink_entry(
    entry: RemoteThreadEntry,
    relative_path: str,
    snapshot: SyncFileSnapshot,
    metadata: SessionMetadata,
) -> RemoteThreadEntry:
    identity = resolve_project_identity(metadata)
    return replace(
        entry,
        file=relative_path,
        project_key=identity.key,
        project_label=identity.label,
        project_aliases=identity.aliases,
        sha256=snapshot.sha256,
        size_bytes=snapshot.size_bytes,
        session_updated_at=_timestamp_iso(metadata) or entry.session_updated_at,
    )


def _timestamp_iso(metadata: SessionMetadata) -> str:
    if metadata.timestamp is None:
        return ""
    return metadata.timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _unreadable_issue(relative_path: str) -> SyncIssue:
    return SyncIssue(
        "unindexed_unreadable",
        f"Remote conversation {relative_path} has no readable session_meta identity and was left untouched",
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
