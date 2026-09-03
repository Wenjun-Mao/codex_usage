from __future__ import annotations

import sqlite3
from dataclasses import replace

from codex_usage.parallel.usage import UsageParseResult
from codex_usage.session_cache_generations import rekey_file_generation
from codex_usage.session_generation_models import ParsedSessionGeneration
from codex_usage.session_inventory import (
    SessionFileInventoryEntry,
    _path_fallback_file_key,
)


def group_canonical_winners(
    results: tuple[UsageParseResult, ...],
    inventory: list[SessionFileInventoryEntry],
) -> dict[str, int]:
    winners: dict[str, int] = {}
    for result in results:
        if result.error or result.generation is None:
            continue
        session_id = result.generation.metadata.session_id
        current = winners.get(session_id)
        if current is None or entry_priority(
            inventory[result.request.ordinal]
        ) < entry_priority(inventory[current]):
            winners[session_id] = result.request.ordinal
    return winners


def entry_for_successful_generation(
    connection: sqlite3.Connection,
    inventory: list[SessionFileInventoryEntry],
    result: UsageParseResult,
    group_winners: dict[str, int],
) -> tuple[SessionFileInventoryEntry, set[str]]:
    if result.generation is None:
        raise ValueError("successful usage parse result lacks generation")
    original_entry = inventory[result.request.ordinal]
    session_id = result.generation.metadata.session_id
    if group_winners[session_id] != result.request.ordinal:
        return fallback_duplicate_entry(original_entry), set()

    canonical_entry = _entry_with_generation_identity(
        original_entry, result.generation
    )
    existing_index = _canonical_duplicate_index(
        inventory, result.request.ordinal, session_id
    )
    if existing_index is None:
        return canonical_entry, set()

    existing_entry = inventory[existing_index]
    if entry_priority(existing_entry) <= entry_priority(canonical_entry):
        return fallback_duplicate_entry(original_entry), set()

    replacement = fallback_duplicate_entry(existing_entry)
    inventory[existing_index] = replacement
    affected = rekey_file_generation(connection, existing_entry, replacement)
    return canonical_entry, affected


def error_entry(
    entry: SessionFileInventoryEntry,
    successful_task_ids: set[str],
) -> SessionFileInventoryEntry:
    if not entry.file_key_is_fallback or entry.file_key not in successful_task_ids:
        return entry
    return replace(entry, file_key=_path_fallback_file_key(entry.path))


def replaces_cached_identity(
    connection: sqlite3.Connection,
    existing_entry: SessionFileInventoryEntry,
    replacement_entry: SessionFileInventoryEntry,
) -> bool:
    if existing_entry.file_key == replacement_entry.file_key:
        return False
    return (
        connection.execute(
            """
            select 1 from files
            where file_key = ? and path = ? and parsed_at != ''
            """,
            (existing_entry.file_key, str(existing_entry.path)),
        ).fetchone()
        is not None
    )


def upsert_pending_inventory_rows(
    connection: sqlite3.Connection,
    inventory: list[SessionFileInventoryEntry],
    now: str,
) -> None:
    """Represent every discovered source before the parse budget is applied."""
    connection.executemany(
        """
        insert into files (
            file_key, path, session_dir, storage_state, size_bytes, mtime_ns,
            parsed_at, last_seen_at, missing_since, is_missing, session_id, error
        ) values (?, ?, ?, ?, ?, ?, '', ?, null, 0, null, null)
        on conflict(file_key) do update set
            path = excluded.path,
            session_dir = excluded.session_dir,
            storage_state = excluded.storage_state,
            size_bytes = excluded.size_bytes,
            mtime_ns = excluded.mtime_ns,
            last_seen_at = excluded.last_seen_at,
            missing_since = null,
            is_missing = 0
        where files.parsed_at = ''
          and coalesce(files.error, '') = ''
          and not exists (
              select 1 from parser_checkpoints
              where parser_checkpoints.file_key = excluded.file_key
          )
        """,
        (
            (
                entry.file_key,
                str(entry.path),
                str(entry.session_dir),
                entry.storage_state,
                entry.size_bytes,
                entry.mtime_ns,
                now,
            )
            for entry in inventory
        ),
    )


def dedupe_inventory_by_cached_session_id(
    inventory: list[SessionFileInventoryEntry],
    cached_rows: dict[str, sqlite3.Row],
) -> None:
    selected: dict[str, SessionFileInventoryEntry] = {}
    for entry in inventory:
        cached = cached_rows.get(entry.file_key)
        session_id = (
            str(cached["session_id"])
            if cached is not None and cached["session_id"] and not cached["error"]
            else entry.file_key
        )
        existing = selected.get(session_id)
        if existing is None or entry_priority(entry) < entry_priority(existing):
            selected[session_id] = entry
    inventory[:] = sorted(
        selected.values(), key=lambda entry: str(entry.path).casefold()
    )


def entry_priority(entry: SessionFileInventoryEntry) -> tuple[int, int, str]:
    storage_priority = (
        0
        if entry.storage_state == "active"
        else 1 if entry.storage_state == "archived" else 2
    )
    return (storage_priority, -entry.mtime_ns, str(entry.path).casefold())


def _entry_with_generation_identity(
    entry: SessionFileInventoryEntry,
    generation: ParsedSessionGeneration,
) -> SessionFileInventoryEntry:
    session_id = generation.metadata.session_id
    if not session_id or session_id == entry.file_key:
        return entry
    return replace(entry, file_key=session_id, file_key_is_fallback=False)


def fallback_duplicate_entry(
    entry: SessionFileInventoryEntry,
) -> SessionFileInventoryEntry:
    if entry.file_key_is_fallback:
        return entry
    return replace(
        entry,
        file_key=_path_fallback_file_key(entry.path),
        file_key_is_fallback=True,
    )


def _canonical_duplicate_index(
    inventory: list[SessionFileInventoryEntry],
    current_index: int,
    session_id: str,
) -> int | None:
    candidates = [
        index
        for index, entry in enumerate(inventory)
        if index != current_index and entry.file_key == session_id
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda index: entry_priority(inventory[index]))
