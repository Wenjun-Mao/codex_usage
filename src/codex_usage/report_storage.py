from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Iterable

from codex_usage.storage_insights import TaskStorageInsights, TaskStorageTree


@dataclass(frozen=True, slots=True)
class StorageTreePoint:
    root_task_id: str
    title: str
    project_key: str
    project_label: str
    root_bytes: int
    descendant_bytes: int
    descendant_count: int
    total_bytes: int
    corpus_share: float
    active_file_count: int
    archived_file_count: int
    root_missing: bool
    relationship_cycle: bool
    duplicate_file_count: int
    high_inherited_root: bool
    large_task_tree: bool
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaskStorageView:
    total_bytes: int
    active_file_count: int
    archived_file_count: int
    diagnostics: tuple[str, ...]
    trees: tuple[StorageTreePoint, ...]

    @property
    def top_trees(self) -> tuple[StorageTreePoint, ...]:
        return self.trees[:12]

    @property
    def has_storage(self) -> bool:
        return bool(self.trees)


def build_task_storage_view(
    snapshot: TaskStorageInsights | None,
) -> TaskStorageView:
    """Adapt cached storage insights into a report-only view without file I/O."""
    if snapshot is None:
        return TaskStorageView(0, 0, 0, (), ())

    trees = tuple(
        sorted(
            (_tree_point(tree) for tree in snapshot.task_trees),
            key=lambda tree: (-tree.total_bytes, tree.title.casefold(), tree.root_task_id),
        )
    )
    return TaskStorageView(
        total_bytes=snapshot.corpus_bytes,
        active_file_count=sum(tree.active_file_count for tree in trees),
        archived_file_count=sum(tree.archived_file_count for tree in trees),
        diagnostics=snapshot.diagnostics,
        trees=trees,
    )


def render_task_storage_section(view: TaskStorageView) -> str:
    intro = (
        '<p class="muted storage-intro">Current local storage. Date range does not affect '
        "storage; selected project filters do. Root task token usage includes side chats "
        "stored in the parent task.</p>"
    )
    if not view.has_storage:
        return (
            '<section class="section task-storage-section" data-report-section="task-storage">'
            "<h2>Task Storage</h2>"
            f"{intro}"
            '<p class="notice">No task storage was found for the selected projects.</p>'
            "</section>"
        )

    summary = (
        f"{format_bytes(view.total_bytes)} across "
        f"{view.active_file_count + view.archived_file_count:,} files"
    )
    if view.archived_file_count:
        summary += f" ({view.archived_file_count:,} archived included)"
    diagnostics = _render_diagnostics(view.diagnostics)
    return (
        '<section class="section task-storage-section" data-report-section="task-storage">'
        "<h2>Task Storage</h2>"
        f"{intro}"
        f'<p class="muted storage-summary">{html.escape(summary)}</p>'
        f"{_render_storage_chart(view.top_trees)}"
        f"{_render_storage_table(view.trees)}"
        f"{diagnostics}"
        "</section>"
    )


def format_bytes(value: int) -> str:
    size = max(0, int(value))
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    amount = float(size)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount):,} {unit}"
            return f"{amount:.2f} {unit}"
        amount /= 1024
    return f"{size:,} B"


def short_task_id(task_id: str) -> str:
    return task_id if len(task_id) <= 12 else f"{task_id[:12]}..."


def _render_storage_chart(trees: Iterable[StorageTreePoint]) -> str:
    items = tuple(trees)
    if not items:
        return ""
    max_bytes = max(tree.total_bytes for tree in items) or 1
    rows = "".join(_render_storage_bar(tree, max_bytes) for tree in items)
    return (
        '<div class="storage-chart-scroll">'
        '<div class="storage-chart" role="group" aria-label="Largest task storage trees">'
        f"{rows}"
        '<div class="storage-legend" aria-label="Storage role colors">'
        '<span><i class="storage-swatch storage-root-swatch" aria-hidden="true"></i>Root task JSONL</span>'
        '<span><i class="storage-swatch storage-descendant-swatch" aria-hidden="true"></i>Structured subagents</span>'
        "</div></div></div>"
    )


def _render_storage_bar(tree: StorageTreePoint, max_bytes: int) -> str:
    outer_width = tree.total_bytes / max_bytes * 100
    root_width = tree.root_bytes / tree.total_bytes * 100 if tree.total_bytes else 0
    descendant_width = 100 - root_width
    detail = (
        f"Root {format_bytes(tree.root_bytes)} | "
        f"Descendants {format_bytes(tree.descendant_bytes)} ({tree.descendant_count:,}) | "
        f"Total {format_bytes(tree.total_bytes)}"
    )
    aria = f"{tree.title}, {detail.replace(' | ', ', ')}"
    if tree.root_bytes and tree.descendant_bytes:
        role_shape = " storage-has-boundary"
    elif tree.root_bytes:
        role_shape = " storage-root-only"
    else:
        role_shape = " storage-descendant-only"
    return (
        '<div class="storage-bar-row">'
        f'<span class="storage-bar-label" title="{_esc(tree.title)}">{_esc(tree.title)}</span>'
        '<div class="storage-track">'
        f'<span class="storage-stack{role_shape}" style="width:{outer_width:.4f}%" '
        f'tabindex="0" aria-label="{_esc(aria)}">'
        f'<span class="storage-segment storage-root-segment" style="width:{root_width:.4f}%"></span>'
        f'<span class="storage-segment storage-descendant-segment" style="width:{descendant_width:.4f}%"></span>'
        '<span class="chart-tooltip" aria-hidden="true">'
        f'<span class="chart-tooltip-main">{_esc(tree.title)}</span>'
        f'<span class="chart-tooltip-detail">{_esc(detail)}</span>'
        "</span></span></div>"
        f'<span class="storage-bar-value">{_esc(format_bytes(tree.total_bytes))}</span>'
        "</div>"
    )


def _render_storage_table(trees: Iterable[StorageTreePoint]) -> str:
    rows = "".join(_render_storage_row(tree) for tree in trees)
    return (
        '<section class="report-table-section" data-report-section="task-storage-details">'
        "<h3>Task Storage Details</h3>"
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Task</th><th>Project</th><th class=\"num\">Root</th>"
        '<th class="num">Descendants</th><th class="num">Total</th><th>State</th>'
        '<th class="num">Share</th><th>Flags</th>'
        "</tr></thead><tbody>"
        f"{rows}</tbody></table></div></section>"
    )


def _render_storage_row(tree: StorageTreePoint) -> str:
    descendants = f"{format_bytes(tree.descendant_bytes)} ({tree.descendant_count:,})"
    task = f'<span class="storage-task-title">{_esc(tree.title)}</span> <code>{_esc(short_task_id(tree.root_task_id))}</code>'
    return (
        "<tr>"
        f"<td>{task}</td>"
        f"<td>{_esc(tree.project_label)}</td>"
        f'<td class="num">{_esc(format_bytes(tree.root_bytes))}</td>'
        f'<td class="num">{_esc(descendants)}</td>'
        f'<td class="num">{_esc(format_bytes(tree.total_bytes))}</td>'
        f"<td>{_esc(_state_label(tree))}</td>"
        f'<td class="num">{tree.corpus_share:.1%}</td>'
        f"<td>{_render_badges(tree)}</td>"
        "</tr>"
    )


def _render_badges(tree: StorageTreePoint) -> str:
    badges: list[str] = []
    if tree.high_inherited_root:
        badges.append('<span class="storage-badge warn">High inherited root</span>')
    if tree.large_task_tree:
        badges.append('<span class="storage-badge warn">Large task tree</span>')
    if tree.root_missing:
        badges.append('<span class="storage-badge danger">Root missing</span>')
    if tree.relationship_cycle:
        badges.append('<span class="storage-badge danger">Relationship cycle</span>')
    if tree.duplicate_file_count:
        badges.append(
            f'<span class="storage-badge">{tree.duplicate_file_count:,} duplicate file'
            f"{'s' if tree.duplicate_file_count != 1 else ''}</span>"
        )
    if tree.diagnostics:
        tooltip = "; ".join(tree.diagnostics)
        badges.append(
            f'<span class="storage-badge" title="{_esc(tooltip)}">Diagnostics</span>'
        )
    return " ".join(badges) or '<span class="muted">-</span>'


def _render_diagnostics(diagnostics: tuple[str, ...]) -> str:
    if not diagnostics:
        return ""
    return (
        '<p class="muted storage-diagnostics">'
        f"Snapshot diagnostics: {_esc('; '.join(diagnostics))}</p>"
    )


def _tree_point(tree: TaskStorageTree) -> StorageTreePoint:
    return StorageTreePoint(
        root_task_id=tree.root_task_id,
        title=tree.title or tree.root_task_id or "Unknown root",
        project_key=tree.project_key,
        project_label=tree.project_label or tree.project_key or "Unassigned",
        root_bytes=tree.root_bytes,
        descendant_bytes=tree.descendant_bytes,
        descendant_count=tree.descendant_count,
        total_bytes=tree.total_bytes,
        corpus_share=tree.share,
        active_file_count=tree.active_file_count,
        archived_file_count=tree.archived_file_count,
        root_missing=tree.has_missing_root,
        relationship_cycle=tree.has_relationship_cycle,
        duplicate_file_count=tree.duplicate_file_count,
        high_inherited_root=tree.is_large_root,
        large_task_tree=tree.is_large_tree,
        diagnostics=tree.metadata_diagnostics,
    )


def _state_label(tree: StorageTreePoint) -> str:
    states: list[str] = []
    if tree.active_file_count:
        states.append("Active")
    if tree.archived_file_count:
        states.append("Archived")
    if tree.root_missing:
        states.append("Root missing")
    return " + ".join(states) or "Unknown"


def _esc(value: str) -> str:
    return html.escape(value, quote=True)
