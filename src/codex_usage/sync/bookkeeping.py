from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codex_usage.session_files import (
    codex_home_from_session_dir,
    owning_session_dir,
    timestamp_key,
)
from codex_usage.sync.errors import (
    ConcurrentLocalChangeError,
    ConcurrentRemoteChangeError,
)
from codex_usage.sync.io import snapshot_file
from codex_usage.sync.models import (
    LocalInventory,
    LocalSyncState,
    RemoteInventory,
    SyncPlan,
    SyncPlanItem,
)
from codex_usage.sync.state import (
    LocalStateStore,
    local_state_from_success,
    merge_session_index,
)


def repair_matching_bookkeeping(
    plan: SyncPlan,
    local: LocalInventory,
    remote: RemoteInventory,
    sync_dir: Path,
    *,
    merge_remote_index: bool = True,
) -> None:
    index_repairs: dict[Path, list[dict[str, Any]]] = {}
    for item in plan.items:
        if item.action != "none":
            continue
        if snapshot_file(item.local.path) != item.local:
            raise ConcurrentLocalChangeError(
                f"Local task changed before bookkeeping repair for thread {item.thread_id!r}"
            )
        if snapshot_file(item.remote.path) != item.remote:
            raise ConcurrentRemoteChangeError(
                f"Remote task changed before bookkeeping repair for thread {item.thread_id!r}"
            )
        session_dir = _session_dir(item, local)
        remote_entry = remote.index.threads.get(item.thread_id)
        local_entry = local.index_entries.get(item.thread_id)
        index_needs_merge = remote_entry is not None and _index_entry_needs_merge(
            local_entry,
            remote_entry.index_entry,
        )
        state_item = (
            replace(item, updated_at=remote_entry.session_updated_at)
            if index_needs_merge and remote_entry is not None
            else item
        )
        state_store = LocalStateStore(session_dir, sync_dir)
        existing_state = state_store.read(item.thread_id)
        if not _state_is_current(existing_state, state_item, sync_dir):
            state_store.record_success(state_item, item.local, item.remote)

        if merge_remote_index and index_needs_merge and remote_entry is not None:
            index_repairs.setdefault(session_dir, []).append(
                dict(remote_entry.index_entry)
            )

    if not index_repairs:
        return
    label = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    for session_dir, entries in index_repairs.items():
        backup_dir = (
            codex_home_from_session_dir(session_dir) / ".codex-sync-backups" / label
        )
        merge_session_index(session_dir, entries, backup_dir)


def _state_is_current(
    existing: LocalSyncState | None,
    item: SyncPlanItem,
    sync_dir: Path,
) -> bool:
    if existing is None:
        return False
    expected = local_state_from_success(item, item.local, item.remote, sync_dir)
    return existing == replace(expected, synced_at=existing.synced_at)


def _index_entry_needs_merge(
    local_entry: dict[str, Any] | None,
    remote_entry: dict[str, Any],
) -> bool:
    if local_entry is None:
        return True
    if local_entry == remote_entry:
        return False
    local_updated = timestamp_key(str(local_entry.get("updated_at") or ""))
    remote_updated = timestamp_key(str(remote_entry.get("updated_at") or ""))
    if remote_updated != local_updated:
        return remote_updated > local_updated
    return any(local_entry.get(key) != value for key, value in remote_entry.items())


def _session_dir(item: SyncPlanItem, local: LocalInventory) -> Path:
    thread = local.threads.get(item.thread_id)
    if thread is not None:
        return owning_session_dir(thread.session_path, list(local.session_dirs))
    if local.session_dirs:
        return local.session_dirs[0]
    raise ValueError(f"No local session directory for thread {item.thread_id!r}")
