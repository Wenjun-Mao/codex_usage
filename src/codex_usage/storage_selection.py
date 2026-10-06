"""Bind a selected tree to its physical membership, without exposing paths."""
import hashlib
import json


def tree_membership(tree) -> str:
    members = sorted((file.path, file.task_id, file.parent_task_id, file.usage_role,
                      file.storage_state, file.project_key, file.project_aliases) for file in tree.storage_files)
    return hashlib.sha256(json.dumps(members).encode()).hexdigest()
