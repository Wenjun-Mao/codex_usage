from __future__ import annotations

from collections.abc import Iterable

from codex_usage.session_cache import CachedSessionData
from codex_usage.session_files import load_all_index_entries
from codex_usage.sync.models import LocalInventory
from codex_usage.threads import list_threads_from_cached_data


def build_local_inventory(data: CachedSessionData) -> LocalInventory:
    threads = list_threads_from_cached_data(data)
    return LocalInventory(
        session_dirs=tuple(data.session_dirs),
        threads={thread.thread_id: thread for thread in threads},
        index_entries=load_all_index_entries(data.session_dirs),
        discovered_count=len(data.files),
    )


def normalize_selected_thread_ids(thread_ids: Iterable[str]) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in thread_ids:
        thread_id = value.strip()
        if not thread_id or thread_id in seen:
            continue
        seen.add(thread_id)
        selected.append(thread_id)
    return tuple(selected)
