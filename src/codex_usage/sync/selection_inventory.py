from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from codex_usage.project_identity import is_git_project_key
from codex_usage.session_cache import CachedSessionData
from codex_usage.session_files import timestamp_key
from codex_usage.sync.inventory import build_local_inventory
from codex_usage.sync.models import (
    LocalInventory,
    ProjectIdentityKind,
    ProjectResolutionRequest,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
    SyncIssue,
)
from codex_usage.sync.planner import build_sync_plan
from codex_usage.sync.project_roots import destination_for_project
from codex_usage.sync.store import RemoteStore


INVENTORY_VERSION = 2
TaskAvailability = Literal["local", "remote", "both"]


@dataclass(frozen=True)
class SyncTaskInventoryItem:
    thread_id: str
    title: str
    updated_at: str
    estimated_sync_bytes: int
    availability: TaskAvailability
    state: str
    action: str

    def to_dict(self) -> dict[str, object]:
        return {
            "thread_id": self.thread_id,
            "title": self.title,
            "updated_at": self.updated_at,
            "estimated_sync_bytes": self.estimated_sync_bytes,
            "availability": self.availability,
            "state": self.state,
            "action": self.action,
        }


@dataclass(frozen=True)
class SyncProjectInventoryItem:
    project_key: str
    project_label: str
    identity_kind: ProjectIdentityKind
    candidate_roots: tuple[str, ...]
    tasks: tuple[SyncTaskInventoryItem, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "project_key": self.project_key,
            "project_label": self.project_label,
            "identity_kind": self.identity_kind,
            "candidate_roots": list(self.candidate_roots),
            "tasks": [task.to_dict() for task in self.tasks],
        }


@dataclass(frozen=True)
class SyncSelectionInventory:
    inventory_version: int
    projects: tuple[SyncProjectInventoryItem, ...]
    issues: tuple[SyncIssue, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "inventory_version": self.inventory_version,
            "projects": [project.to_dict() for project in self.projects],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class _TaskCandidate:
    project_key: str
    project_label: str
    from_local: bool
    remote_entry: RemoteThreadEntry | None
    task: SyncTaskInventoryItem


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _materialize_remote_for_selection(
    store: RemoteStore,
    remote: RemoteInventory,
) -> RemoteInventory:
    issue_offset = len(remote.issues)
    materialized = store.materialize_selected(remote, tuple(remote.index.threads))
    failed_validation_thread_ids = {
        issue.thread_id
        for issue in materialized.issues[issue_offset:]
        if issue.code == "unindexed_unreadable"
    }
    if not failed_validation_thread_ids:
        return materialized

    # Earlier same-code issues can describe separate unindexed files. Only issues
    # appended by materialization identify indexed snapshots that failed identity validation.
    return replace(
        materialized,
        files={
            thread_id: snapshot
            for thread_id, snapshot in materialized.files.items()
            if thread_id not in failed_validation_thread_ids
        },
    )


def build_sync_selection_inventory(
    local: LocalInventory,
    remote: RemoteInventory,
    sync_dir: Path,
    *,
    candidate_roots: tuple[Path, ...] = (),
) -> SyncSelectionInventory:
    remote_entries: dict[str, tuple[RemoteThreadEntry, SyncFileSnapshot]] = {}
    for thread_id, entry in remote.index.threads.items():
        snapshot = remote.files.get(thread_id)
        if snapshot is not None and snapshot.exists:
            remote_entries[thread_id] = (entry, snapshot)

    selected_thread_ids = tuple(sorted(local.threads.keys() | remote_entries.keys()))
    selection_plan = build_sync_plan(
        local,
        remote,
        selected_thread_ids,
        sync_dir,
        project_resolution=None,
    )
    plan_items = {item.thread_id: item for item in selection_plan.items}

    grouped: dict[str, list[_TaskCandidate]] = {}
    for thread_id in selected_thread_ids:
        local_task = local.threads.get(thread_id)
        remote_pair = remote_entries.get(thread_id)
        plan_item = plan_items[thread_id]
        if local_task is not None:
            availability: TaskAvailability = "both" if remote_pair is not None else "local"
            project_key = local_task.project_key
            project_label = local_task.project_label
            if remote_pair is not None:
                remote_entry, _ = remote_pair
                local_identities = {
                    local_task.project_key,
                    *local_task.project_aliases,
                }
                remote_identities = {
                    remote_entry.project_key,
                    *remote_entry.project_aliases,
                }
                if local_identities.intersection(remote_identities):
                    project_key = remote_entry.project_key
                    project_label = remote_entry.project_label
            candidate = _TaskCandidate(
                project_key=project_key,
                project_label=project_label,
                from_local=True,
                remote_entry=remote_pair[0] if remote_pair is not None else None,
                task=SyncTaskInventoryItem(
                    thread_id=thread_id,
                    title=local_task.title,
                    updated_at=local_task.updated_at,
                    estimated_sync_bytes=local_task.estimated_sync_bytes,
                    availability=availability,
                    state=plan_item.state,
                    action=plan_item.action,
                ),
            )
        else:
            assert remote_pair is not None
            entry, snapshot = remote_pair
            project_key = entry.project_key
            project_label = entry.project_label
            candidate = _TaskCandidate(
                project_key=project_key,
                project_label=project_label,
                from_local=False,
                remote_entry=entry,
                task=SyncTaskInventoryItem(
                    thread_id=thread_id,
                    title=(
                        _text(entry.index_entry.get("thread_name"))
                        or _text(entry.index_entry.get("title"))
                        or project_label
                        or thread_id
                    ),
                    updated_at=(
                        _text(entry.index_entry.get("updated_at"))
                        or entry.session_updated_at
                    ),
                    estimated_sync_bytes=snapshot.size_bytes,
                    availability="remote",
                    state=plan_item.state,
                    action=plan_item.action,
                ),
            )
        grouped.setdefault(project_key, []).append(candidate)

    projects: list[SyncProjectInventoryItem] = []
    for project_key, candidates in grouped.items():
        candidates.sort(key=lambda candidate: candidate.task.thread_id)
        candidates.sort(
            key=lambda candidate: timestamp_key(candidate.task.updated_at),
            reverse=True,
        )
        local_labels = [candidate for candidate in candidates if candidate.from_local]
        label_candidates = local_labels or candidates
        project_label = label_candidates[0].project_label
        identity_kind: ProjectIdentityKind = (
            "git" if is_git_project_key(project_key) else "path"
        )
        destination_entry = next(
            (
                candidate.remote_entry
                for candidate in candidates
                if candidate.remote_entry is not None
                and candidate.remote_entry.project_key == project_key
            ),
            None,
        )
        destination_roots: tuple[str, ...] = ()
        if destination_entry is not None:
            destination = destination_for_project(
                local,
                destination_entry,
                ProjectResolutionRequest(candidate_roots=candidate_roots),
            )
            identity_kind = destination.identity_kind
            destination_roots = tuple(str(path) for path in destination.candidate_roots)
        projects.append(
            SyncProjectInventoryItem(
                project_key=project_key,
                project_label=project_label,
                identity_kind=identity_kind,
                candidate_roots=destination_roots,
                tasks=tuple(candidate.task for candidate in candidates),
            )
        )
    projects.sort(key=lambda project: (project.project_label.casefold(), project.project_key))
    return SyncSelectionInventory(
        INVENTORY_VERSION,
        tuple(projects),
        selection_plan.issues,
    )


def load_sync_selection_inventory(
    data: CachedSessionData,
    sync_dir: Path,
    *,
    candidate_roots: tuple[Path, ...] = (),
) -> SyncSelectionInventory:
    local = build_local_inventory(data)
    store = RemoteStore(sync_dir)
    remote = store.load_inventory()
    remote = _materialize_remote_for_selection(store, remote)
    return build_sync_selection_inventory(
        local,
        remote,
        sync_dir,
        candidate_roots=candidate_roots,
    )
