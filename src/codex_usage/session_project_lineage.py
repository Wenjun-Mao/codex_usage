from __future__ import annotations

from collections.abc import Iterable

from codex_usage.models import UsageRecord
from codex_usage.session_parser_events import (
    inherit_parent_project_identity,
    should_inherit_parent_project_identity,
)


def finalize_session_records(
    records_by_file: Iterable[list[UsageRecord]],
    *,
    identity_records: Iterable[UsageRecord] = (),
) -> list[UsageRecord]:
    """Apply parent identity only where a root lineage proves continuity."""
    grouped = list(records_by_file)
    identity_by_session: dict[str, UsageRecord] = {}
    for file_records in grouped:
        for record in file_records:
            if record.git_repository_url:
                identity_by_session[record.session_id] = record
    for record in identity_records:
        if record.git_repository_url:
            identity_by_session[record.session_id] = record

    resolved_identities: dict[str, UsageRecord] = {}

    def resolve_identity(session_id: str, resolving: set[str]) -> UsageRecord | None:
        if session_id in resolved_identities:
            return resolved_identities[session_id]
        candidate = identity_by_session.get(session_id)
        if candidate is None or session_id in resolving:
            return candidate
        parent = resolve_identity(
            candidate.parent_thread_id,
            {*resolving, session_id},
        )
        resolved = (
            inherit_parent_project_identity(candidate, parent)
            if parent is not None
            and should_inherit_parent_project_identity(candidate, parent)
            else candidate
        )
        resolved_identities[session_id] = resolved
        return resolved

    records: list[UsageRecord] = []
    for file_records in grouped:
        for record in file_records:
            parent_identity = resolve_identity(record.parent_thread_id, set())
            if (
                parent_identity is not None
                and should_inherit_parent_project_identity(record, parent_identity)
            ):
                records.append(inherit_parent_project_identity(record, parent_identity))
            else:
                records.append(record)
    return records
