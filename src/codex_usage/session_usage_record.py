"""Attach source metadata and current model context to one observed usage delta."""
from codex_usage.models import UsageRecord, usage_role_from_is_subagent
from codex_usage.project_identity import resolve_project_identity


def usage_record(path, metadata, timestamp, delta, *, model, turn_id, effort, mode):
    identity = resolve_project_identity(metadata)
    return UsageRecord(
        timestamp=timestamp, usage=delta, session_id=metadata.session_id,
        file_path=path, usage_role=usage_role_from_is_subagent(metadata.is_subagent),
        model=model, turn_id=turn_id, effort=effort, collaboration_mode=mode,
        project_key=identity.key, project_label=identity.label, project_aliases=identity.aliases,
        cwd=metadata.cwd,
        git_repository_url=(identity.git_repository_url if identity.uses_current_checkout_origin
                            else metadata.git_repository_url or identity.git_repository_url),
        git_branch=metadata.git_branch, parent_thread_id=metadata.parent_thread_id,
    )
