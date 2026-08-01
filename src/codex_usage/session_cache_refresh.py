from __future__ import annotations

import sqlite3
from collections.abc import Sequence
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
from codex_usage.session_cache_models import CacheStats
from codex_usage.session_cache_schema import _REPARSE_REQUIRED_ERROR
from codex_usage.session_cache_store import (
    _set_project_transitions_dirty,
    record_file_error,
    replace_file_generation,
)
from codex_usage.session_inventory import SessionFileInventoryEntry

_COMMIT_GROUP_SIZE = 8


def refresh_files(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    inventory: list[SessionFileInventoryEntry],
    *,
    rebuilt: bool,
    max_workers: int | None = None,
) -> tuple[CacheStats, ParallelRunReport]:
    cached_rows = {
        str(row["file_key"]): row
        for row in connection.execute(
            "select file_key, path, size_bytes, mtime_ns, is_missing, error "
            "from files"
        )
    }
    parse_entries, reused, missing_marked = _commit_preflight(
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
    resolved_max_workers = (
        DEFAULT_MAX_WORKERS if max_workers is None else max_workers
    )
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
            _commit_result_group(
                connection,
                session_dirs,
                inventory,
                results,
            )
            worker_spans.extend(result.span for result in results)
            file_errors += sum(bool(result.error) for result in results)

    missing_count = int(
        connection.execute(
            "select count(*) from files where is_missing = 1"
        ).fetchone()[0]
    )
    stats = CacheStats(
        files_total=len(inventory),
        files_current=len(inventory),
        files_archived=sum(
            entry.storage_state == "archived" for entry in inventory
        ),
        files_parsed=len(requests),
        files_reused=reused,
        files_removed=missing_marked,
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
    return stats, report


def _commit_preflight(
    connection: sqlite3.Connection,
    inventory: list[SessionFileInventoryEntry],
    cached_rows: dict[str, sqlite3.Row],
    *,
    rebuilt: bool,
) -> tuple[list[tuple[int, SessionFileInventoryEntry]], int, int]:
    now = datetime.now(UTC).isoformat()
    current_keys = {entry.file_key for entry in inventory}
    parse_entries: list[tuple[int, SessionFileInventoryEntry]] = []
    reused = 0
    missing_marked = 0

    connection.execute("begin immediate")
    try:
        for file_key, row in cached_rows.items():
            if file_key in current_keys or int(row["is_missing"]) != 0:
                continue
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
            if _is_reusable(entry, cached, rebuilt=rebuilt):
                connection.execute(
                    "update files set last_seen_at = ? where file_key = ?",
                    (now, entry.file_key),
                )
                reused += 1
            else:
                parse_entries.append((ordinal, entry))

        if rebuilt or missing_marked:
            _set_project_transitions_dirty(connection, dirty=True)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return parse_entries, reused, missing_marked


def _is_reusable(
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
        and not cached["error"]
    )


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
) -> None:
    connection.execute("begin immediate")
    try:
        for result in results:
            entry = inventory[result.request.ordinal]
            if result.error:
                record_file_error(
                    connection,
                    session_dirs,
                    entry,
                    result.error,
                )
            else:
                replace_file_generation(
                    connection,
                    session_dirs,
                    entry,
                    result.records,
                )
        _set_project_transitions_dirty(connection, dirty=True)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
