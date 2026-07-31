from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from codex_usage.project_identity import is_git_project_key
from codex_usage.session_files import timestamp_key
from codex_usage.sync.constants import LEGACY_REMOTE_TRANSFER_FORMAT_VERSION
from codex_usage.sync.local_session_probe import LocalTransferProbe
from codex_usage.sync.models import (
    LocalInventory,
    ProjectIdentityKind,
    ProjectResolutionRequest,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
    SyncIssue,
)
from codex_usage.sync.project_roots import destination_for_project
from codex_usage.sync.remote_reconciliation import (
    materialize_remote_metadata_for_selection,
)
from codex_usage.sync.store import RemoteStore


INVENTORY_VERSION = 3
TaskAvailability = Literal["local", "remote", "both"]


@dataclass(frozen=True)
class SyncTaskInventoryItem:
    thread_id: str
    title: str
    updated_at: str
    estimated_sync_bytes: int
    availability: TaskAvailability

    def to_dict(self) -> dict[str, object]:
        return {
            "thread_id": self.thread_id,
            "title": self.title,
            "updated_at": self.updated_at,
            "estimated_sync_bytes": self.estimated_sync_bytes,
            "availability": self.availability,
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


def build_sync_selection_inventory(
    local: LocalInventory,
    remote: RemoteInventory,
    *,
    candidate_roots: tuple[Path, ...] = (),
    local_issues: tuple[SyncIssue, ...] = (),
) -> SyncSelectionInventory:
    remote_entries: dict[str, tuple[RemoteThreadEntry, SyncFileSnapshot]] = {}
    for thread_id, entry in remote.index.threads.items():
        snapshot = remote.files.get(thread_id)
        if snapshot is not None and snapshot.exists:
            remote_entries[thread_id] = (entry, snapshot)

    selected_thread_ids = tuple(sorted(local.threads.keys() | remote_entries.keys()))

    grouped: dict[str, list[_TaskCandidate]] = {}
    for thread_id in selected_thread_ids:
        local_task = local.threads.get(thread_id)
        remote_pair = remote_entries.get(thread_id)
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
        (*local_issues, *remote.issues),
    )


def load_sync_selection_inventory(
    local_probe: LocalTransferProbe,
    sync_dir: Path,
    *,
    candidate_roots: tuple[Path, ...] = (),
) -> SyncSelectionInventory:
    store = RemoteStore(sync_dir)
    remote = store.probe_inventory(metadata_only=True)
    if remote.index.format_version == LEGACY_REMOTE_TRANSFER_FORMAT_VERSION:
        remote = store.materialize_probed(remote, tuple(remote.index.threads))
    else:
        remote = materialize_remote_metadata_for_selection(sync_dir, remote)
    return build_sync_selection_inventory(
        local_probe.inventory,
        remote,
        candidate_roots=candidate_roots,
        local_issues=local_probe.issues,
    )
