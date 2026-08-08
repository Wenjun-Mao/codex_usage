from __future__ import annotations

from codex_usage.report_storage import format_bytes
from codex_usage.storage_insights import TaskStorageInsights, TaskStorageTree


def storage_snapshot_payload(snapshot: TaskStorageInsights) -> dict[str, object]:
    trees = [_storage_tree_payload(tree) for tree in snapshot.task_trees]
    trees.sort(
        key=lambda tree: (
            -int(tree["total_bytes"]),
            str(tree["title"]).casefold(),
            str(tree["root_task_id"]),
        )
    )
    roots = [
        {
            "path": str(root.path),
            "storage_state": root.storage_state,
            "exists": root.exists,
            "jsonl_count": root.jsonl_count,
            "total_bytes": root.total_bytes,
        }
        for root in snapshot.roots
    ]
    return {
        "schema_version": 3,
        "totals": {
            "total_bytes": snapshot.corpus_bytes,
            "root_bytes": snapshot.root_bytes,
            "descendant_bytes": snapshot.descendant_bytes,
            "active_bytes": snapshot.active_bytes,
            "archived_bytes": snapshot.archived_bytes,
            "physical_file_count": snapshot.physical_file_count,
            "task_tree_count": snapshot.task_tree_count,
        },
        "thresholds": {
            "high_inherited_root_bytes": snapshot.high_inherited_root_bytes,
            "large_task_tree_bytes": snapshot.large_task_tree_bytes,
        },
        "roots": roots,
        "task_trees": trees,
        "diagnostics": list(snapshot.diagnostics),
    }


def render_storage_terminal(payload: dict[str, object]) -> str:
    totals = payload["totals"]
    roots = payload["roots"]
    trees = payload["task_trees"]
    assert isinstance(totals, dict)
    assert isinstance(roots, list)
    assert isinstance(trees, list)
    total_bytes = int(totals.get("total_bytes", 0))
    file_count = int(totals.get("physical_file_count", 0))
    lines = [
        "Codex task storage snapshot",
        f"Corpus: {format_bytes(total_bytes)} | Files: {file_count:,} | "
        f"Root {format_bytes(int(totals.get('root_bytes', 0)))} | "
        f"Descendants {format_bytes(int(totals.get('descendant_bytes', 0)))}",
        "",
        "Roots:",
    ]
    for root in roots:
        assert isinstance(root, dict)
        exists = "yes" if root.get("exists", True) else "no"
        lines.append(
            f"{str(root.get('storage_state', 'unknown')):>12} {exists:>3} "
            f"{int(root.get('jsonl_count', 0)):>5} files "
            f"{format_bytes(int(root.get('total_bytes', 0))):>12} "
            f"{root.get('path', '')}"
        )
    lines.extend(("", "Task trees:"))
    for tree in trees:
        assert isinstance(tree, dict)
        flags = _terminal_tree_flags(tree)
        suffix = f" | {flags}" if flags else ""
        lines.append(
            f"{format_bytes(int(tree.get('total_bytes', 0))):>12} total | "
            f"root {format_bytes(int(tree.get('root_bytes', 0))):>12} | "
            f"desc {format_bytes(int(tree.get('descendant_bytes', 0))):>12} "
            f"({int(tree.get('descendant_count', 0)):,}) | "
            f"{tree.get('project_label') or tree.get('project_key') or 'Unassigned'} | "
            f"{tree.get('title') or tree.get('root_task_id')}{suffix}"
        )
    return "\n".join(lines)


def _storage_tree_payload(tree: TaskStorageTree) -> dict[str, object]:
    return {
        "root_task_id": tree.root_task_id,
        "title": tree.title,
        "project_key": tree.project_key,
        "project_label": tree.project_label,
        "project_aliases": list(tree.project_aliases),
        "root_bytes": tree.root_bytes,
        "descendant_bytes": tree.descendant_bytes,
        "descendant_count": tree.descendant_count,
        "active_file_count": tree.active_file_count,
        "archived_file_count": tree.archived_file_count,
        "active_bytes": tree.active_bytes,
        "archived_bytes": tree.archived_bytes,
        "physical_file_count": tree.physical_file_count,
        "total_bytes": tree.total_bytes,
        "share": tree.share,
        "has_missing_root": tree.has_missing_root,
        "has_relationship_cycle": tree.has_relationship_cycle,
        "recovery_ready": tree.recovery_ready,
        "duplicate_file_count": tree.duplicate_file_count,
        "has_duplicate_task_id": tree.has_duplicate_task_id,
        "metadata_diagnostics": list(tree.metadata_diagnostics),
        "is_large_root": tree.is_large_root,
        "is_large_tree": tree.is_large_tree,
        "analysis_status": tree.analysis_status,
        "analysis_complete": tree.analysis_complete,
        "analyzed_bytes": tree.analyzed_bytes,
        "analysis_coverage": tree.analysis_coverage,
        "compacted_record_count": tree.compacted_record_count,
        "compacted_bytes": tree.compacted_bytes,
        "compacted_share": tree.compacted_share,
        "largest_compacted_record_bytes": tree.largest_compacted_record_bytes,
        "media_compacted_record_count": tree.media_compacted_record_count,
        "embedded_media_occurrence_count": tree.embedded_media_occurrence_count,
        "large_descendant_file_count": tree.large_descendant_file_count,
        "large_descendant_bytes": tree.large_descendant_bytes,
        "large_descendant_share": tree.large_descendant_share,
        "active_root_compacted_bytes": tree.active_root_compacted_bytes,
        "has_history_amplification": tree.has_history_amplification,
        "has_media_amplification": tree.has_media_amplification,
        "has_active_root_history_risk": tree.has_active_root_history_risk,
        "can_prepare_rollover": tree.can_prepare_rollover,
    }


def _terminal_tree_flags(tree: dict[str, object]) -> str:
    flags: list[str] = []
    if tree.get("is_large_root"):
        flags.append("high inherited root")
    if tree.get("is_large_tree"):
        flags.append("large task tree")
    if tree.get("has_history_amplification"):
        flags.append("history amplification")
    if tree.get("has_media_amplification"):
        flags.append("inline media amplification")
    if tree.get("has_active_root_history_risk"):
        flags.append("active root history risk")
    if tree.get("analysis_status") != "complete":
        flags.append(f"content analysis {tree.get('analysis_status', 'unknown')}")
    if tree.get("has_missing_root"):
        flags.append("root missing")
    if tree.get("has_relationship_cycle"):
        flags.append("relationship cycle")
    if int(tree.get("duplicate_file_count", 0)):
        flags.append(f"{int(tree['duplicate_file_count']):,} duplicate files")
    return ", ".join(flags)
