from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from itertools import batched
from pathlib import Path

from codex_usage.parallel.execution import (
    DEFAULT_MAX_WORKERS,
    OrderedProcessMapper,
    ParallelRunReport,
    WorkerSpan,
)
from codex_usage.parallel.usage import (
    UsageParseRequest,
    UsageParseResult,
    parse_usage_request,
)
from codex_usage.session_cache_generations import (
    affected_task_ids_for_file,
    rekey_file_generation,
    remove_candidate_generation,
    replace_file_generation,
)
from codex_usage.session_cache_models import CacheRefreshOutcome, CacheStats
from codex_usage.session_cache_ownership import (
    is_reusable,
    promote_cached_session_owners,
)
from codex_usage.session_cache_schema import _REPARSE_REQUIRED_ERROR
from codex_usage.session_cache_store import record_file_error
from codex_usage.session_generation_models import ParsedSessionGeneration
from codex_usage.session_inventory import (
    SessionFileInventoryEntry,
    _path_fallback_file_key,
)

_COMMIT_GROUP_SIZE = 8


def refresh_files(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    inventory: list[SessionFileInventoryEntry],
    *,
    rebuilt: bool,
    max_workers: int | None = None,
) -> CacheRefreshOutcome:
    cached_rows = _load_cached_rows(connection)
    _reconcile_fallback_file_keys(inventory, cached_rows)
    parse_entries, reused, missing_marked, affected_task_ids = _commit_preflight(
        connection,
        inventory,
        cached_rows,
        rebuilt=rebuilt,
    )
    requests = [
        UsageParseRequest(
            ordinal=ordinal,
            file_key=entry.file_key,
            path=entry.path,
            size_bytes=entry.size_bytes,
            mtime_ns=entry.mtime_ns,
        )
        for ordinal, entry in parse_entries
    ]

    worker_spans: list[WorkerSpan] = []
    file_errors = 0
    identity_replacements = 0
    resolved_max_workers = DEFAULT_MAX_WORKERS if max_workers is None else max_workers
    with OrderedProcessMapper(
        parse_usage_request,
        task_count=len(requests),
        max_workers=resolved_max_workers,
    ) as mapper:
        for request_group in batched(requests, _COMMIT_GROUP_SIZE):
            results = _validated_results(
                request_group,
                mapper.map_batch(request_group),
            )
            group_affected_task_ids, group_identity_replacements = (
                _commit_result_group(
                    connection,
                    session_dirs,
                    inventory,
                    results,
                )
            )
            affected_task_ids.update(group_affected_task_ids)
            identity_replacements += group_identity_replacements
            worker_spans.extend(result.span for result in results)
            file_errors += sum(bool(result.error) for result in results)

    _dedupe_inventory_by_cached_session_id(
        inventory, _load_cached_rows(connection)
    )

    missing_count = int(
        connection.execute(
            "select count(*) from files where is_missing = 1"
        ).fetchone()[0]
    )
    stats = CacheStats(
        files_total=len(inventory),
        files_current=len(inventory),
        files_archived=sum(entry.storage_state == "archived" for entry in inventory),
        files_parsed=len(requests),
        files_reused=reused,
        files_removed=missing_marked + identity_replacements,
        files_missing_retained=missing_count,
        file_errors=file_errors,
        rebuilt=rebuilt,
    )
    report = ParallelRunReport(
        resolved_worker_count=mapper.worker_count,
        worker_spans=tuple(worker_spans),
        used_serial_fallback=mapper.used_serial_fallback,
        infrastructure_error=mapper.infrastructure_error,
        file_error_count=file_errors,
    )
    return CacheRefreshOutcome(
        stats=stats,
        usage_run=report,
        affected_task_ids=frozenset(affected_task_ids),
    )


def _load_cached_rows(
    connection: sqlite3.Connection,
) -> dict[str, sqlite3.Row]:
    return {
        str(row["file_key"]): row
        for row in connection.execute(
            """
            select file_key, path, size_bytes, mtime_ns, is_missing, session_id, error
            from files
            """
        )
    }


def _reconcile_fallback_file_keys(
    inventory: list[SessionFileInventoryEntry],
    cached_rows: dict[str, sqlite3.Row],
) -> None:
    owned_current_keys = {entry.file_key for entry in inventory}
    cached_keys_by_path: dict[str, list[str]] = {}
    for file_key, row in cached_rows.items():
        cached_keys_by_path.setdefault(str(row["path"]), []).append(file_key)

    for index, entry in enumerate(inventory):
        if not entry.file_key_is_fallback:
            continue
        matching_keys = cached_keys_by_path.get(str(entry.path), [])
        if len(matching_keys) != 1:
            continue
        replacement_key = matching_keys[0]
        if replacement_key != entry.file_key and replacement_key in owned_current_keys:
            continue
        inventory[index] = replace(entry, file_key=replacement_key)
        owned_current_keys.add(replacement_key)


def _commit_preflight(
    connection: sqlite3.Connection,
    inventory: list[SessionFileInventoryEntry],
    cached_rows: dict[str, sqlite3.Row],
    *,
    rebuilt: bool,
) -> tuple[list[tuple[int, SessionFileInventoryEntry]], int, int, set[str]]:
    now = datetime.now(UTC).isoformat()
    current_keys = {entry.file_key for entry in inventory}
    parse_entries: list[tuple[int, SessionFileInventoryEntry]] = []
    reused = 0
    missing_marked = 0
    affected_task_ids: set[str] = set()

    connection.execute("begin immediate")
    try:
        affected_task_ids.update(
            promote_cached_session_owners(
                connection,
                inventory,
                cached_rows,
                rebuilt=rebuilt,
                entry_priority=_entry_priority,
            )
        )
        cached_rows = _load_cached_rows(connection)
        current_keys = {entry.file_key for entry in inventory}
        for file_key, row in cached_rows.items():
            if file_key in current_keys or int(row["is_missing"]) != 0:
                continue
            affected_task_ids.update(affected_task_ids_for_file(connection, file_key))
            remove_candidate_generation(connection, file_key)
            connection.execute(
                """
                update files
                set is_missing = 1, missing_since = ?, last_seen_at = ?,
                    error = case when error = ? then '' else error end
                where file_key = ?
                """,
                (now, now, _REPARSE_REQUIRED_ERROR, file_key),
            )
            connection.execute(
                "update session_metadata set is_missing = 1 where file_key = ?",
                (file_key,),
            )
            missing_marked += 1

        for ordinal, entry in enumerate(inventory):
            cached = cached_rows.get(entry.file_key)
            if is_reusable(entry, cached, rebuilt=rebuilt):
                connection.execute(
                    "update files set last_seen_at = ? where file_key = ?",
                    (now, entry.file_key),
                )
                reused += 1
            else:
                parse_entries.append((ordinal, entry))

        _mark_transition_tasks_dirty(connection, affected_task_ids)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return parse_entries, reused, missing_marked, affected_task_ids


def _validated_results(
    requests: Sequence[UsageParseRequest],
    results: Sequence[UsageParseResult],
) -> tuple[UsageParseResult, ...]:
    if len(results) != len(requests):
        raise ValueError("usage parse result count does not match request count")
    expected_by_ordinal = {request.ordinal: request for request in requests}
    if len(expected_by_ordinal) != len(requests):
        raise ValueError("usage parse requests contain duplicate ordinals")

    seen: set[int] = set()
    for result in results:
        ordinal = result.request.ordinal
        if ordinal in seen:
            raise ValueError("usage parse results contain duplicate ordinals")
        if expected_by_ordinal.get(ordinal) != result.request:
            raise ValueError("usage parse result does not match its request")
        seen.add(ordinal)
    if seen != set(expected_by_ordinal):
        raise ValueError("usage parse results do not cover the complete request group")
    return tuple(sorted(results, key=lambda result: result.request.ordinal))


def _commit_result_group(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    inventory: list[SessionFileInventoryEntry],
    results: tuple[UsageParseResult, ...],
) -> tuple[set[str], int]:
    affected_task_ids: set[str] = set()
    identity_replacements = 0
    group_winners = _group_canonical_winners(results, inventory)
    successful_task_ids = {
        result.generation.metadata.session_id
        for result in results
        if result.error == "" and result.generation is not None
    }
    errors = sorted(
        (result for result in results if result.error),
        key=lambda result: result.request.ordinal,
    )
    successes = sorted(
        (result for result in results if not result.error),
        key=lambda result: (
            _entry_priority(inventory[result.request.ordinal]),
            result.request.ordinal,
        ),
        reverse=True,
    )
    connection.execute("begin immediate")
    try:
        for result in (*errors, *successes):
            entry = inventory[result.request.ordinal]
            if result.error:
                entry = _error_entry(entry, successful_task_ids)
                inventory[result.request.ordinal] = entry
                record_file_error(
                    connection,
                    session_dirs,
                    entry,
                    result.error,
                )
            else:
                if result.generation is None:
                    raise ValueError("successful usage parse result lacks generation")
                entry, duplicate_affected = _entry_for_successful_generation(
                    connection,
                    inventory,
                    result,
                    group_winners,
                )
                affected_task_ids.update(duplicate_affected)
                identity_replacements += int(
                    _replaces_cached_identity(
                        connection,
                        inventory[result.request.ordinal],
                        entry,
                    )
                )
                inventory[result.request.ordinal] = entry
                affected_task_ids.update(
                    replace_file_generation(
                        connection,
                        session_dirs,
                        entry,
                        result.generation,
                    )
                )
        _mark_transition_tasks_dirty(connection, affected_task_ids)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return affected_task_ids, identity_replacements


def _group_canonical_winners(
    results: tuple[UsageParseResult, ...],
    inventory: list[SessionFileInventoryEntry],
) -> dict[str, int]:
    winners: dict[str, int] = {}
    for result in results:
        if result.error or result.generation is None:
            continue
        session_id = result.generation.metadata.session_id
        current = winners.get(session_id)
        if current is None or _entry_priority(
            inventory[result.request.ordinal]
        ) < _entry_priority(inventory[current]):
            winners[session_id] = result.request.ordinal
    return winners


def _entry_for_successful_generation(
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
        return _fallback_duplicate_entry(original_entry), set()

    canonical_entry = _entry_with_generation_identity(
        original_entry, result.generation
    )
    existing_index = _canonical_duplicate_index(
        inventory, result.request.ordinal, session_id
    )
    if existing_index is None:
        return canonical_entry, set()

    existing_entry = inventory[existing_index]
    if _entry_priority(existing_entry) <= _entry_priority(canonical_entry):
        return _fallback_duplicate_entry(original_entry), set()

    replacement = _fallback_duplicate_entry(existing_entry)
    inventory[existing_index] = replacement
    return canonical_entry, rekey_file_generation(connection, existing_entry, replacement)


def _entry_with_generation_identity(
    entry: SessionFileInventoryEntry,
    generation: ParsedSessionGeneration,
) -> SessionFileInventoryEntry:
    session_id = generation.metadata.session_id
    if not session_id or session_id == entry.file_key:
        return entry
    return replace(entry, file_key=session_id, file_key_is_fallback=False)


def _fallback_duplicate_entry(
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
    return min(candidates, key=lambda index: _entry_priority(inventory[index]))


def _error_entry(
    entry: SessionFileInventoryEntry,
    successful_task_ids: set[str],
) -> SessionFileInventoryEntry:
    if not entry.file_key_is_fallback or entry.file_key not in successful_task_ids:
        return entry
    return replace(entry, file_key=_path_fallback_file_key(entry.path))


def _replaces_cached_identity(
    connection: sqlite3.Connection,
    existing_entry: SessionFileInventoryEntry,
    replacement_entry: SessionFileInventoryEntry,
) -> bool:
    if existing_entry.file_key == replacement_entry.file_key:
        return False
    return connection.execute(
        "select 1 from files where file_key = ? and path = ?",
        (existing_entry.file_key, str(existing_entry.path)),
    ).fetchone() is not None


def _dedupe_inventory_by_cached_session_id(
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
        if existing is None or _entry_priority(entry) < _entry_priority(existing):
            selected[session_id] = entry
    inventory[:] = sorted(
        selected.values(), key=lambda entry: str(entry.path).casefold()
    )


def _entry_priority(entry: SessionFileInventoryEntry) -> tuple[int, int, str]:
    storage_priority = (
        0
        if entry.storage_state == "active"
        else 1 if entry.storage_state == "archived" else 2
    )
    return (storage_priority, -entry.mtime_ns, str(entry.path).casefold())


def _mark_transition_tasks_dirty(
    connection: sqlite3.Connection, task_ids: set[str]
) -> None:
    connection.executemany(
        "insert or ignore into dirty_transition_tasks (thread_id) values (?)",
        [(task_id,) for task_id in sorted(task_ids) if task_id],
    )
