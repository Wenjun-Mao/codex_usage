from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from pathlib import Path

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import codex_usage.session_cache_queries as _queries
import codex_usage.session_cache_refresh as _refresh
import codex_usage.session_cache_schema as _schema
import codex_usage.session_cache_store as _store
import codex_usage.session_cache_transitions as _cache_transitions
import codex_usage.storage_insights as _storage_insights
import codex_usage.storage_metadata as _storage_metadata
from codex_usage.cache_refresh_lock import acquire_cache_refresh_lock
from codex_usage.aggregation import RangeBounds
from codex_usage.models import UsageRecord
from codex_usage.parallel.execution import EMPTY_PARALLEL_RUN_REPORT
from codex_usage.parser import finalize_session_records
from codex_usage.performance_timing import PhaseTimer
from codex_usage.project_transitions import (
    ProjectTransition,
    apply_project_transitions,
)
from codex_usage.session_cache_models import (
    CachedFileSummary,
    CachedSessionData,
    CacheStats,
)
from codex_usage.session_cache_schema import (
    CACHE_SCHEMA_VERSION,
    PARSER_CACHE_VERSION,
    PROJECT_TRANSITION_CACHE_VERSION,
)
from codex_usage.session_inventory import (
    SessionFileInventoryEntry,
    collect_session_file_inventory,
)

CACHE_DB_NAME = "usage-cache-v8.sqlite3"
LEGACY_CACHE_DB_NAMES = (
    "usage-cache-v7.sqlite3",
    "usage-cache-v6.sqlite3",
    "usage-cache-v5.sqlite3",
    "usage-cache-v4.sqlite3",
    "usage-cache.sqlite3",
)
_STALE_CHECKPOINT_RETRY_COUNT = 1

__all__ = (
    "CACHE_DB_NAME",
    "CACHE_SCHEMA_VERSION",
    "LEGACY_CACHE_DB_NAMES",
    "PARSER_CACHE_VERSION",
    "PROJECT_TRANSITION_CACHE_VERSION",
    "CacheStats",
    "CachedFileSummary",
    "CachedSessionData",
    "load_cached_session_data",
    "resolve_cache_dir",
    "uncached_session_data",
)


@retry(
    retry=retry_if_exception_type(OSError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.01, min=0.01, max=0.04),
    reraise=True,
)
def _remove_legacy_cache_path(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _cleanup_legacy_cache_files(cache_dir: Path) -> int:
    errors = 0
    for database_name in LEGACY_CACHE_DB_NAMES:
        for suffix in ("", "-wal", "-shm"):
            try:
                _remove_legacy_cache_path(cache_dir / f"{database_name}{suffix}")
            except OSError:
                errors += 1
    return errors


def uncached_session_data(
    session_dirs: list[Path],
    files: list[Path],
    records: list[UsageRecord],
    project_transitions: list[ProjectTransition],
    *,
    direct_fallback: bool = False,
    storage_insights: _storage_insights.TaskStorageInsights | None = None,
) -> CachedSessionData:
    return CachedSessionData(
        session_dirs=session_dirs,
        files=files,
        records=records,
        file_summaries={},
        project_transitions=project_transitions,
        stats=CacheStats(
            files_total=len(files),
            files_current=len(files),
            files_parsed=len(files) if direct_fallback else 0,
            files_full_parsed=len(files) if direct_fallback else 0,
            cache_errors=int(direct_fallback),
            direct_fallback=direct_fallback,
        ),
        file_errors={},
        storage_insights=storage_insights,
    )


def resolve_cache_dir(session_dirs: list[Path], cache_dir: Path | None = None) -> Path:
    if cache_dir is not None:
        return cache_dir
    env_value = os.environ.get("CODEX_USAGE_CACHE_DIR", "").strip()
    if env_value:
        return Path(env_value)
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    if codex_home:
        return Path(codex_home).expanduser() / ".codex-usage-cache"
    if session_dirs:
        return session_dirs[0].parent / ".codex-usage-cache"
    return Path.home() / ".codex" / ".codex-usage-cache"


@contextmanager
def _open_cache_connection(path: Path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _refresh_files_with_stale_checkpoint_retry(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    inventory: list[SessionFileInventoryEntry],
    *,
    rebuilt: bool,
    max_workers: int | None,
) -> _refresh.CacheRefreshOutcome:
    for attempt in range(_STALE_CHECKPOINT_RETRY_COUNT + 1):
        try:
            return _refresh.refresh_files(
                connection,
                session_dirs,
                inventory,
                rebuilt=rebuilt,
                max_workers=max_workers,
            )
        except _refresh.StaleAppendCheckpointError:
            if attempt == _STALE_CHECKPOINT_RETRY_COUNT:
                raise
    raise AssertionError("stale checkpoint retry loop exhausted unexpectedly")


def load_cached_session_data(
    session_dirs: list[Path],
    *,
    cache_dir: Path | None = None,
    auto_transitions: bool = True,
    max_workers: int | None = None,
    range_bounds: RangeBounds | None = None,
    timer: PhaseTimer | None = None,
) -> CachedSessionData:
    resolved_cache_dir = resolve_cache_dir(session_dirs, cache_dir)
    resolved_cache_dir.mkdir(parents=True, exist_ok=True)
    if timer is None:
        inventory = collect_session_file_inventory(session_dirs, read_metadata=False)
    else:
        with timer.measure("inventory"):
            inventory = collect_session_file_inventory(session_dirs, read_metadata=False)
    cache_database_path = resolved_cache_dir / CACHE_DB_NAME
    with (
        acquire_cache_refresh_lock(cache_database_path),
        _open_cache_connection(cache_database_path) as connection,
    ):
        connection.row_factory = sqlite3.Row
        schema_state = _schema._ensure_schema(connection)
        legacy_cleanup_errors = _cleanup_legacy_cache_files(resolved_cache_dir)
        physical_inventory = list(inventory)
        if timer is None:
            refresh_outcome = _refresh_files_with_stale_checkpoint_retry(
                connection,
                session_dirs,
                inventory,
                rebuilt=schema_state.created or schema_state.reset,
                max_workers=max_workers,
            )
        else:
            with timer.measure("usage_refresh"):
                refresh_outcome = _refresh_files_with_stale_checkpoint_retry(
                    connection,
                    session_dirs,
                    inventory,
                    rebuilt=schema_state.created or schema_state.reset,
                    max_workers=max_workers,
                )
        storage_refresh = _storage_metadata.refresh_storage_file_metadata(
            connection, physical_inventory
        )
        session_files = [entry.path for entry in inventory]
        stats = refresh_outcome.stats
        usage_run = refresh_outcome.usage_run
        stats = replace(
            stats,
            worker_infrastructure_errors=int(bool(usage_run.infrastructure_error)),
            worker_serial_fallbacks=int(usage_run.used_serial_fallback),
        )
        current_keys = {entry.file_key for entry in inventory}
        missing_keys = _store._missing_file_keys(connection)
        selected_keys = current_keys | missing_keys
        with timer.measure("range_query") if timer else nullcontext():
            if range_bounds is None:
                records_by_file_key = _store._load_records_by_file_key(
                    connection, selected_keys
                )
                ordered_keys = [entry.file_key for entry in inventory] + sorted(
                    missing_keys - current_keys
                )
                records = finalize_session_records(
                    [records_by_file_key.get(file_key, []) for file_key in ordered_keys]
                )
            else:
                records_by_file_key = _queries.load_records_by_file_key_for_range(
                    connection, selected_keys, range_bounds
                )
                ordered_keys = [entry.file_key for entry in inventory] + sorted(
                    missing_keys - current_keys
                )
                range_records = [
                    record
                    for file_key in ordered_keys
                    for record in records_by_file_key.get(file_key, [])
                ]
                identity_records = _queries.load_parent_identity_records(
                    connection,
                    {
                        record.parent_thread_id
                        for record in range_records
                        if record.parent_thread_id
                    },
                )
                records = finalize_session_records(
                    [records_by_file_key.get(file_key, []) for file_key in ordered_keys],
                    identity_records=identity_records,
                )
        with timer.measure("transition_refresh") if timer else nullcontext():
            transitions = _cache_transitions.refresh_dirty_task_transitions(
                connection,
                session_dirs=session_dirs,
                auto_transitions=auto_transitions,
            )
        with timer.measure("range_query") if timer else nullcontext():
            if auto_transitions:
                records = apply_project_transitions(records, transitions)
        summaries = _store._load_file_summaries(connection, inventory, session_dirs)
        errors = _store._load_file_errors(connection)
        retained_missing_files = _store._retained_missing_files(connection)
        storage_insights = _storage_insights.load_task_storage_insights(
            connection, session_dirs
        )
    stats = replace(
        stats,
        legacy_cleanup_errors=legacy_cleanup_errors,
        storage_metadata_reads=storage_refresh.metadata_reads,
        storage_files_reused=storage_refresh.files_reused,
        storage_files_missing_marked=storage_refresh.files_missing_marked,
    )
    return CachedSessionData(
        session_dirs=session_dirs,
        files=session_files,
        records=records,
        file_summaries=summaries,
        project_transitions=transitions,
        stats=stats,
        file_errors=errors,
        retained_missing_files=retained_missing_files,
        usage_run=usage_run,
        transition_run=EMPTY_PARALLEL_RUN_REPORT,
        storage_insights=storage_insights,
    )
