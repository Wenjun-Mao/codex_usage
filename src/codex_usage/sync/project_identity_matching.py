from __future__ import annotations

from codex_usage.project_identity import (
    ProjectIdentity,
    is_git_project_key,
    normalize_declared_project_key,
    normalize_repository_key,
)
from codex_usage.sync.models import RemoteThreadEntry


def matches_indexed_project_identity(
    indexed_entry: RemoteThreadEntry,
    actual_identity: ProjectIdentity,
    declared_repository: str,
) -> bool:
    """Check selected task metadata against the project identity trusted by its index."""
    repository = normalize_repository_key(declared_repository)
    if repository:
        canonical_key = normalize_repository_key(indexed_entry.project_key)
        if repository == canonical_key:
            return True
        return repository in _normalized_git_aliases(indexed_entry.project_aliases)

    indexed_paths = _normalized_project_identities(
        indexed_entry.project_key,
        indexed_entry.project_aliases,
        repository=False,
    )
    actual_paths = _normalized_project_identities(
        actual_identity.key,
        actual_identity.aliases,
        repository=False,
    )
    return bool(indexed_paths.intersection(actual_paths))


def _normalized_project_identities(
    key: str,
    aliases: tuple[str, ...],
    *,
    repository: bool,
) -> frozenset[str]:
    return frozenset(
        normalized
        for value in (key, *aliases)
        if (normalized := normalize_declared_project_key(value))
        and is_git_project_key(normalized) is repository
    )


def _normalized_git_aliases(aliases: tuple[str, ...]) -> frozenset[str]:
    return frozenset(
        normalized
        for value in aliases
        if (normalized := normalize_declared_project_key(value))
        and is_git_project_key(normalized)
    )
