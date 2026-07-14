from __future__ import annotations

from collections.abc import Iterable

from codex_usage.project_identity import normalize_project_key
from codex_usage.session_cache import CachedSessionData
from codex_usage.session_files import load_all_index_entries
from codex_usage.sync.models import LocalInventory, RemoteInventory
from codex_usage.threads import list_threads_from_cached_data


def build_local_inventory(data: CachedSessionData) -> LocalInventory:
    threads = list_threads_from_cached_data(data)
    return LocalInventory(
        session_dirs=tuple(data.session_dirs),
        threads={thread.thread_id: thread for thread in threads},
        index_entries=load_all_index_entries(data.session_dirs),
        discovered_count=len(data.files),
    )


def resolve_selected_thread_ids(
    local: LocalInventory,
    remote: RemoteInventory,
    project_keys: list[str],
    thread_ids: list[str],
) -> tuple[str, ...]:
    if thread_ids:
        return _deduplicate(thread_ids)

    selected_project_keys = {normalize_project_key(project_key) for project_key in project_keys}
    selected_project_keys.discard("")
    local_ids = sorted(
        thread.thread_id
        for thread in local.threads.values()
        if _matches_projects(thread.project_key, thread.project_aliases, selected_project_keys)
    )
    remote_ids = sorted(
        entry.thread_id
        for entry in remote.index.threads.values()
        if _matches_projects(entry.project_key, entry.project_aliases, selected_project_keys)
    )
    return _deduplicate([*local_ids, *remote_ids])


def _matches_projects(project_key: str, aliases: tuple[str, ...], selected_project_keys: set[str]) -> bool:
    if not selected_project_keys:
        return True
    return any(
        normalize_project_key(candidate) in selected_project_keys
        for candidate in (project_key, *aliases)
    )


def _deduplicate(thread_ids: Iterable[str]) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    for thread_id in thread_ids:
        if thread_id in seen:
            continue
        seen.add(thread_id)
        selected.append(thread_id)
    return tuple(selected)
