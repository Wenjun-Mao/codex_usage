from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from codex_usage.session_files import owning_session_dir
from codex_usage.sync.constants import TRANSFER_TASKS_DIRNAME
from codex_usage.sync.errors import (
    ConcurrentLocalChangeError,
    ConcurrentRemoteChangeError,
    SyncStoreError,
    TransferFilesystemError,
)
from codex_usage.sync.io import snapshot_file
from codex_usage.sync.models import (
    LocalInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
    SyncPlan,
    SyncPlanItem,
    SyncProgressEvent,
)
from codex_usage.sync.paths import portable_thread_filename
from codex_usage.sync.state import LocalStateStore, now_iso
from codex_usage.sync.store import RemoteStore


@dataclass(frozen=True)
class PushExecution:
    thread_ids: tuple[str, ...]
    snapshots: dict[str, SyncFileSnapshot]
    entries: dict[str, RemoteThreadEntry]


def emit_progress(
    callback: Callable[[SyncProgressEvent], None] | None,
    phase: str,
) -> None:
    if callback is not None:
        callback(SyncProgressEvent("sync_progress", phase))


def execute_pushes(
    plan: SyncPlan,
    local: LocalInventory,
    store: RemoteStore,
    machine_id: str,
    callback: Callable[[SyncProgressEvent], None] | None,
) -> PushExecution:
    actions = [item for item in plan.items if item.action == "push"]
    if not actions:
        return PushExecution((), {}, {})
    emit_progress(callback, "pushing")
    completed: list[str] = []
    snapshots: dict[str, SyncFileSnapshot] = {}
    entries: dict[str, RemoteThreadEntry] = {}
    try:
        for item in actions:
            validate_local_snapshot(item)
            if item.local.path is None:
                raise ValueError("push action requires a local path")
            filename = portable_thread_filename(item.thread_id)
            written = store.write_task(item.local.path, filename, item.remote)
            validate_local_snapshot(item)
            if snapshot_file(written.path) != written or not same_contents(
                written, item.local
            ):
                raise ConcurrentRemoteChangeError(
                    f"Remote task changed while pushing thread {item.thread_id!r}"
                )
            entry = _remote_entry(item, local, filename, written, machine_id)
            local_session_dir = session_dir(item, local)
            snapshots[item.thread_id] = written
            entries[item.thread_id] = entry
            completed.append(item.thread_id)
            LocalStateStore(local_session_dir, store.root).record_success(
                item, item.local, written
            )
    except OSError as error:
        raise TransferFilesystemError(
            error,
            pushed_thread_ids=tuple(completed),
        ) from error
    except SyncStoreError as error:
        error.pushed_thread_ids = tuple(completed)
        raise
    return PushExecution(tuple(completed), snapshots, entries)


def validate_local_snapshot(item: SyncPlanItem) -> None:
    if snapshot_file(item.local.path) != item.local:
        raise ConcurrentLocalChangeError(
            f"Local task changed after planning for thread {item.thread_id!r}"
        )


def same_contents(first: SyncFileSnapshot, second: SyncFileSnapshot) -> bool:
    return (
        first.exists == second.exists
        and first.sha256 == second.sha256
        and first.size_bytes == second.size_bytes
    )


def session_dir(item: SyncPlanItem, local: LocalInventory) -> Path:
    thread = local.threads.get(item.thread_id)
    if thread is not None:
        return owning_session_dir(thread.session_path, list(local.session_dirs))
    if local.session_dirs:
        return local.session_dirs[0]
    raise ValueError(f"No local session directory for thread {item.thread_id!r}")


def _remote_entry(
    item: SyncPlanItem,
    local: LocalInventory,
    filename: str,
    written: SyncFileSnapshot,
    machine_id: str,
) -> RemoteThreadEntry:
    thread = local.threads.get(item.thread_id)
    aliases = thread.project_aliases if thread is not None else ()
    index_entry = dict(
        local.index_entries.get(item.thread_id) or {"id": item.thread_id}
    )
    return RemoteThreadEntry(
        thread_id=item.thread_id,
        file=f"{TRANSFER_TASKS_DIRNAME}/{filename}",
        source_relative_path=item.source_relative_path,
        index_entry=index_entry,
        project_key=item.project_key,
        project_label=item.project_label,
        project_aliases=aliases,
        sha256=written.sha256,
        size_bytes=written.size_bytes,
        session_updated_at=item.updated_at,
        exported_at=now_iso(),
        source_machine_id=machine_id,
    )
