from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from codex_usage.sync.inventory import normalize_selected_thread_ids
from codex_usage.sync.local_selection import materialize_selected_local
from codex_usage.sync.models import (
    LocalInventory,
    ProjectResolutionRequest,
    RemoteInventory,
    SyncIssue,
    SyncPlan,
)
from codex_usage.sync.planner import build_sync_plan
from codex_usage.sync.project_scope import transfer_project_scope_issues
from codex_usage.sync.remote_reconciliation import promote_matching_local_metadata
from codex_usage.sync.store import RemoteStore

Direction = Literal["pull", "push"]


def prepare_direction_plan(
    local: LocalInventory,
    store: RemoteStore,
    sync_dir: Path,
    thread_ids: Iterable[str],
    project_resolution: ProjectResolutionRequest,
    project_key: str,
) -> tuple[RemoteInventory, SyncPlan, tuple[SyncIssue, ...]]:
    probed_remote, probed_plan, scope_issues = probe_direction_scope(
        local,
        store,
        sync_dir,
        thread_ids,
        project_key,
    )
    if scope_issues:
        return probed_remote, probed_plan, scope_issues
    remote = store.load_inventory(metadata_only=True)
    selected = normalize_selected_thread_ids(thread_ids)
    remote = store.materialize_selected(remote, selected)
    scope_issues = transfer_project_scope_issues(local, remote, selected, project_key)
    selected_local = (
        materialize_selected_local(local, selected) if not scope_issues else None
    )
    preflight_issues = scope_issues or (
        selected_local.issues if selected_local is not None else ()
    )
    plan = build_sync_plan(
        local,
        remote,
        selected,
        sync_dir,
        project_resolution=None if preflight_issues else project_resolution,
        local_snapshots=(
            selected_local.snapshots if selected_local is not None else None
        ),
    )
    return promote_matching_local_metadata(remote, local, plan), plan, preflight_issues


def probe_direction_scope(
    local: LocalInventory,
    store: RemoteStore,
    sync_dir: Path,
    thread_ids: Iterable[str],
    project_key: str,
) -> tuple[RemoteInventory, SyncPlan, tuple[SyncIssue, ...]]:
    selected = normalize_selected_thread_ids(thread_ids)
    remote = store.probe_inventory(metadata_only=True)
    remote = store.materialize_probed(remote, selected)
    scope_issues = transfer_project_scope_issues(local, remote, selected, project_key)
    selected_local = (
        materialize_selected_local(local, selected) if not scope_issues else None
    )
    preflight_issues = scope_issues or (
        selected_local.issues if selected_local is not None else ()
    )
    plan = build_sync_plan(
        local,
        remote,
        selected,
        sync_dir,
        project_resolution=None,
        local_snapshots=(
            selected_local.snapshots if selected_local is not None else None
        ),
    )
    return remote, plan, preflight_issues


def prepare_status_plan(
    local: LocalInventory,
    store: RemoteStore,
    sync_dir: Path,
    thread_ids: Iterable[str],
    project_resolution: ProjectResolutionRequest,
) -> tuple[RemoteInventory, SyncPlan]:
    selected = normalize_selected_thread_ids(thread_ids)
    selected_local = materialize_selected_local(local, selected)
    remote = store.probe_inventory(metadata_only=True)
    remote = store.materialize_probed(remote, selected)
    plan = build_sync_plan(
        local,
        remote,
        selected,
        sync_dir,
        project_resolution=project_resolution,
        local_snapshots=selected_local.snapshots,
        local_issues=selected_local.issues,
    )
    return promote_matching_local_metadata(remote, local, plan), plan


def directional_blockers(
    plan: SyncPlan,
    direction: Direction,
) -> tuple[SyncIssue, ...]:
    opposite_direction = "push" if direction == "pull" else "pull"
    issue_code = f"{direction}_requires_{opposite_direction}"
    return tuple(
        SyncIssue(
            issue_code,
            (
                f"Selected task requires {opposite_direction} before the batch "
                f"can {direction}."
            ),
            item.thread_id,
        )
        for item in plan.items
        if item.action == opposite_direction
    )
