from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from time import perf_counter_ns

from codex_usage.session_cache import CachedSessionData
from codex_usage.session_files import codex_home_from_session_dir, owning_session_dir
from codex_usage.sync.bookkeeping import repair_matching_bookkeeping
from codex_usage.sync.constants import SYNC_CONVERSATIONS_DIRNAME
from codex_usage.sync.errors import (
    ConcurrentLocalChangeError,
    ConcurrentRemoteChangeError,
    SyncStoreError,
)
from codex_usage.sync.inventory import (
    build_local_inventory,
    resolve_selected_thread_ids,
)
from codex_usage.sync.io import atomic_copy, snapshot_file
from codex_usage.sync.models import (
    LocalInventory,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
    SyncIssue,
    SyncPlan,
    SyncPlanItem,
    SyncProgressEvent,
    SyncRunResult,
    SyncTimings,
)
from codex_usage.sync.paths import portable_thread_filename
from codex_usage.sync.planner import build_sync_plan
from codex_usage.sync.state import (
    LocalStateStore,
    backup_local_session,
    merge_session_index,
    now_iso,
    save_conflict_candidate,
)
from codex_usage.sync.store import RemoteStore


@dataclass(frozen=True)
class PushExecution:
    thread_ids: tuple[str, ...]
    snapshots: dict[str, SyncFileSnapshot]
    entries: dict[str, RemoteThreadEntry]


class PhaseTimer:
    def __init__(self, discovery_ms: int) -> None:
        self.discovery_ms = max(0, discovery_ms)
        self._durations = {"planning": 0, "pull": 0, "push": 0, "index": 0}

    @contextmanager
    def measure(self, phase: str) -> Iterator[None]:
        started = perf_counter_ns()
        try:
            yield
        finally:
            elapsed_ms = (perf_counter_ns() - started) // 1_000_000
            self._durations[phase] += max(0, elapsed_ms)

    def finish(self) -> SyncTimings:
        planning = self._durations["planning"]
        pull = self._durations["pull"]
        push = self._durations["push"]
        index = self._durations["index"]
        return SyncTimings(
            discovery=self.discovery_ms,
            planning=planning,
            pull=pull,
            push=push,
            index=index,
            total=self.discovery_ms + planning + pull + push + index,
        )


def sync_status(
    *,
    data: CachedSessionData,
    sync_dir: Path,
    project_keys: list[str],
    thread_ids: list[str],
) -> SyncPlan:
    local = build_local_inventory(data)
    store = RemoteStore(sync_dir)
    try:
        remote = store.load_inventory()
    except SyncStoreError as error:
        return _load_failure_plan(local, error)
    selected = resolve_selected_thread_ids(local, remote, project_keys, thread_ids)
    return build_sync_plan(local, remote, selected, sync_dir)


def run_sync(
    *,
    data: CachedSessionData,
    sync_dir: Path,
    project_keys: list[str],
    thread_ids: list[str],
    machine_id: str,
    discovery_ms: int = 0,
    on_progress: Callable[[SyncProgressEvent], None] | None = None,
) -> SyncRunResult:
    timer = PhaseTimer(discovery_ms)
    with timer.measure("planning"):
        local = build_local_inventory(data)
    store = RemoteStore(sync_dir)
    plan: SyncPlan | None = None
    pulled: tuple[str, ...] = ()
    pushed: tuple[str, ...] = ()

    try:
        with store.transaction():
            blocked = False
            with timer.measure("planning"):
                remote = store.load_inventory()
                selected = resolve_selected_thread_ids(
                    local, remote, project_keys, thread_ids
                )
                plan = build_sync_plan(local, remote, selected, sync_dir)
                if plan.blocks_execution:
                    save_conflict_candidates(plan)
                    blocked = True
                else:
                    validate_local_selected(plan)
                    store.validate_selected(
                        plan.expected_remote_entries(),
                        plan.expected_remote_snapshots(),
                    )

            if blocked:
                return SyncRunResult.blocked(plan, timings=timer.finish())

            with timer.measure("pull"):
                pulled = execute_pulls(plan, local, remote, on_progress)
            with timer.measure("push"):
                push_execution = execute_pushes(
                    plan, local, store, machine_id, on_progress
                )
                pushed = push_execution.thread_ids
            with timer.measure("index"):
                repair_matching_bookkeeping(plan, local, remote, sync_dir)
                commit_remote_index_once(plan, remote, store, push_execution)
    except SyncStoreError as error:
        if plan is None:
            failure_plan = _load_failure_plan(local, error)
            return SyncRunResult.blocked(failure_plan, timings=timer.finish())
        pulled = _merge_completed(pulled, getattr(error, "pulled_thread_ids", ()))
        pushed = _merge_completed(pushed, getattr(error, "pushed_thread_ids", ()))
        return SyncRunResult.failed(
            plan,
            _issue_from_error(error),
            pulled=pulled,
            pushed=pushed,
            timings=timer.finish(),
        )

    return SyncRunResult.completed(
        plan,
        pulled=pulled,
        pushed=pushed,
        timings=timer.finish(),
    )


def emit(callback: Callable[[SyncProgressEvent], None] | None, phase: str) -> None:
    if callback is not None:
        callback(SyncProgressEvent("sync_progress", phase))


def save_conflict_candidates(plan: SyncPlan) -> None:
    label = _backup_label()
    for item in plan.items:
        if item.action != "conflict" or item.remote.path is None:
            continue
        _validate_remote_snapshot(item)
        backup_dir = _backup_dir(item, label)
        candidate_path = save_conflict_candidate(
            item.remote.path, backup_dir, item.thread_id
        )
        if not _same_contents(snapshot_file(candidate_path), item.remote):
            raise ConcurrentRemoteChangeError(
                f"Remote conversation changed while saving conflict candidate for thread {item.thread_id!r}"
            )


def validate_local_selected(plan: SyncPlan) -> None:
    for item in plan.items:
        _validate_local_snapshot(item)


def execute_pulls(
    plan: SyncPlan,
    local: LocalInventory,
    remote: RemoteInventory,
    callback: Callable[[SyncProgressEvent], None] | None,
) -> tuple[str, ...]:
    actions = [item for item in plan.items if item.action == "pull"]
    if not actions:
        return ()
    emit(callback, "pulling")
    completed: list[str] = []
    index_entries: dict[Path, list[dict[str, object]]] = {}
    backup_dirs: dict[Path, Path] = {}
    label = _backup_label()
    try:
        for item in actions:
            _validate_local_snapshot(item)
            _validate_remote_snapshot(item)
            if item.local.path is None or item.remote.path is None:
                raise ValueError("pull action requires local and remote paths")
            session_dir = _session_dir(item, local)
            backup_dir = backup_dirs.setdefault(session_dir, _backup_dir(item, label))
            if item.local.exists:
                backup_local_session(item.local.path, backup_dir, item.thread_id)
            _validate_local_snapshot(item)
            try:
                copied = atomic_copy(
                    item.remote.path,
                    item.local.path,
                    expected_target=item.local,
                    target_label="local conversation",
                )
            except ConcurrentRemoteChangeError as error:
                if snapshot_file(item.local.path) != item.local:
                    raise ConcurrentLocalChangeError(
                        f"Local conversation changed before replacement for thread {item.thread_id!r}"
                    ) from error
                raise
            if not _same_contents(copied, item.remote):
                raise ConcurrentRemoteChangeError(
                    f"Remote conversation changed while pulling thread {item.thread_id!r}"
                )
            _validate_remote_snapshot(item)
            remote_entry = remote.index.threads[item.thread_id]
            index_entries.setdefault(session_dir, []).append(
                dict(remote_entry.index_entry)
            )
            completed.append(item.thread_id)
            LocalStateStore(session_dir, _sync_dir(item)).record_success(
                item, copied, item.remote
            )
        _merge_pulled_indexes(index_entries, backup_dirs)
    except SyncStoreError as error:
        error.pulled_thread_ids = tuple(completed)
        raise
    return tuple(completed)


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
    emit(callback, "pushing")
    completed: list[str] = []
    snapshots: dict[str, SyncFileSnapshot] = {}
    entries: dict[str, RemoteThreadEntry] = {}
    try:
        for item in actions:
            _validate_local_snapshot(item)
            if item.local.path is None:
                raise ValueError("push action requires a local path")
            filename = portable_thread_filename(item.thread_id)
            written = store.write_conversation(item.local.path, filename, item.remote)
            _validate_local_snapshot(item)
            if snapshot_file(written.path) != written or not _same_contents(
                written, item.local
            ):
                raise ConcurrentRemoteChangeError(
                    f"Remote conversation changed while pushing thread {item.thread_id!r}"
                )
            entry = _remote_entry(item, local, filename, written, machine_id)
            session_dir = _session_dir(item, local)
            snapshots[item.thread_id] = written
            entries[item.thread_id] = entry
            completed.append(item.thread_id)
            LocalStateStore(session_dir, store.root).record_success(
                item, item.local, written
            )
    except SyncStoreError as error:
        error.pushed_thread_ids = tuple(completed)
        raise
    return PushExecution(tuple(completed), snapshots, entries)


def commit_remote_index_once(
    plan: SyncPlan,
    remote: RemoteInventory,
    store: RemoteStore,
    pushed: PushExecution,
) -> None:
    del plan
    if not pushed.entries and not remote.repaired_thread_ids:
        return
    store.commit_index(remote, pushed.entries, pushed.snapshots)


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
        file=f"{SYNC_CONVERSATIONS_DIRNAME}/{filename}",
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


def _validate_local_snapshot(item: SyncPlanItem) -> None:
    if snapshot_file(item.local.path) != item.local:
        raise ConcurrentLocalChangeError(
            f"Local conversation changed after planning for thread {item.thread_id!r}"
        )


def _validate_remote_snapshot(item: SyncPlanItem) -> None:
    if snapshot_file(item.remote.path) != item.remote:
        raise ConcurrentRemoteChangeError(
            f"Remote conversation changed after planning for thread {item.thread_id!r}"
        )


def _same_contents(first: SyncFileSnapshot, second: SyncFileSnapshot) -> bool:
    return (
        first.exists == second.exists
        and first.sha256 == second.sha256
        and first.size_bytes == second.size_bytes
    )


def _session_dir(item: SyncPlanItem, local: LocalInventory) -> Path:
    thread = local.threads.get(item.thread_id)
    if thread is not None:
        return owning_session_dir(thread.session_path, list(local.session_dirs))
    if local.session_dirs:
        return local.session_dirs[0]
    raise ValueError(f"No local session directory for thread {item.thread_id!r}")


def _sync_dir(item: SyncPlanItem) -> Path:
    if (
        item.remote.path is None
        or item.remote.path.parent.name != SYNC_CONVERSATIONS_DIRNAME
    ):
        raise ValueError(f"No remote sync directory for thread {item.thread_id!r}")
    return item.remote.path.parent.parent


def _backup_dir(item: SyncPlanItem, label: str) -> Path:
    if item.local.path is None:
        raise ValueError(f"No local backup location for thread {item.thread_id!r}")
    relative_parts = PurePosixPath(item.source_relative_path).parts
    session_dir = item.local.path
    for _ in relative_parts:
        session_dir = session_dir.parent
    expected = session_dir.joinpath(*relative_parts).resolve(strict=False)
    if expected != item.local.path.resolve(strict=False):
        sessions_ancestor = next(
            (
                parent
                for parent in item.local.path.parents
                if parent.name.casefold() == "sessions"
            ),
            None,
        )
        if sessions_ancestor is None:
            raise ValueError(
                f"Cannot determine backup location for thread {item.thread_id!r}"
            )
        session_dir = sessions_ancestor
    return codex_home_from_session_dir(session_dir) / ".codex-sync-backups" / label


def _backup_label() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


def _merge_pulled_indexes(
    entries: dict[Path, list[dict[str, object]]],
    backup_dirs: dict[Path, Path],
) -> None:
    for session_dir, new_entries in entries.items():
        merge_session_index(session_dir, new_entries, backup_dirs[session_dir])


def _issue_from_error(error: SyncStoreError) -> SyncIssue:
    name = re.sub(r"(?<!^)(?=[A-Z])", "_", type(error).__name__).casefold()
    return SyncIssue(name.removesuffix("_error"), str(error))


def _load_failure_plan(local: LocalInventory, error: SyncStoreError) -> SyncPlan:
    return SyncPlan(
        items=(),
        issues=(_issue_from_error(error),),
        discovered_count=local.discovered_count,
        remote_count=0,
        selected_count=0,
    )


def _merge_completed(
    existing: tuple[str, ...], partial: tuple[str, ...]
) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*existing, *partial)))
