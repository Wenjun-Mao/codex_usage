from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from codex_usage.models import ROOT_USAGE_ROLE, UsageRole
from codex_usage.project_identity import normalize_declared_project_key
from codex_usage.session_inventory import (
    StorageRootSnapshot,
    storage_state_for_session_dir,
)
from codex_usage.storage_metadata import StorageFile, load_present_storage_files


LARGE_ROOT_BYTES = 1 << 30
LARGE_TREE_BYTES = 10 << 30


@dataclass(frozen=True, slots=True)
class StorageRootContribution:
    path: str
    storage_state: str
    file_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class TaskStorageTree:
    root_task_id: str
    title: str
    project_key: str
    project_label: str
    project_aliases: tuple[str, ...]
    root_bytes: int
    descendant_bytes: int
    descendant_count: int
    active_file_count: int
    archived_file_count: int
    active_bytes: int
    archived_bytes: int
    physical_file_count: int
    total_bytes: int
    share: float
    has_missing_root: bool
    has_relationship_cycle: bool
    duplicate_file_count: int
    metadata_diagnostics: tuple[str, ...]
    is_large_root: bool
    is_large_tree: bool
    storage_root_contributions: tuple[StorageRootContribution, ...] = ()

    @property
    def corpus_share(self) -> float:
        return self.share

    @property
    def root_missing(self) -> bool:
        return self.has_missing_root

    @property
    def has_duplicate_task_id(self) -> bool:
        return bool(self.duplicate_file_count)

    @property
    def high_inherited_root(self) -> bool:
        return self.is_large_root

    @property
    def large_task_tree(self) -> bool:
        return self.is_large_tree

    @property
    def diagnostics(self) -> tuple[str, ...]:
        issues = list(self.metadata_diagnostics)
        if self.has_relationship_cycle:
            issues.append("task_relationship_cycle")
        return tuple(sorted(set(issues)))


@dataclass(frozen=True, slots=True)
class TaskStorageInsights:
    corpus_bytes: int
    root_bytes: int
    descendant_bytes: int
    active_bytes: int
    archived_bytes: int
    physical_file_count: int
    task_tree_count: int
    task_trees: tuple[TaskStorageTree, ...]
    roots: tuple[StorageRootSnapshot, ...] = ()
    diagnostics: tuple[str, ...] = ()

    def filter_projects(
        self, project_keys: Iterable[str] | None
    ) -> "TaskStorageInsights":
        selected = _normalize_project_keys(project_keys)
        if not selected:
            return self
        trees = tuple(
            tree
            for tree in self.task_trees
            if selected.intersection({tree.project_key, *tree.project_aliases})
        )
        return _summarize_trees(trees, roots=_filter_storage_roots(self.roots, trees))

    @property
    def total_bytes(self) -> int:
        return self.corpus_bytes

    @property
    def corpus_total_bytes(self) -> int:
        return self.corpus_bytes

    @property
    def active_file_count(self) -> int:
        return sum(tree.active_file_count for tree in self.task_trees)

    @property
    def archived_file_count(self) -> int:
        return sum(tree.archived_file_count for tree in self.task_trees)

    @property
    def high_inherited_root_bytes(self) -> int:
        return LARGE_ROOT_BYTES

    @property
    def large_task_tree_bytes(self) -> int:
        return LARGE_TREE_BYTES


@dataclass(frozen=True, slots=True)
class _TaskNode:
    task_id: str
    parent_task_id: str
    usage_role: UsageRole
    project_key: str
    project_label: str
    project_aliases: tuple[str, ...]
    task_title: str


@dataclass(frozen=True, slots=True)
class _RootResolution:
    root_key: str
    has_missing_root: bool = False
    has_relationship_cycle: bool = False


def load_task_storage_insights(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    *,
    project_keys: Iterable[str] | None = None,
) -> TaskStorageInsights:
    """Build immutable storage insight models from physical, present JSONL files."""
    files = load_present_storage_files(connection)
    insights = build_task_storage_insights(files, session_dirs)
    return insights.filter_projects(project_keys)


def build_task_storage_snapshot(
    data: object,
    *,
    project_keys: Iterable[str] | None = None,
) -> TaskStorageInsights:
    """Return the already-cached storage snapshot without reopening JSONLs."""
    insights = getattr(data, "storage_insights", None)
    if not isinstance(insights, TaskStorageInsights):
        return _summarize_trees(())
    return insights.filter_projects(project_keys)


def build_task_storage_insights(
    files: Iterable[StorageFile], session_dirs: list[Path]
) -> TaskStorageInsights:
    files = tuple(files)
    files_by_task: dict[str, list[StorageFile]] = defaultdict(list)
    for file in files:
        files_by_task[file.task_id].append(file)
    nodes = {
        task_id: _node_from_files(task_id, task_files)
        for task_id, task_files in files_by_task.items()
    }
    resolutions = _resolve_task_roots(nodes)
    groups: dict[str, list[StorageFile]] = defaultdict(list)
    group_resolutions: dict[str, _RootResolution] = {}
    for file in files:
        resolution = resolutions[file.task_id]
        groups[resolution.root_key].append(file)
        group_resolutions[resolution.root_key] = resolution

    duplicate_task_ids = {
        task_id for task_id, task_files in files_by_task.items() if len(task_files) > 1
    }
    trees = tuple(
        _build_tree(
            root_key,
            group_files,
            group_resolutions[root_key],
            nodes,
            duplicate_task_ids,
        )
        for root_key, group_files in groups.items()
    )
    return _summarize_trees(
        trees,
        roots=_build_storage_roots(files, session_dirs),
    )


def _node_from_files(task_id: str, files: list[StorageFile]) -> _TaskNode:
    primary = min(files, key=_file_priority)
    return _TaskNode(
        task_id=task_id,
        parent_task_id=primary.parent_task_id,
        usage_role=primary.usage_role,
        project_key=primary.project_key,
        project_label=primary.project_label,
        project_aliases=primary.project_aliases,
        task_title=primary.task_title,
    )


def _resolve_task_roots(nodes: dict[str, _TaskNode]) -> dict[str, _RootResolution]:
    resolutions: dict[str, _RootResolution] = {}

    def resolve(task_id: str, trail: tuple[str, ...] = ()) -> _RootResolution:
        cached = resolutions.get(task_id)
        if cached is not None:
            return cached
        node = nodes[task_id]
        if node.usage_role == ROOT_USAGE_ROLE:
            result = _RootResolution(task_id)
        elif not node.parent_task_id:
            result = _RootResolution(f"missing:{task_id}", has_missing_root=True)
        elif node.parent_task_id not in nodes:
            result = _RootResolution(
                f"missing:{node.parent_task_id}", has_missing_root=True
            )
        elif task_id in trail:
            cycle = trail[trail.index(task_id) :]
            result = _RootResolution(f"cycle:{min(cycle)}", has_relationship_cycle=True)
        else:
            result = resolve(node.parent_task_id, (*trail, task_id))
        resolutions[task_id] = result
        return result

    for task_id in sorted(nodes):
        resolve(task_id)
    return resolutions


def _build_tree(
    root_key: str,
    files: list[StorageFile],
    resolution: _RootResolution,
    nodes: dict[str, _TaskNode],
    duplicate_task_ids: set[str],
) -> TaskStorageTree:
    root_node = nodes.get(root_key)
    primary = min(files, key=_file_priority)
    project_key = root_node.project_key if root_node else primary.project_key
    project_label = root_node.project_label if root_node else primary.project_label
    project_aliases = (
        root_node.project_aliases if root_node else primary.project_aliases
    )
    if resolution.has_missing_root:
        title = f"Root missing ({_short_id(root_key.removeprefix('missing:'))})"
    elif resolution.has_relationship_cycle:
        title = (
            f"Task relationship cycle ({_short_id(root_key.removeprefix('cycle:'))})"
        )
    else:
        title = str(
            (root_node.task_title if root_node else primary.task_title)
            or project_label
            or root_key
        )
    root_bytes = sum(
        file.size_bytes
        for file in files
        if root_node is not None
        and file.task_id == root_key
        and file.usage_role == ROOT_USAGE_ROLE
    )
    total_bytes = sum(file.size_bytes for file in files)
    descendant_task_ids = {
        file.task_id for file in files if file.task_id != root_key or root_node is None
    }
    diagnostics = tuple(
        sorted({file.metadata_diagnostic for file in files if file.metadata_diagnostic})
    )
    return TaskStorageTree(
        root_task_id=root_key,
        title=title,
        project_key=project_key,
        project_label=project_label,
        project_aliases=project_aliases,
        root_bytes=root_bytes,
        descendant_bytes=total_bytes - root_bytes,
        descendant_count=len(descendant_task_ids),
        active_file_count=sum(file.storage_state == "active" for file in files),
        archived_file_count=sum(file.storage_state == "archived" for file in files),
        active_bytes=sum(
            file.size_bytes for file in files if file.storage_state == "active"
        ),
        archived_bytes=sum(
            file.size_bytes for file in files if file.storage_state == "archived"
        ),
        physical_file_count=len(files),
        total_bytes=total_bytes,
        share=0.0,
        has_missing_root=resolution.has_missing_root,
        has_relationship_cycle=resolution.has_relationship_cycle,
        duplicate_file_count=sum(
            sum(1 for candidate in files if candidate.task_id == task_id) - 1
            for task_id in {file.task_id for file in files}.intersection(
                duplicate_task_ids
            )
        ),
        metadata_diagnostics=diagnostics,
        is_large_root=root_bytes >= LARGE_ROOT_BYTES,
        is_large_tree=total_bytes >= LARGE_TREE_BYTES,
        storage_root_contributions=_storage_root_contributions(files),
    )


def _summarize_trees(
    trees: Iterable[TaskStorageTree],
    *,
    roots: tuple[StorageRootSnapshot, ...] = (),
) -> TaskStorageInsights:
    ordered = tuple(
        sorted(
            trees,
            key=lambda tree: (
                -tree.total_bytes,
                tree.title.casefold(),
                tree.root_task_id,
            ),
        )
    )
    corpus_bytes = sum(tree.total_bytes for tree in ordered)
    with_shares = tuple(
        replace(tree, share=tree.total_bytes / corpus_bytes if corpus_bytes else 0.0)
        for tree in ordered
    )
    diagnostics = tuple(
        sorted({diagnostic for tree in with_shares for diagnostic in tree.diagnostics})
    )
    return TaskStorageInsights(
        corpus_bytes=corpus_bytes,
        root_bytes=sum(tree.root_bytes for tree in with_shares),
        descendant_bytes=sum(tree.descendant_bytes for tree in with_shares),
        active_bytes=sum(tree.active_bytes for tree in with_shares),
        archived_bytes=sum(tree.archived_bytes for tree in with_shares),
        physical_file_count=sum(tree.physical_file_count for tree in with_shares),
        task_tree_count=len(with_shares),
        task_trees=with_shares,
        roots=roots,
        diagnostics=diagnostics,
    )


def _build_storage_roots(
    files: tuple[StorageFile, ...], session_dirs: list[Path]
) -> tuple[StorageRootSnapshot, ...]:
    files_by_session_dir: dict[str, list[StorageFile]] = defaultdict(list)
    for file in files:
        files_by_session_dir[file.session_dir].append(file)
    paths = {str(session_dir): session_dir for session_dir in session_dirs}
    paths.update({path: Path(path) for path in files_by_session_dir})
    roots: list[StorageRootSnapshot] = []
    for path_text, path in paths.items():
        root_files = files_by_session_dir.get(path_text, [])
        roots.append(
            StorageRootSnapshot(
                path=path,
                storage_state=storage_state_for_session_dir(path),
                exists=path.is_dir(),
                jsonl_count=len(root_files),
                total_bytes=sum(file.size_bytes for file in root_files),
            )
        )
    return tuple(sorted(roots, key=lambda root: str(root.path).casefold()))


def _storage_root_contributions(
    files: list[StorageFile],
) -> tuple[StorageRootContribution, ...]:
    grouped: dict[tuple[str, str], list[StorageFile]] = defaultdict(list)
    for file in files:
        grouped[(file.session_dir, file.storage_state)].append(file)
    return tuple(
        StorageRootContribution(
            path=path,
            storage_state=storage_state,
            file_count=len(root_files),
            total_bytes=sum(file.size_bytes for file in root_files),
        )
        for (path, storage_state), root_files in sorted(grouped.items())
    )


def _filter_storage_roots(
    roots: tuple[StorageRootSnapshot, ...],
    trees: tuple[TaskStorageTree, ...],
) -> tuple[StorageRootSnapshot, ...]:
    totals: dict[str, tuple[int, int]] = {}
    for tree in trees:
        for contribution in tree.storage_root_contributions:
            count, total_bytes = totals.get(contribution.path, (0, 0))
            totals[contribution.path] = (
                count + contribution.file_count,
                total_bytes + contribution.total_bytes,
            )
    return tuple(
        replace(
            root,
            jsonl_count=totals.get(str(root.path), (0, 0))[0],
            total_bytes=totals.get(str(root.path), (0, 0))[1],
        )
        for root in roots
    )


def _normalize_project_keys(project_keys: Iterable[str] | None) -> frozenset[str]:
    return frozenset(
        key
        for value in project_keys or ()
        if (key := normalize_declared_project_key(value))
    )


def _file_priority(file: StorageFile) -> tuple[int, int, str]:
    state_priority = (
        0
        if file.storage_state == "active"
        else 1
        if file.storage_state == "archived"
        else 2
    )
    return (state_priority, -file.mtime_ns, file.path.casefold())


def _short_id(value: str) -> str:
    return value[:8] if value else "unknown"
