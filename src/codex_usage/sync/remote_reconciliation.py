from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC
from pathlib import Path

from codex_usage.models import SessionMetadata
from codex_usage.parser import parse_timestamp
from codex_usage.project_identity import resolve_project_identity
from codex_usage.session_files import timestamp_key
from codex_usage.sync.constants import SYNC_CONVERSATIONS_DIRNAME, SYNC_FORMAT_VERSION
from codex_usage.sync.io import read_bytes_with_snapshot
from codex_usage.sync.models import (
    LocalInventory,
    RemoteIndex,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
    SyncIssue,
    SyncPlan,
)
from codex_usage.sync.paths import is_direct_conversation_path, portable_thread_filename


PathGuard = Callable[[Path], None]


def reconcile_remote_discovery(
    root: Path,
    persisted_index: RemoteIndex,
    index_snapshot: SyncFileSnapshot,
    discovered_files: dict[str, Path],
    path_guard: PathGuard,
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
        if not is_direct_conversation_path(relative_path, SYNC_CONVERSATIONS_DIRNAME):
            issues.append(
                SyncIssue(
                    "unindexed_unreadable",
                    f"Remote conversation {relative_path} is not a portable direct JSONL path and was "
                    "left untouched",
                )
            )
            continue
        snapshot, metadata = _materialize_conversation(path, path_guard)
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
        effective_threads[thread_id] = _reconstruct_entry(relative_path, snapshot, metadata)
        files_by_thread[thread_id] = snapshot
        repaired_thread_ids.append(thread_id)

    for thread_id in sorted(missing_thread_ids):
        entry = persisted_index.threads[thread_id]
        issues.append(_missing_file_issue(entry))

    return RemoteInventory(
        persisted_index=persisted_index,
        index=RemoteIndex(
            format_version=SYNC_FORMAT_VERSION,
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
) -> RemoteInventory:
    """Read and validate selected indexed files without rereading reconstructed files."""
    effective_threads = dict(inventory.index.threads)
    files = dict(inventory.files)
    repaired_thread_ids = list(inventory.repaired_thread_ids)
    issues = list(inventory.issues)

    for thread_id in dict.fromkeys(selected_thread_ids):
        entry = effective_threads.get(thread_id)
        if entry is None or thread_id in files:
            continue
        snapshot, metadata = _materialize_conversation(root / entry.file, path_guard)
        files[thread_id] = snapshot
        if not snapshot.exists:
            if not _has_issue(issues, "missing_remote_file", thread_id):
                issues.append(_missing_file_issue(entry))
            continue
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
        if (entry.sha256, entry.size_bytes) != (snapshot.sha256, snapshot.size_bytes):
            effective_threads[thread_id] = replace(
                entry,
                sha256=snapshot.sha256,
                size_bytes=snapshot.size_bytes,
            )
            if thread_id not in repaired_thread_ids:
                repaired_thread_ids.append(thread_id)

    return replace(
        inventory,
        index=replace(inventory.index, threads=effective_threads),
        files=files,
        repaired_thread_ids=tuple(repaired_thread_ids),
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


def _materialize_conversation(
    path: Path,
    path_guard: PathGuard,
) -> tuple[SyncFileSnapshot, SessionMetadata | None]:
    path_guard(path)
    try:
        contents, snapshot = read_bytes_with_snapshot(path)
    except OSError:
        return SyncFileSnapshot(path=path, exists=True), None
    if contents is None:
        return snapshot, None
    return snapshot, _session_metadata_from_bytes(path, contents)


def _session_metadata_from_bytes(path: Path, contents: bytes) -> SessionMetadata | None:
    for raw_line in contents.splitlines():
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
            timestamp=parse_timestamp(payload.get("timestamp"))
            or parse_timestamp(value.get("timestamp")),
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
        f"Remote conversation {entry.file} is missing",
        entry.thread_id,
    )


def _unreadable_issue(relative_path: str) -> SyncIssue:
    return SyncIssue(
        "unindexed_unreadable",
        f"Remote conversation {relative_path} has no readable session_meta identity and was left untouched",
    )


def _has_issue(issues: list[SyncIssue], code: str, thread_id: str) -> bool:
    return any(issue.code == code and issue.thread_id == thread_id for issue in issues)
