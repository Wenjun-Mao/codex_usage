from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from time import perf_counter_ns

from codex_usage.session_cache import CachedSessionData
from codex_usage.session_files import codex_home_from_session_dir
from codex_usage.sync.bookkeeping import repair_matching_bookkeeping
from codex_usage.sync.constants import TRANSFER_TASKS_DIRNAME
from codex_usage.sync.directional_preflight import (
    Direction,
    directional_blockers,
    prepare_direction_plan,
    prepare_status_plan,
    probe_direction_scope,
)
from codex_usage.sync.errors import (
    ConcurrentLocalChangeError,
    ConcurrentRemoteChangeError,
    SyncStoreError,
    TransferFilesystemError,
)
from codex_usage.sync.inventory import (
    build_local_inventory,
)
from codex_usage.sync.identity import require_remote_index_thread_identity
from codex_usage.sync.io import atomic_copy, snapshot_file
from codex_usage.sync.models import (
    LocalInventory,
    ProjectResolutionRequest,
    RemoteInventory,
    RemoteThreadEntry,
    SyncIssue,
    SyncPlan,
    SyncPlanItem,
    SyncProgressEvent,
    SyncRunResult,
    SyncTimings,
)
from codex_usage.sync.execution import (
    PushExecution,
    emit_progress,
    execute_pushes,
    same_contents,
    session_dir as resolve_session_dir,
    validate_local_snapshot,
)
from codex_usage.sync.session_materialization import materialize_session_cwd
from codex_usage.sync.state import (
    LocalStateStore,
    backup_local_session,
    merge_session_index,
    save_conflict_candidate,
)
from codex_usage.sync.store import RemoteStore


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
    thread_ids: Iterable[str],
    project_resolution: ProjectResolutionRequest,
) -> SyncPlan:
    local = build_local_inventory(data)
    store = RemoteStore(sync_dir)
    try:
        _, plan = prepare_status_plan(
            local,
            store,
            sync_dir,
            thread_ids,
            project_resolution,
        )
    except SyncStoreError as error:
        return _load_failure_plan(local, error)
    return plan


def pull_sync(
    *,
    data: CachedSessionData,
    sync_dir: Path,
    thread_ids: Iterable[str],
    project_resolution: ProjectResolutionRequest,
    project_key: str,
    discovery_ms: int = 0,
    on_progress: Callable[[SyncProgressEvent], None] | None = None,
) -> SyncRunResult:
    return _run_direction(
        direction="pull",
        data=data,
        sync_dir=sync_dir,
        thread_ids=thread_ids,
        project_resolution=project_resolution,
        project_key=project_key,
        machine_id="",
        discovery_ms=discovery_ms,
        on_progress=on_progress,
    )


def push_sync(
    *,
    data: CachedSessionData,
    sync_dir: Path,
    thread_ids: Iterable[str],
    machine_id: str,
    project_key: str,
    project_resolution: ProjectResolutionRequest = ProjectResolutionRequest(),
    discovery_ms: int = 0,
    on_progress: Callable[[SyncProgressEvent], None] | None = None,
) -> SyncRunResult:
    return _run_direction(
        direction="push",
        data=data,
        sync_dir=sync_dir,
        thread_ids=thread_ids,
        project_resolution=project_resolution,
        project_key=project_key,
        machine_id=machine_id,
        discovery_ms=discovery_ms,
        on_progress=on_progress,
    )


def _run_direction(
    *,
    direction: Direction,
    data: CachedSessionData,
    sync_dir: Path,
    thread_ids: Iterable[str],
    project_resolution: ProjectResolutionRequest,
    project_key: str,
    machine_id: str,
    discovery_ms: int,
    on_progress: Callable[[SyncProgressEvent], None] | None,
) -> SyncRunResult:
    timer = PhaseTimer(discovery_ms)
    with timer.measure("planning"):
        local = build_local_inventory(data)
    store = RemoteStore(sync_dir)
    plan: SyncPlan | None = None
    pulled: tuple[str, ...] = ()
    pushed: tuple[str, ...] = ()

    try:
        with timer.measure("planning"):
            _, plan, scope_issues = probe_direction_scope(
                local,
                store,
                sync_dir,
                thread_ids,
                project_key,
            )
            if scope_issues:
                return SyncRunResult.blocked_with_issues(
                    plan,
                    scope_issues,
                    timings=timer.finish(),
                )
        with store.transaction():
            blocked = False
            direction_issues: tuple[SyncIssue, ...] = ()
            with timer.measure("planning"):
                remote, plan, scope_issues = prepare_direction_plan(
                    local,
                    store,
                    sync_dir,
                    thread_ids,
                    project_resolution,
                    project_key,
                )
                if scope_issues:
                    return SyncRunResult.blocked_with_issues(
                        plan,
                        scope_issues,
                        timings=timer.finish(),
                    )
                if plan.blocks_execution:
                    save_conflict_candidates(plan)
                    blocked = True
                else:
                    direction_issues = directional_blockers(plan, direction)
                    if not direction_issues:
                        validate_local_selected(plan)
                        store.validate_selected(
                            plan.expected_remote_entries(),
                            plan.expected_remote_snapshots(),
                        )

            if blocked:
                return SyncRunResult.blocked(plan, timings=timer.finish())
            if direction_issues:
                return SyncRunResult.blocked_with_issues(
                    plan,
                    direction_issues,
                    timings=timer.finish(),
                )

            push_execution = PushExecution((), {}, {})
            if direction == "pull":
                with timer.measure("pull"):
                    pulled = execute_pulls(plan, local, remote, on_progress)
            else:
                with timer.measure("push"):
                    push_execution = execute_pushes(
                        plan, local, store, machine_id, on_progress
                    )
                    pushed = push_execution.thread_ids
            with timer.measure("index"):
                repair_matching_bookkeeping(
                    plan,
                    local,
                    remote,
                    sync_dir,
                    merge_remote_index=direction == "pull",
                )
                if direction == "push":
                    commit_remote_index_once(plan, remote, store, push_execution)
    except (OSError, SyncStoreError) as error:
        if isinstance(error, OSError):
            error = TransferFilesystemError(
                error,
                pulled_thread_ids=pulled,
                pushed_thread_ids=pushed,
            )
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
        if not same_contents(snapshot_file(candidate_path), item.remote):
            raise ConcurrentRemoteChangeError(
                f"Remote task changed while saving conflict candidate for thread {item.thread_id!r}"
            )


def validate_local_selected(plan: SyncPlan) -> None:
    for item in plan.items:
        validate_local_snapshot(item)


def execute_pulls(
    plan: SyncPlan,
    local: LocalInventory,
    remote: RemoteInventory,
    callback: Callable[[SyncProgressEvent], None] | None,
) -> tuple[str, ...]:
    actions = [item for item in plan.items if item.action == "pull"]
    if not actions:
        return ()
    emit_progress(callback, "pulling")
    validated_actions: list[tuple[SyncPlanItem, RemoteThreadEntry]] = []
    for item in actions:
        remote_entry = remote.index.threads[item.thread_id]
        require_remote_index_thread_identity(
            item.thread_id,
            remote_entry.thread_id,
            remote_entry.index_entry,
        )
        validated_actions.append((item, remote_entry))
    completed: list[str] = []
    index_entries: dict[Path, list[dict[str, object]]] = {}
    backup_dirs: dict[Path, Path] = {}
    label = _backup_label()
    try:
        for item, remote_entry in validated_actions:
            validate_local_snapshot(item)
            _validate_remote_snapshot(item)
            if item.local.path is None or item.remote.path is None:
                raise ValueError("pull action requires local and remote paths")
            local_session_dir = resolve_session_dir(item, local)
            backup_dir = backup_dirs.setdefault(
                local_session_dir,
                _backup_dir(item, label),
            )
            if item.local.exists:
                backup_local_session(item.local.path, backup_dir, item.thread_id)
            validate_local_snapshot(item)
            try:
                if item.local_project_root is None:
                    copied = atomic_copy(
                        item.remote.path,
                        item.local.path,
                        expected_target=item.local,
                        target_label="local task",
                    )
                else:
                    copied = materialize_session_cwd(
                        item.remote.path,
                        item.local.path,
                        local_cwd=item.local_project_root,
                        project_identities=frozenset(
                            {
                                remote_entry.project_key,
                                *remote_entry.project_aliases,
                            }
                        ),
                        expected_target=item.local,
                        expected_source=item.remote,
                    )
            except ConcurrentRemoteChangeError as error:
                if snapshot_file(item.local.path) != item.local:
                    raise ConcurrentLocalChangeError(
                        f"Local task changed before replacement for thread {item.thread_id!r}"
                    ) from error
                raise
            if item.local_project_root is None and not same_contents(
                copied, item.remote
            ):
                raise ConcurrentRemoteChangeError(
                    f"Remote task changed while pulling thread {item.thread_id!r}"
                )
            _validate_remote_snapshot(item)
            index_entries.setdefault(local_session_dir, []).append(
                dict(remote_entry.index_entry)
            )
            completed.append(item.thread_id)
            LocalStateStore(local_session_dir, _sync_dir(item)).record_success(
                item, copied, item.remote
            )
        _merge_pulled_indexes(index_entries, backup_dirs)
    except OSError as error:
        raise TransferFilesystemError(
            error,
            pulled_thread_ids=tuple(completed),
        ) from error
    except SyncStoreError as error:
        error.pulled_thread_ids = tuple(completed)
        raise
    return tuple(completed)


def commit_remote_index_once(
    plan: SyncPlan,
    remote: RemoteInventory,
    store: RemoteStore,
    pushed: PushExecution,
) -> None:
    expected_entries = plan.expected_remote_entries()
    expected_files = plan.expected_remote_snapshots()
    if not pushed.entries and not remote.repaired_thread_ids:
        store.validate_selected(expected_entries, expected_files)
        return
    store.commit_index(
        remote,
        pushed.entries,
        pushed.snapshots,
        expected_entries=expected_entries,
        expected_files=expected_files,
    )


def _validate_remote_snapshot(item: SyncPlanItem) -> None:
    if snapshot_file(item.remote.path) != item.remote:
        raise ConcurrentRemoteChangeError(
            f"Remote task changed after planning for thread {item.thread_id!r}"
        )


def _sync_dir(item: SyncPlanItem) -> Path:
    if (
        item.remote.path is None
        or item.remote.path.parent.name != TRANSFER_TASKS_DIRNAME
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
    if isinstance(error, TransferFilesystemError):
        return SyncIssue("transfer_filesystem_failure", str(error))
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
