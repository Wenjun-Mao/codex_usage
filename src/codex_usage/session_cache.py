from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import codex_usage.session_cache_schema as _schema
import codex_usage.session_cache_refresh as _refresh
import codex_usage.session_cache_store as _store
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.parser import finalize_session_records, parse_session_file, parse_timestamp
from codex_usage.project_identity import resolve_project_identity
from codex_usage.project_transitions import (
    ProjectTransition,
    apply_project_transitions,
    collect_repo_path_observations,
    infer_project_transitions,
)
from codex_usage.session_cache_models import (
    CacheStats,
    CachedFileSummary,
    CachedRowsSnapshot,
    CachedSessionData,
)
from codex_usage.session_cache_schema import (
    CACHE_SCHEMA_VERSION,
    PARSER_CACHE_VERSION,
    PROJECT_TRANSITION_CACHE_VERSION,
)
from codex_usage.session_files import owning_session_dir, read_session_metadata
from codex_usage.session_inventory import SessionFileInventoryEntry, collect_session_file_inventory

CACHE_DB_NAME = "usage-cache.sqlite3"


def uncached_session_data(
    session_dirs: list[Path],
    files: list[Path],
    records: list[UsageRecord],
    project_transitions: list[ProjectTransition],
) -> CachedSessionData:
    return CachedSessionData(
        session_dirs=session_dirs,
        files=files,
        records=records,
        file_summaries={},
        project_transitions=project_transitions,
        stats=CacheStats(files_total=len(files), files_current=len(files)),
        file_errors={},
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


def load_cached_session_data(
    session_dirs: list[Path],
    *,
    cache_dir: Path | None = None,
    auto_transitions: bool = True,
    max_workers: int | None = None,
) -> CachedSessionData:
    resolved_cache_dir = resolve_cache_dir(session_dirs, cache_dir)
    resolved_cache_dir.mkdir(parents=True, exist_ok=True)
    inventory = collect_session_file_inventory(session_dirs)
    session_files = [entry.path for entry in inventory]
    with sqlite3.connect(resolved_cache_dir / CACHE_DB_NAME) as connection:
        connection.row_factory = sqlite3.Row
        rebuilt = _schema._ensure_schema(connection)
        stats, usage_run = _refresh.refresh_files(
            connection,
            session_dirs,
            inventory,
            rebuilt=rebuilt,
            max_workers=max_workers,
        )
        current_keys = {entry.file_key for entry in inventory}
        missing_keys = _store._missing_file_keys(connection)
        records_by_file_key = _store._load_records_by_file_key(connection, current_keys | missing_keys)
        ordered_keys = [entry.file_key for entry in inventory] + sorted(missing_keys - current_keys)
        records = finalize_session_records([records_by_file_key.get(file_key, []) for file_key in ordered_keys])
        transitions = _store._refresh_or_load_transitions(
            connection,
            session_dirs=session_dirs,
            session_files=session_files,
            records=records,
            auto_transitions=auto_transitions,
        )
        if auto_transitions:
            records = apply_project_transitions(records, transitions)
        summaries = _store._load_file_summaries(connection, inventory, session_dirs)
        errors = _store._load_file_errors(connection)
        retained_missing_files = _store._retained_missing_files(connection)
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
    )
