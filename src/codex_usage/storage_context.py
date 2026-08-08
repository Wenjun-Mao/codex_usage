from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

import codex_usage.session_cache_schema as _schema
from codex_usage.session_cache import CACHE_DB_NAME, resolve_cache_dir
from codex_usage.session_inventory import (
    SessionFileInventoryEntry,
    collect_session_file_inventory,
    find_session_dirs,
)
from codex_usage.storage_insights import (
    TaskStorageInsights,
    build_task_storage_insights,
)
from codex_usage.storage_metadata import (
    StorageFile,
    StorageMetadataRefreshStats,
    inspect_storage_files,
    load_present_storage_files,
    refresh_storage_file_metadata,
)


@dataclass(frozen=True, slots=True)
class StorageContext:
    session_dirs: tuple[Path, ...]
    inventory: tuple[SessionFileInventoryEntry, ...]
    files: tuple[StorageFile, ...]
    insights: TaskStorageInsights
    refresh_stats: StorageMetadataRefreshStats
    direct_fallback: bool = False


def load_storage_context(
    *,
    session_dirs: list[Path] | None = None,
    cache_dir: Path | None = None,
) -> StorageContext:
    """Refresh bounded storage metadata without parsing usage-event bodies."""
    resolved_session_dirs = session_dirs or find_session_dirs()
    inventory = tuple(
        collect_session_file_inventory(resolved_session_dirs, read_metadata=False)
    )
    try:
        files, stats = _load_cached_storage_files(
            resolved_session_dirs,
            inventory,
            cache_dir=cache_dir,
        )
        direct_fallback = False
    except (OSError, sqlite3.Error):
        files = inspect_storage_files(inventory)
        stats = StorageMetadataRefreshStats(metadata_reads=len(files))
        direct_fallback = True
    return StorageContext(
        session_dirs=tuple(resolved_session_dirs),
        inventory=inventory,
        files=files,
        insights=build_task_storage_insights(files, resolved_session_dirs),
        refresh_stats=stats,
        direct_fallback=direct_fallback,
    )


def _sqlite_is_transient(error: BaseException) -> bool:
    return isinstance(error, sqlite3.OperationalError) and any(
        marker in str(error).casefold() for marker in ("locked", "busy", "i/o")
    )


@retry(
    retry=retry_if_exception(_sqlite_is_transient),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _load_cached_storage_files(
    session_dirs: list[Path],
    inventory: tuple[SessionFileInventoryEntry, ...],
    *,
    cache_dir: Path | None,
) -> tuple[tuple[StorageFile, ...], StorageMetadataRefreshStats]:
    resolved_cache_dir = resolve_cache_dir(session_dirs, cache_dir)
    resolved_cache_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved_cache_dir / CACHE_DB_NAME)
    try:
        connection.row_factory = sqlite3.Row
        _schema._ensure_schema(connection)
        stats = refresh_storage_file_metadata(connection, inventory)
        files = load_present_storage_files(connection)
        return files, stats
    finally:
        connection.close()
