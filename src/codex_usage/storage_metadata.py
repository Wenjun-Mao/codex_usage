from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from codex_usage.models import (
    ROOT_USAGE_ROLE,
    SUBAGENT_USAGE_ROLE,
    UsageRole,
    usage_role_from_is_subagent,
)
from codex_usage.project_identity import (
    normalize_declared_project_key,
    resolve_project_identity,
)
from codex_usage.session_files import read_session_metadata_bounded
from codex_usage.session_inventory import SessionFileInventoryEntry


@dataclass(frozen=True, slots=True)
class StorageMetadataRefreshStats:
    metadata_reads: int = 0
    files_reused: int = 0
    files_missing_marked: int = 0


@dataclass(frozen=True, slots=True)
class StorageFile:
    path: str
    session_dir: str
    storage_state: str
    size_bytes: int
    mtime_ns: int
    task_id: str
    parent_task_id: str
    usage_role: UsageRole
    project_key: str
    project_label: str
    project_aliases: tuple[str, ...]
    metadata_diagnostic: str


def refresh_storage_file_metadata(
    connection: sqlite3.Connection,
    inventory: Iterable[SessionFileInventoryEntry],
) -> StorageMetadataRefreshStats:
    """Refresh path-keyed storage metadata without touching unchanged JSONLs."""
    entries = tuple(inventory)
    existing = {
        str(row["path"]): row
        for row in connection.execute("select * from storage_files")
    }
    current_paths = {str(entry.path) for entry in entries}
    now = datetime.now(UTC).isoformat()
    metadata_reads = 0
    reused = 0
    missing_marked = 0

    connection.execute("begin immediate")
    try:
        for path, row in existing.items():
            if path in current_paths or int(row["is_missing"]):
                continue
            connection.execute(
                """
                update storage_files
                set is_missing = 1, last_seen_at = ?
                where path = ?
                """,
                (now, path),
            )
            missing_marked += 1

        for entry in entries:
            path = str(entry.path)
            cached = existing.get(path)
            if _storage_file_is_reusable(entry, cached):
                connection.execute(
                    "update storage_files set last_seen_at = ? where path = ?",
                    (now, path),
                )
                reused += 1
                continue

            metadata_reads += 1
            read = read_session_metadata_bounded(entry.path)
            if read.metadata is None:
                task_id = entry.path.stem
                parent_task_id = ""
                usage_role = ROOT_USAGE_ROLE
                project_key = normalize_declared_project_key(task_id)
                project_label = task_id
                project_aliases: tuple[str, ...] = ()
                diagnostic = read.diagnostic
            else:
                metadata = read.metadata
                identity = resolve_project_identity(metadata)
                task_id = metadata.session_id or entry.path.stem
                parent_task_id = metadata.parent_thread_id.strip()
                usage_role = usage_role_from_is_subagent(metadata.is_subagent)
                project_key = normalize_declared_project_key(identity.key) or task_id
                project_label = identity.label or task_id
                project_aliases = tuple(
                    alias
                    for alias in (
                        normalize_declared_project_key(value)
                        for value in identity.aliases
                    )
                    if alias and alias != project_key
                )
                diagnostic = read.diagnostic
            connection.execute(
                """
                insert into storage_files (
                    path, session_dir, storage_state, size_bytes, mtime_ns,
                    last_seen_at, is_missing, task_id, parent_task_id, usage_role,
                    project_key, project_label, project_aliases_json, metadata_diagnostic
                ) values (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
                on conflict(path) do update set
                    session_dir = excluded.session_dir,
                    storage_state = excluded.storage_state,
                    size_bytes = excluded.size_bytes,
                    mtime_ns = excluded.mtime_ns,
                    last_seen_at = excluded.last_seen_at,
                    is_missing = 0,
                    task_id = excluded.task_id,
                    parent_task_id = excluded.parent_task_id,
                    usage_role = excluded.usage_role,
                    project_key = excluded.project_key,
                    project_label = excluded.project_label,
                    project_aliases_json = excluded.project_aliases_json,
                    metadata_diagnostic = excluded.metadata_diagnostic
                """,
                (
                    path,
                    str(entry.session_dir),
                    entry.storage_state,
                    entry.size_bytes,
                    entry.mtime_ns,
                    now,
                    task_id,
                    parent_task_id,
                    usage_role,
                    project_key,
                    project_label,
                    json.dumps(project_aliases),
                    diagnostic,
                ),
            )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return StorageMetadataRefreshStats(
        metadata_reads=metadata_reads,
        files_reused=reused,
        files_missing_marked=missing_marked,
    )


def load_present_storage_files(
    connection: sqlite3.Connection,
) -> tuple[StorageFile, ...]:
    return tuple(
        _storage_file_from_row(row)
        for row in connection.execute(
            "select * from storage_files where is_missing = 0 order by path"
        )
    )


def _storage_file_is_reusable(
    entry: SessionFileInventoryEntry,
    cached: sqlite3.Row | None,
) -> bool:
    return bool(
        cached is not None
        and int(cached["is_missing"]) == 0
        and str(cached["session_dir"]) == str(entry.session_dir)
        and str(cached["storage_state"]) == entry.storage_state
        and int(cached["size_bytes"]) == entry.size_bytes
        and int(cached["mtime_ns"]) == entry.mtime_ns
    )


def _storage_file_from_row(row: sqlite3.Row) -> StorageFile:
    return StorageFile(
        path=str(row["path"]),
        session_dir=str(row["session_dir"]),
        storage_state=str(row["storage_state"]),
        size_bytes=int(row["size_bytes"]),
        mtime_ns=int(row["mtime_ns"]),
        task_id=str(row["task_id"]),
        parent_task_id=str(row["parent_task_id"]),
        usage_role=_parse_storage_role(row["usage_role"]),
        project_key=str(row["project_key"]),
        project_label=str(row["project_label"]),
        project_aliases=tuple(json.loads(row["project_aliases_json"] or "[]")),
        metadata_diagnostic=str(row["metadata_diagnostic"]),
    )


def _parse_storage_role(value: object) -> UsageRole:
    return SUBAGENT_USAGE_ROLE if value == SUBAGENT_USAGE_ROLE else ROOT_USAGE_ROLE
