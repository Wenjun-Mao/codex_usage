from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC
from pathlib import Path

from codex_usage.models import SessionMetadata
from codex_usage.project_identity import (
    ProjectIdentity,
    is_git_project_key,
    normalize_declared_project_key,
    resolve_project_identity,
)
from codex_usage.session_files import timestamp_key
from codex_usage.sync.constants import LEGACY_REMOTE_TRANSFER_FORMAT_VERSION
from codex_usage.sync.format_migration_layout import guard_legacy_file, guard_task_file
from codex_usage.sync.io import (
    metadata_snapshot,
    read_bytes_with_snapshot,
)
from codex_usage.sync.models import (
    LocalInventory,
    RemoteIndex,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
    SyncIssue,
    SyncPlan,
)
from codex_usage.sync.paths import is_direct_task_path, portable_thread_filename
from codex_usage.sync.transfer_metadata import (
    parse_transfer_metadata_bytes,
    read_transfer_metadata,
)

read_session_metadata = read_transfer_metadata

PathGuard = Callable[[Path], None]


def reconcile_remote_discovery(
    root: Path,
    persisted_index: RemoteIndex,
    index_snapshot: SyncFileSnapshot,
    discovered_files: dict[str, Path],
    path_guard: PathGuard,
    *,
    directory_name: str,
    format_version: int,
    metadata_only: bool = False,
    propagate_io_errors: bool = False,
) -> RemoteInventory:
    """Reconcile cheap indexed discovery with one-pass unindexed reconstruction."""
    effective_threads = dict(persisted_index.threads)
    files_by_thread: dict[str, SyncFileSnapshot] = {}
    repaired_thread_ids: list[str] = []
    issues: list[SyncIssue] = []
    missing_thread_ids: set[str] = set()

    claimed_paths = {entry.file for entry in persisted_index.threads.values()}
    for thread_id, entry in persisted_index.threads.items():
        if entry.file not in discovered_files:
            files_by_thread[thread_id] = SyncFileSnapshot(path=root / entry.file, exists=False)
            missing_thread_ids.add(thread_id)

    reconstruction_candidates: dict[
        str, list[tuple[str, SyncFileSnapshot, SessionMetadata]]
    ] = {}
    for relative_path in sorted(discovered_files.keys() - claimed_paths):
        path = discovered_files[relative_path]
        if not is_direct_task_path(relative_path, directory_name):
            issues.append(
                SyncIssue(
                    "unindexed_unreadable",
                    f"Remote task {relative_path} is not a portable direct JSONL path and was "
                    "left untouched",
                )
            )
            continue
        if metadata_only:
            path_guard(path)
            metadata = read_session_metadata(path)
            try:
                snapshot = metadata_snapshot(path)
            except OSError:
                if propagate_io_errors:
                    raise
                snapshot = SyncFileSnapshot(path=path, exists=True)
        else:
            snapshot, metadata = materialize_remote_task(
                path,
                path_guard,
                propagate_io_errors=propagate_io_errors,
            )
        if metadata is None:
            issues.append(_unreadable_issue(relative_path))
            continue
        if metadata_only and metadata.is_subagent:
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
            missing_thread_ids.remove(thread_id)
            continue
        if thread_id in effective_threads or len(candidates) > 1:
            for relative_path, _, _ in candidates:
                issues.append(
                    SyncIssue(
                        "unindexed_unreadable",
                        f"Remote task {relative_path} cannot be indexed because multiple remote "
                        f"files claim thread id {thread_id!r}",
                        thread_id if thread_id in effective_threads else "",
                    )
                )
            continue

        relative_path, snapshot, metadata = candidates[0]
        effective_threads[thread_id] = _reconstruct_entry(relative_path, snapshot, metadata)
        files_by_thread[thread_id] = snapshot
        if not metadata_only and not metadata.is_subagent:
            repaired_thread_ids.append(thread_id)

    for thread_id in sorted(missing_thread_ids):
        entry = persisted_index.threads[thread_id]
        issues.append(_missing_file_issue(entry))

    return RemoteInventory(
        persisted_index=persisted_index,
        index=RemoteIndex(
            format_version=format_version,
            updated_at=persisted_index.updated_at,
            threads=effective_threads,
        ),
        index_snapshot=index_snapshot,
        files=files_by_thread,
        repaired_thread_ids=tuple(repaired_thread_ids),
        issues=tuple(issues),
    )


def materialize_selected_remote(
    root: Path,
    inventory: RemoteInventory,
    selected_thread_ids: Iterable[str],
    path_guard: PathGuard,
    *,
    propagate_io_errors: bool = False,
) -> RemoteInventory:
    """Read and hash selected files, then validate their indexed provenance."""
    effective_threads = dict(inventory.index.threads)
    files = dict(inventory.files)
    repaired_thread_ids = list(inventory.repaired_thread_ids)
    issues = list(inventory.issues)

    for thread_id in dict.fromkeys(selected_thread_ids):
        entry = effective_threads.get(thread_id)
        if entry is None:
            continue
        visible_snapshot = files.get(thread_id)
        if visible_snapshot is not None and not visible_snapshot.exists:
            continue
        path = (
            visible_snapshot.path
            if visible_snapshot is not None and visible_snapshot.path is not None
            else root / entry.file
        )
        snapshot, metadata = materialize_remote_task(
            path,
            path_guard,
            propagate_io_errors=propagate_io_errors,
        )
        files[thread_id] = snapshot
        if not snapshot.exists:
            if not _has_issue(issues, "missing_remote_file", thread_id):
                issues.append(_missing_file_issue(entry))
            continue
        if metadata is None:
            issues.append(
                SyncIssue(
                    "unindexed_unreadable",
                    f"Remote task {entry.file} has no readable session_meta identity",
                    thread_id,
                )
            )
            continue
        if metadata.session_id != thread_id:
            issues.append(
                SyncIssue(
                    "unindexed_unreadable",
                    f"Remote task {entry.file} contains thread id {metadata.session_id!r}, "
                    f"not indexed id {thread_id!r}",
                    thread_id,
                )
            )
            continue
        if metadata.is_subagent:
            issues.append(_subagent_issue(entry))
            continue
        if inventory.index.format_version != LEGACY_REMOTE_TRANSFER_FORMAT_VERSION:
            actual_identity = resolve_project_identity(metadata)
            provenance_entry = inventory.persisted_index.threads.get(thread_id, entry)
            if not _project_identity_matches(
                provenance_entry,
                actual_identity,
                metadata.git_repository_url,
            ):
                issues.append(_project_identity_issue(entry))
                continue
        updated_entry = entry
        if (entry.sha256, entry.size_bytes) != (snapshot.sha256, snapshot.size_bytes):
            updated_entry = replace(
                entry,
                sha256=snapshot.sha256,
                size_bytes=snapshot.size_bytes,
            )
            effective_threads[thread_id] = updated_entry
        persisted_entry = inventory.persisted_index.threads.get(thread_id)
        if (
            thread_id not in repaired_thread_ids
            and (persisted_entry is None or updated_entry != persisted_entry)
        ):
            repaired_thread_ids.append(thread_id)

    return replace(
        inventory,
        index=replace(inventory.index, threads=effective_threads),
        files=files,
        repaired_thread_ids=tuple(repaired_thread_ids),
        issues=tuple(issues),
    )


def materialize_remote_metadata_for_selection(
    root: Path,
    inventory: RemoteInventory,
) -> RemoteInventory:
    files = dict(inventory.files)
    threads = dict(inventory.index.threads)
    issues = list(inventory.issues)
    for thread_id, entry in tuple(threads.items()):
        snapshot = files.get(thread_id)
        if snapshot is not None and not snapshot.exists:
            continue
        path = snapshot.path if snapshot is not None else root / entry.file
        if path is None:
            continue
        _guard_for_format(root, inventory.index.format_version, path)
        metadata = read_session_metadata(path)
        if metadata is not None and metadata.is_subagent:
            threads.pop(thread_id, None)
            files.pop(thread_id, None)
            continue
        if metadata is None or metadata.session_id != thread_id:
            files.pop(thread_id, None)
            issues.append(_indexed_metadata_issue(entry, metadata))
            continue
        if snapshot is None:
            files[thread_id] = metadata_snapshot(path)
    return replace(
        inventory,
        index=replace(inventory.index, threads=threads),
        files=files,
        issues=tuple(issues),
    )


def promote_matching_local_metadata(
    inventory: RemoteInventory,
    local: LocalInventory,
    plan: SyncPlan,
) -> RemoteInventory:
    """Promote only strictly newer local metadata for byte-identical selected files."""
    effective_threads = dict(inventory.index.threads)
    repaired_thread_ids = list(inventory.repaired_thread_ids)

    for item in plan.items:
        entry = effective_threads.get(item.thread_id)
        local_thread = local.threads.get(item.thread_id)
        if entry is None or local_thread is None or not _same_bytes(item.local, item.remote):
            continue

        updates: dict[str, object] = {}
        if timestamp_key(local_thread.updated_at) > timestamp_key(entry.session_updated_at):
            updates.update(
                source_relative_path=item.source_relative_path,
                project_key=local_thread.project_key,
                project_label=local_thread.project_label,
                project_aliases=local_thread.project_aliases,
                session_updated_at=local_thread.updated_at,
            )

        local_index_entry = local.index_entries.get(item.thread_id)
        if local_index_entry is not None and _index_entry_is_newer(
            local_index_entry, entry.index_entry
        ):
            updates["index_entry"] = dict(local_index_entry)

        if not updates:
            continue
        effective_threads[item.thread_id] = replace(entry, **updates)
        if item.thread_id not in repaired_thread_ids:
            repaired_thread_ids.append(item.thread_id)

    return replace(
        inventory,
        index=replace(inventory.index, threads=effective_threads),
        repaired_thread_ids=tuple(repaired_thread_ids),
    )


def materialize_remote_task(
    path: Path,
    path_guard: PathGuard,
    *,
    propagate_io_errors: bool = False,
) -> tuple[SyncFileSnapshot, SessionMetadata | None]:
    path_guard(path)
    try:
        contents, snapshot = read_bytes_with_snapshot(path)
    except OSError:
        if propagate_io_errors:
            raise
        return SyncFileSnapshot(path=path, exists=True), None
    if contents is None:
        return snapshot, None
    return snapshot, parse_transfer_metadata_bytes(path, contents)


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
    return replace(
        entry,
        file=relative_path,
        sha256=snapshot.sha256,
        size_bytes=snapshot.size_bytes,
        session_updated_at=_timestamp_iso(metadata) or entry.session_updated_at,
    )


def _timestamp_iso(metadata: SessionMetadata) -> str:
    if metadata.timestamp is None:
        return ""
    return metadata.timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _same_bytes(first: SyncFileSnapshot, second: SyncFileSnapshot) -> bool:
    return (
        first.exists
        and second.exists
        and first.sha256 == second.sha256
        and first.size_bytes == second.size_bytes
    )


def _index_entry_is_newer(local: dict[str, object], remote: dict[str, object]) -> bool:
    return timestamp_key(str(local.get("updated_at") or "")) > timestamp_key(
        str(remote.get("updated_at") or "")
    )


def _missing_file_issue(entry: RemoteThreadEntry) -> SyncIssue:
    return SyncIssue(
        "missing_remote_file",
        f"Remote task {entry.file} is missing",
        entry.thread_id,
    )


def _unreadable_issue(relative_path: str) -> SyncIssue:
    return SyncIssue(
        "unindexed_unreadable",
        f"Remote task {relative_path} has no readable session_meta identity and was left untouched",
    )


def _subagent_issue(entry: RemoteThreadEntry) -> SyncIssue:
    return SyncIssue(
        "subagent_not_transferable",
        f"Remote task {entry.file} is a structured subagent and cannot be transferred",
        entry.thread_id,
    )


def _project_identity_issue(entry: RemoteThreadEntry) -> SyncIssue:
    return SyncIssue(
        "remote_project_identity_mismatch",
        (
            f"Remote task {entry.file} does not match its indexed project identity. "
            "Re-export the task from its source project before retrying."
        ),
        entry.thread_id,
    )


def _project_identity_matches(
    entry: RemoteThreadEntry,
    actual: ProjectIdentity,
    declared_repository: str,
) -> bool:
    repository = normalize_declared_project_key(declared_repository)
    if repository:
        return repository in _normalized_project_identities(
            entry.project_key,
            entry.project_aliases,
            repository=True,
        )
    indexed_paths = _normalized_project_identities(
        entry.project_key,
        entry.project_aliases,
        repository=False,
    )
    actual_paths = _normalized_project_identities(
        actual.key,
        actual.aliases,
        repository=False,
    )
    return bool(indexed_paths.intersection(actual_paths))


def _normalized_project_identities(
    key: str,
    aliases: tuple[str, ...],
    *,
    repository: bool,
) -> frozenset[str]:
    return frozenset(
        normalized
        for value in (key, *aliases)
        if (normalized := normalize_declared_project_key(value))
        and is_git_project_key(normalized) is repository
    )


def _indexed_metadata_issue(
    entry: RemoteThreadEntry,
    metadata: SessionMetadata | None,
) -> SyncIssue:
    if metadata is None:
        message = f"Remote task {entry.file} has no readable session_meta identity"
    else:
        message = (
            f"Remote task {entry.file} contains thread id {metadata.session_id!r}, "
            f"not indexed id {entry.thread_id!r}"
        )
    return SyncIssue("unindexed_unreadable", message, entry.thread_id)


def _guard_for_format(root: Path, format_version: int, path: Path) -> None:
    if format_version == LEGACY_REMOTE_TRANSFER_FORMAT_VERSION:
        guard_legacy_file(root, path)
    else:
        guard_task_file(root, path)


def _has_issue(issues: list[SyncIssue], code: str, thread_id: str) -> bool:
    return any(issue.code == code and issue.thread_id == thread_id for issue in issues)
