from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from codex_usage.models import SessionMetadata
from codex_usage.project_identity import resolve_project_identity
from codex_usage.sync.io import read_bytes_with_snapshot
from codex_usage.sync.models import LocalInventory, SyncFileSnapshot, SyncIssue
from codex_usage.sync.transfer_metadata import parse_transfer_metadata_bytes
from codex_usage.threads import ThreadInfo


@dataclass(frozen=True)
class MaterializedLocalSelection:
    snapshots: dict[str, SyncFileSnapshot]
    issues: tuple[SyncIssue, ...]


def materialize_selected_local(
    local: LocalInventory,
    selected_thread_ids: Iterable[str],
) -> MaterializedLocalSelection:
    snapshots: dict[str, SyncFileSnapshot] = {}
    issues: list[SyncIssue] = []

    for thread_id in dict.fromkeys(selected_thread_ids):
        thread = local.threads.get(thread_id)
        if thread is None or not _is_contained_session_path(local, thread.session_path):
            continue
        contents, snapshot = read_bytes_with_snapshot(thread.session_path)
        snapshots[thread_id] = snapshot
        if contents is None:
            issues.append(_unreadable_issue(thread_id, thread.session_path))
            continue
        metadata = parse_transfer_metadata_bytes(thread.session_path, contents)
        if metadata is None:
            issues.append(_unreadable_issue(thread_id, thread.session_path))
            continue
        if metadata.session_id != thread_id:
            issues.append(
                SyncIssue(
                    "local_session_identity_mismatch",
                    f"Local task {thread.session_path} contains thread id "
                    f"{metadata.session_id!r}, not selected id {thread_id!r}",
                    thread_id,
                )
            )
            continue
        if metadata.is_subagent:
            issues.append(
                SyncIssue(
                    "subagent_not_transferable",
                    f"Local task {thread.session_path} is a structured subagent and "
                    "cannot be transferred",
                    thread_id,
                )
            )
            continue
        if not _same_project_identity(thread, metadata):
            issues.append(
                SyncIssue(
                    "local_project_identity_mismatch",
                    f"Local task {thread.session_path} changed project identity after browse",
                    thread_id,
                )
            )

    return MaterializedLocalSelection(snapshots, tuple(issues))


def _is_contained_session_path(local: LocalInventory, path: Path) -> bool:
    resolved = path.resolve(strict=False)
    return any(
        session_dir.resolve(strict=False) in resolved.parents
        for session_dir in local.session_dirs
    )


def _same_project_identity(thread: ThreadInfo, metadata: SessionMetadata) -> bool:
    identity = resolve_project_identity(metadata)
    return identity.key == thread.project_key and set(identity.aliases) == set(
        thread.project_aliases
    )


def _unreadable_issue(thread_id: str, path: Path) -> SyncIssue:
    return SyncIssue(
        "local_session_metadata_unreadable",
        f"Local task {path} has no readable session_meta identity",
        thread_id,
    )
