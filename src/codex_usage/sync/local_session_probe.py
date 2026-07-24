from __future__ import annotations

from pathlib import Path

from codex_usage.models import UsageRecord
from codex_usage.parser import finalize_session_records, parse_session_file
from codex_usage.project_identity import resolve_project_identity
from codex_usage.project_transitions import (
    apply_project_transitions,
    collect_repo_path_observations,
    infer_project_transitions,
)
from codex_usage.session_cache import (
    CacheStats,
    CachedFileSummary,
    CachedSessionData,
)
from codex_usage.session_files import owning_session_dir, read_session_metadata
from codex_usage.session_inventory import (
    SessionFileInventoryEntry,
    collect_session_file_inventory,
)


_ESTIMATED_SYNC_METADATA_BYTES = 4096


def load_sync_session_data_read_only(
    session_dirs: list[Path],
    *,
    auto_transitions: bool,
) -> CachedSessionData:
    """Build transfer input without creating or updating the usage cache."""
    inventory = collect_session_file_inventory(session_dirs)
    files = [entry.path for entry in inventory]
    parsed_by_path = {
        entry.path: parse_session_file(entry.path)
        for entry in inventory
    }
    records = finalize_session_records(list(parsed_by_path.values()))
    summaries = {
        entry.path: _file_summary(
            entry,
            session_dirs,
            parsed_by_path[entry.path],
        )
        for entry in inventory
    }
    transitions = []
    if auto_transitions:
        observations = collect_repo_path_observations(session_dirs, files)
        transitions = infer_project_transitions(records, observations)
        records = apply_project_transitions(records, transitions)
    active_count = sum(
        entry.storage_state == "active"
        for entry in inventory
    )
    return CachedSessionData(
        session_dirs=session_dirs,
        files=files,
        records=records,
        file_summaries=summaries,
        project_transitions=transitions,
        stats=CacheStats(
            files_total=len(files),
            files_current=active_count,
            files_archived=len(files) - active_count,
            files_parsed=len(files),
        ),
        file_errors={},
    )


def _file_summary(
    entry: SessionFileInventoryEntry,
    session_dirs: list[Path],
    records: list[UsageRecord],
) -> CachedFileSummary:
    metadata = read_session_metadata(entry.path)
    selected = records[-1] if records else None
    identity = (
        None
        if selected is not None or metadata is None
        else resolve_project_identity(metadata)
    )
    return CachedFileSummary(
        file_path=entry.path,
        session_dir=owning_session_dir(entry.path, session_dirs),
        session_id=(
            selected.session_id
            if selected
            else metadata.session_id if metadata else entry.path.stem
        ),
        cwd=selected.cwd if selected else metadata.cwd if metadata else "",
        project_key=(
            selected.project_key
            if selected
            else identity.key if identity else ""
        ),
        project_label=(
            selected.project_label
            if selected
            else identity.label if identity else ""
        ),
        project_aliases=(
            selected.project_aliases
            if selected
            else identity.aliases if identity else ()
        ),
        git_repository_url=(
            selected.git_repository_url
            if selected
            else metadata.git_repository_url if metadata else ""
        ),
        git_branch=(
            selected.git_branch
            if selected
            else metadata.git_branch if metadata else ""
        ),
        memory_mode=metadata.memory_mode if metadata else "",
        has_base_instructions=metadata.has_base_instructions if metadata else False,
        session_bytes=entry.size_bytes,
        estimated_sync_bytes=entry.size_bytes + _ESTIMATED_SYNC_METADATA_BYTES,
        file_key=entry.file_key,
        storage_state=entry.storage_state,
    )
