from __future__ import annotations

from pathlib import Path

from codex_usage.session_files import owning_session_dir
from codex_usage.sync.constants import SYNC_CONVERSATIONS_DIRNAME
from codex_usage.sync.io import is_byte_prefix, snapshot_file
from codex_usage.sync.models import (
    LocalInventory,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
    SyncIssue,
    SyncPlan,
    SyncPlanItem,
)
from codex_usage.sync.paths import portable_thread_filename, safe_session_target_path
from codex_usage.sync.state import LocalStateStore, memory_database_row_count
from codex_usage.threads import ThreadInfo


def classify_snapshots(
    local: SyncFileSnapshot,
    remote: SyncFileSnapshot,
    base_sha256: str,
) -> tuple[str, str, str]:
    if local.exists and remote.exists and local.sha256 == remote.sha256:
        return "synced", "none", "local and remote match"
    if local.exists and not remote.exists:
        return "local_only", "push", "local conversation is not in the sync folder"
    if remote.exists and not local.exists:
        return "remote_only", "pull", "sync folder conversation is not local"
    if not local.exists and not remote.exists:
        return "missing", "skip", "conversation is missing locally and remotely"

    local_changed = not base_sha256 or local.sha256 != base_sha256
    remote_changed = not base_sha256 or remote.sha256 != base_sha256
    if base_sha256 and local_changed and not remote_changed:
        return "local_ahead", "push", "local changed since last sync"
    if base_sha256 and remote_changed and not local_changed:
        return "remote_ahead", "pull", "remote changed since last sync"

    relation = _prefix_relationship(local, remote)
    if relation == "remote_prefix_of_local":
        return "fast_forward_push", "push", "local extends remote"
    if relation == "local_prefix_of_remote":
        return "fast_forward_pull", "pull", "remote extends local"
    return "conflict", "conflict", "local and remote diverged"


def build_sync_plan(
    local: LocalInventory,
    remote: RemoteInventory,
    selected_thread_ids: tuple[str, ...],
    sync_dir: Path,
) -> SyncPlan:
    selected_ids = tuple(dict.fromkeys(selected_thread_ids))
    issues = list(remote.issues)
    items: list[SyncPlanItem] = []

    for thread_id in selected_ids:
        local_thread = local.threads.get(thread_id)
        effective_entry = remote.index.threads.get(thread_id)
        persisted_entry = remote.persisted_index.threads.get(thread_id)
        session_dir = _session_dir_for_thread(local, local_thread)
        item_issues = [issue for issue in remote.issues if issue.thread_id == thread_id]

        local_path, path_issue = _local_path(
            session_dir,
            thread_id,
            local_thread,
            effective_entry,
        )
        if path_issue is not None:
            issues.append(path_issue)
            item_issues.append(path_issue)

        local_snapshot = snapshot_file(local_path)
        remote_snapshot = _remote_snapshot(sync_dir, thread_id, effective_entry, remote)
        state_record = LocalStateStore(session_dir, sync_dir).read(thread_id) if session_dir else None
        base_sha256 = state_record.base_sha256 if state_record is not None else ""

        if item_issues:
            state = action = "issue"
            reason = "; ".join(issue.message for issue in item_issues)
        else:
            state, action, reason = classify_snapshots(
                local_snapshot,
                remote_snapshot,
                base_sha256,
            )

        source_relative_path, project_key, project_label, updated_at = _metadata_for_action(
            local,
            thread_id,
            action,
            local_path,
            local_thread,
            effective_entry,
        )
        items.append(
            SyncPlanItem(
                thread_id=thread_id,
                state=state,
                action=action,
                reason=reason,
                local=local_snapshot,
                remote=remote_snapshot,
                base_sha256=base_sha256,
                updated_at=updated_at,
                source_relative_path=source_relative_path,
                project_key=project_key,
                project_label=project_label,
                memory_database_rows=(
                    memory_database_row_count(session_dir, thread_id) if session_dir is not None else 0
                ),
                expected_remote_entry=persisted_entry,
            )
        )

    return SyncPlan(
        items=tuple(items),
        issues=tuple(issues),
        discovered_count=local.discovered_count,
        remote_count=len(remote.index.threads),
        selected_count=len(selected_ids),
    )


def _session_dir_for_thread(
    local: LocalInventory,
    local_thread: ThreadInfo | None,
) -> Path | None:
    if local_thread is not None and local.session_dirs:
        return owning_session_dir(local_thread.session_path, list(local.session_dirs))
    return local.session_dirs[0] if local.session_dirs else None


def _local_path(
    session_dir: Path | None,
    thread_id: str,
    local_thread: ThreadInfo | None,
    remote_entry: RemoteThreadEntry | None,
) -> tuple[Path | None, SyncIssue | None]:
    if local_thread is not None:
        if session_dir is not None:
            root = session_dir.resolve(strict=False)
            local_path = local_thread.session_path.resolve(strict=False)
            if root in local_path.parents:
                return local_thread.session_path, None
        return None, SyncIssue(
            "unsafe_local_path",
            f"Discovered local conversation for thread {thread_id!r} is outside the session directory",
            thread_id,
        )
    if session_dir is None:
        return None, SyncIssue(
            "missing_session_dir",
            f"No local session directory is available for thread {thread_id!r}",
            thread_id,
        )

    relative_path = (
        remote_entry.source_relative_path
        if remote_entry is not None
        else f"synced/{portable_thread_filename(thread_id)}"
    )
    target = safe_session_target_path(session_dir, relative_path)
    if target is None:
        return None, SyncIssue(
            "unsafe_local_path",
            f"Local conversation path {relative_path!r} escapes the session directory",
            thread_id,
        )
    return target, None


def _remote_snapshot(
    sync_dir: Path,
    thread_id: str,
    remote_entry: RemoteThreadEntry | None,
    remote: RemoteInventory,
) -> SyncFileSnapshot:
    selected = remote.files.get(thread_id)
    if selected is not None:
        return selected
    if remote_entry is not None:
        return SyncFileSnapshot(path=sync_dir / remote_entry.file, exists=False)
    return SyncFileSnapshot(
        path=sync_dir / SYNC_CONVERSATIONS_DIRNAME / portable_thread_filename(thread_id),
        exists=False,
    )


def _metadata_for_action(
    local: LocalInventory,
    thread_id: str,
    action: str,
    local_path: Path | None,
    local_thread: ThreadInfo | None,
    remote_entry: RemoteThreadEntry | None,
) -> tuple[str, str, str, str]:
    if action in {"push", "none", "conflict"} and local_thread is not None and local_path is not None:
        resolved = local_path.resolve(strict=False)
        for session_dir in local.session_dirs:
            root = session_dir.resolve(strict=False)
            if root in resolved.parents:
                return (
                    resolved.relative_to(root).as_posix(),
                    local_thread.project_key,
                    local_thread.project_label,
                    local_thread.updated_at,
                )
    if remote_entry is not None:
        return (
            remote_entry.source_relative_path,
            remote_entry.project_key,
            remote_entry.project_label,
            remote_entry.session_updated_at,
        )
    return f"synced/{portable_thread_filename(thread_id)}", "", "", ""


def _prefix_relationship(local: SyncFileSnapshot, remote: SyncFileSnapshot) -> str:
    if local.path is None or remote.path is None:
        return "diverged"
    if local.size_bytes == remote.size_bytes:
        return "diverged"
    if local.size_bytes > remote.size_bytes and is_byte_prefix(remote, local):
        return "remote_prefix_of_local"
    if remote.size_bytes > local.size_bytes and is_byte_prefix(local, remote):
        return "local_prefix_of_remote"
    return "diverged"
