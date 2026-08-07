from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import replace

from codex_usage.session_cache_generations import rekey_file_generation
from codex_usage.session_inventory import SessionFileInventoryEntry


def is_reusable(
    entry: SessionFileInventoryEntry,
    cached: sqlite3.Row | None,
    *,
    rebuilt: bool,
) -> bool:
    return bool(
        not rebuilt
        and cached is not None
        and str(cached["path"]) == str(entry.path)
        and int(cached["size_bytes"]) == entry.size_bytes
        and int(cached["mtime_ns"]) == entry.mtime_ns
        and int(cached["is_missing"]) == 0
        and (
            bool(cached["error"])
            or (
                cached["checkpoint_offset"] is not None
                and int(cached["checkpoint_offset"]) == entry.size_bytes
            )
        )
    )


def promote_cached_session_owners(
    connection: sqlite3.Connection,
    inventory: list[SessionFileInventoryEntry],
    cached_rows: dict[str, sqlite3.Row],
    *,
    rebuilt: bool,
    entry_priority: Callable[[SessionFileInventoryEntry], tuple[int, int, str]],
) -> set[str]:
    """Promote a reusable current owner only when it has highest priority.

    Inventory discovery deliberately begins with path-based keys so duplicate
    active/archive JSONL files can coexist. Once both complete generations are
    cached, an ownership handoff can be resolved without reopening either file:
    the complete winner is moved to its session-id key in this transaction.
    """
    current_by_session_id: dict[str, list[int]] = {}
    for index, entry in enumerate(inventory):
        cached = cached_rows.get(entry.file_key)
        session_id = _complete_cached_session_id(connection, entry.file_key, cached)
        if session_id:
            current_by_session_id.setdefault(session_id, []).append(index)

    affected_task_ids: set[str] = set()
    for session_id, indexes in current_by_session_id.items():
        winner_index = min(indexes, key=lambda index: entry_priority(inventory[index]))
        winner = inventory[winner_index]
        winner_cached = cached_rows[winner.file_key]
        if winner.file_key == session_id or not is_reusable(
            winner, winner_cached, rebuilt=rebuilt
        ):
            continue

        canonical_entry = replace(
            winner,
            file_key=session_id,
            file_key_is_fallback=False,
        )
        affected_task_ids.update(
            rekey_file_generation(connection, winner, canonical_entry)
        )
        inventory[winner_index] = canonical_entry
    return affected_task_ids


def _complete_cached_session_id(
    connection: sqlite3.Connection,
    file_key: str,
    cached: sqlite3.Row | None,
) -> str:
    if cached is None or not cached["session_id"]:
        return ""
    session_id = str(cached["session_id"])
    metadata = connection.execute(
        """
        select 1
        from session_metadata
        where file_key = ? and session_id = ? and is_missing = 0
        """,
        (file_key, session_id),
    ).fetchone()
    return session_id if metadata is not None else ""
