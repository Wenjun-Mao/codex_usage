from __future__ import annotations

import os
import sqlite3
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
    append_file_generation,
    affected_task_ids_for_file,
    remove_candidate_generation,
    replace_file_generation,
)
from codex_usage.session_cache_refresh_identity import (
    dedupe_inventory_by_cached_session_id as _dedupe_inventory_by_cached_session_id,
    entry_for_successful_generation as _entry_for_successful_generation,
    entry_priority as _entry_priority,
    error_entry as _error_entry,
    group_canonical_winners as _group_canonical_winners,
    replaces_cached_identity as _replaces_cached_identity,
    upsert_pending_inventory_rows as _upsert_pending_inventory_rows,
)
from codex_usage.session_cache_models import CacheRefreshOutcome, CacheStats
from codex_usage.session_cache_ownership import (
    is_reusable,
    promote_cached_session_owners,
)
from codex_usage.session_cache_requests import (
    assert_current_append_checkpoint as _assert_current_append_checkpoint,
    eligible_append_checkpoint as _eligible_append_checkpoint,
    load_cached_rows as _load_cached_rows,
)
from codex_usage.session_cache_results import validated_results as _validated_results
from codex_usage.session_cache_schema import _REPARSE_REQUIRED_ERROR
from codex_usage.session_cache_store import record_file_error, record_file_stale
from codex_usage.session_inventory import (
    SessionFileInventoryEntry,
)

_COMMIT_GROUP_SIZE = 8


def refresh_files(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    inventory: list[SessionFileInventoryEntry],
    *,
    rebuilt: bool,
    max_workers: int | None = None,
    max_parse_bytes: int | None = None,
    max_total_parse_bytes: int | None = None,
    defer_full_fallback: bool = False,
    preferred_paths: tuple[str, ...] = (),
) -> CacheRefreshOutcome:
    cached_rows = _load_cached_rows(connection)
    _reconcile_fallback_file_keys(inventory, cached_rows)
    parse_entries, reused, missing_marked, affected_task_ids = _commit_preflight(
        connection,
        inventory,
        cached_rows,
        rebuilt=rebuilt,
    )
    refreshed_rows = _load_cached_rows(connection)
    request_plans: list[tuple[tuple[object, ...], UsageParseRequest]] = []
    preferred = {_normalized_path(path) for path in preferred_paths}
    for ordinal, entry in parse_entries:
        cached = refreshed_rows.get(entry.file_key)
        checkpoint = _eligible_append_checkpoint(
            connection,
            entry,
            cached,
            rebuilt=rebuilt,
        )
        deferred_reason = ""
        if (
            defer_full_fallback
            and not rebuilt
            and cached is not None
            and cached["checkpoint_offset"] is not None
            and checkpoint is None
        ):
            deferred_reason = (
                "source no longer satisfies the guarded append-only contract"
            )
        request = UsageParseRequest(
            ordinal=ordinal,
            file_key=entry.file_key,
            path=entry.path,
            size_bytes=entry.size_bytes,
            mtime_ns=entry.mtime_ns,
            checkpoint=checkpoint,
            max_bytes=max_parse_bytes,
            defer_full_fallback=defer_full_fallback,
            deferred_full_parse_reason=deferred_reason,
        )
        request_plans.append(
            (
                _request_priority(
                    request,
                    cached,
                    preferred=_normalized_path(entry.path) in preferred,
                ),
                request,
            )
        )
    requests = _apply_total_parse_budget(
        request_plans,
        max_total_parse_bytes=max_total_parse_bytes,
        max_parse_bytes=max_parse_bytes,
    )

    worker_spans: list[WorkerSpan] = []
    all_results: list[UsageParseResult] = []
    file_errors = 0
    identity_replacements = 0
    resolved_max_workers = DEFAULT_MAX_WORKERS if max_workers is None else max_workers
    with OrderedProcessMapper(
        parse_usage_request,
        task_count=len(requests),
        max_workers=resolved_max_workers,
    ) as mapper:
        for request_group in batched(requests, _COMMIT_GROUP_SIZE):
            scheduled_group = tuple(
                sorted(
                    request_group,
                    key=lambda request: (-request.estimated_bytes, request.ordinal),
                )
            )
            results = _validated_results(
                scheduled_group,
                mapper.map_batch(scheduled_group),
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
            all_results.extend(results)
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
        files_full_parsed=sum(
            result.outcome in {"full", "full_fallback"}
            for result in all_results
        ),
        files_appended=sum(result.outcome == "append" for result in all_results),
        append_fallbacks=sum(
            result.outcome in {"full_fallback", "stale"}
            for result in all_results
        ),
        source_bytes_read=sum(result.bytes_read for result in all_results),
        pending_files=sum(
            1
            for entry in inventory
            if _checkpoint_offset(connection, entry.file_key) < entry.size_bytes
        ),
        pending_bytes=sum(
            max(0, entry.size_bytes - _checkpoint_offset(connection, entry.file_key))
            for entry in inventory
        ),
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


def _request_priority(
    request: UsageParseRequest,
    cached: sqlite3.Row | None,
    *,
    preferred: bool,
) -> tuple[object, ...]:
    if request.deferred_full_parse_reason:
        work_kind = 0
    elif (
        request.checkpoint is not None
        and cached is not None
        and int(cached["size_bytes"]) < request.size_bytes
    ):
        work_kind = 1
    elif cached is None:
        work_kind = 2
    else:
        work_kind = 3
    parsed_at = str(cached["parsed_at"] or "") if cached is not None else ""
    return (
        0 if preferred else 1,
        work_kind,
        parsed_at,
        request.estimated_bytes,
        request.ordinal,
    )


def _apply_total_parse_budget(
    request_plans: list[tuple[tuple[object, ...], UsageParseRequest]],
    *,
    max_total_parse_bytes: int | None,
    max_parse_bytes: int | None,
) -> list[UsageParseRequest]:
    if max_total_parse_bytes is None:
        return [request for _, request in request_plans]
    if max_total_parse_bytes < 1:
        raise ValueError("max_total_parse_bytes must be at least one")

    remaining = max_total_parse_bytes
    selected: list[UsageParseRequest] = []
    for _, request in sorted(request_plans, key=lambda item: item[0]):
        if request.deferred_full_parse_reason:
            selected.append(request)
            continue
        if remaining <= 0:
            continue
        request_limit = remaining
        if max_parse_bytes is not None:
            request_limit = min(request_limit, max_parse_bytes)
        request_limit = max(1, request_limit)
        selected.append(replace(request, max_bytes=request_limit))
        remaining -= min(request.estimated_bytes, request_limit)
    return selected


def _normalized_path(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(path))))


def _checkpoint_offset(connection: sqlite3.Connection, file_key: str) -> int:
    row = connection.execute(
        "select byte_offset from parser_checkpoints where file_key = ?",
        (file_key,),
    ).fetchone()
    return int(row["byte_offset"]) if row is not None else 0


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
        _upsert_pending_inventory_rows(connection, inventory, now)
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
        result.metadata.session_id
        for result in results
        if not result.error and result.outcome != "stale"
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
            elif result.outcome == "stale":
                record_file_stale(
                    connection,
                    session_dirs,
                    entry,
                    result.fallback_reason,
                )
            else:
                if result.appended is not None:
                    _assert_current_append_checkpoint(
                        connection,
                        file_key=result.request.file_key,
                        path=result.request.path,
                        expected=result.request.checkpoint,
                    )
                    affected_task_ids.update(
                        append_file_generation(
                            connection,
                            session_dirs,
                            entry,
                            result.appended,
                        )
                    )
                    continue
                if result.generation is None:
                    raise ValueError("successful usage parse result lacks parsed data")
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


def _mark_transition_tasks_dirty(
    connection: sqlite3.Connection, task_ids: set[str]
) -> None:
    connection.executemany(
        "insert or ignore into dirty_transition_tasks (thread_id) values (?)",
        [(task_id,) for task_id in sorted(task_ids) if task_id],
    )
