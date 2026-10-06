"""Freeze analysis findings against the inventory used by that analysis."""
from dataclasses import replace

from codex_usage.storage_insights import build_task_storage_insights


def selected_analysis_tree(context, tree_id, results, project_keys=None):
    updated = {str(item.request.path): item for item in results}
    files = []
    for file in context.files:
        result = updated.get(file.path)
        files.append(replace(file, content_diagnostic=result.diagnostic,
                             size_bytes=result.request.size_bytes,
                             mtime_ns=result.request.mtime_ns) if result else file)
    insights = build_task_storage_insights(files, list(context.session_dirs)).filter_projects(project_keys)
    return next(tree for tree in insights.task_trees if tree.root_task_id == tree_id)
