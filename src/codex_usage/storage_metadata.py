from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

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
from codex_usage.session_files import (
    load_all_index_entries,
    read_session_metadata_bounded,
    session_index_path_for_session_dir,
)
from codex_usage.session_cache_schema import STORAGE_METADATA_CACHE_VERSION
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
    task_title: str
    metadata_diagnostic: str


@dataclass(frozen=True, slots=True)
class _IndexFingerprint:
    path: str
    size_bytes: int
    mtime_ns: int


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
    metadata_contract_is_current = _metadata_contract_is_current(connection)
    current_paths = {str(entry.path) for entry in entries}
    fingerprints_by_index_path = {
        str(index_path): _index_fingerprint(index_path)
        for index_path in dict.fromkeys(
            session_index_path_for_session_dir(entry.session_dir) for entry in entries
        )
    }
    index_fingerprints = {
        str(entry.path): fingerprints_by_index_path[
            str(session_index_path_for_session_dir(entry.session_dir))
        ]
        for entry in entries
    }
    changed_entries = tuple(
        entry
        for entry in entries
        if not metadata_contract_is_current
        or not _storage_file_is_reusable(entry, existing.get(str(entry.path)))
    )
    changed_paths = {str(entry.path) for entry in changed_entries}
    title_refresh_entries = tuple(
        entry
        for entry in entries
        if str(entry.path) not in changed_paths
        and not _title_index_is_reusable(
            existing.get(str(entry.path)), index_fingerprints[str(entry.path)]
        )
    )
    index_entries = (
        load_all_index_entries(
            list(dict.fromkeys(entry.session_dir for entry in entries))
        )
        if changed_entries or title_refresh_entries
        else {}
    )
    changed_files = {
        str(entry.path): _inspect_storage_file(entry, index_entries)
        for entry in changed_entries
    }
    now = datetime.now(UTC).isoformat()
    metadata_reads = len(changed_files)
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
            index_fingerprint = index_fingerprints[path]
            if path not in changed_paths:
                if _title_index_is_reusable(cached, index_fingerprint):
                    connection.execute(
                        "update storage_files set last_seen_at = ? where path = ?",
                        (now, path),
                    )
                else:
                    assert cached is not None
                    connection.execute(
                        """
                        update storage_files
                        set last_seen_at = ?, task_title = ?, title_index_path = ?,
                            title_index_size = ?, title_index_mtime_ns = ?
                        where path = ?
                        """,
                        (
                            now,
                            _task_title(
                                index_entries,
                                str(cached["task_id"]),
                                str(cached["project_label"]),
                            ),
                            index_fingerprint.path,
                            index_fingerprint.size_bytes,
                            index_fingerprint.mtime_ns,
                            path,
                        ),
                    )
                reused += 1
                continue

            storage_file = changed_files[path]
            connection.execute(
                """
                insert into storage_files (
                    path, session_dir, storage_state, size_bytes, mtime_ns,
                    last_seen_at, is_missing, task_id, parent_task_id, usage_role,
                    project_key, project_label, project_aliases_json, task_title,
                    title_index_path, title_index_size, title_index_mtime_ns,
                    metadata_diagnostic
                ) values (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    task_title = excluded.task_title,
                    title_index_path = excluded.title_index_path,
                    title_index_size = excluded.title_index_size,
                    title_index_mtime_ns = excluded.title_index_mtime_ns,
                    metadata_diagnostic = excluded.metadata_diagnostic
                """,
                (
                    path,
                    str(entry.session_dir),
                    entry.storage_state,
                    entry.size_bytes,
                    entry.mtime_ns,
                    now,
                    storage_file.task_id,
                    storage_file.parent_task_id,
                    storage_file.usage_role,
                    storage_file.project_key,
                    storage_file.project_label,
                    json.dumps(storage_file.project_aliases),
                    storage_file.task_title,
                    index_fingerprint.path,
                    index_fingerprint.size_bytes,
                    index_fingerprint.mtime_ns,
                    storage_file.metadata_diagnostic,
                ),
            )
        connection.execute(
            """
            insert into schema_meta (key, value) values (?, ?)
            on conflict(key) do update set value = excluded.value
            """,
            ("storage_metadata_version", str(STORAGE_METADATA_CACHE_VERSION)),
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


def inspect_storage_files(
    inventory: Iterable[SessionFileInventoryEntry],
) -> tuple[StorageFile, ...]:
    entries = tuple(inventory)
    session_dirs = list(dict.fromkeys(entry.session_dir for entry in entries))
    index_entries = load_all_index_entries(session_dirs) if entries else {}
    return tuple(_inspect_storage_file(entry, index_entries) for entry in entries)


def _inspect_storage_file(
    entry: SessionFileInventoryEntry,
    index_entries: dict[str, dict[str, object]],
) -> StorageFile:
    read = read_session_metadata_bounded(entry.path)
    if read.metadata is None:
        task_id = entry.path.stem
        parent_task_id = ""
        usage_role = ROOT_USAGE_ROLE
        project_key = normalize_declared_project_key(task_id)
        project_label = task_id
        project_aliases: tuple[str, ...] = ()
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
                normalize_declared_project_key(value) for value in identity.aliases
            )
            if alias and alias != project_key
        )
    task_title = _task_title(index_entries, task_id, project_label)
    return StorageFile(
        path=str(entry.path),
        session_dir=str(entry.session_dir),
        storage_state=entry.storage_state,
        size_bytes=entry.size_bytes,
        mtime_ns=entry.mtime_ns,
        task_id=task_id,
        parent_task_id=parent_task_id,
        usage_role=usage_role,
        project_key=project_key,
        project_label=project_label,
        project_aliases=project_aliases,
        task_title=task_title,
        metadata_diagnostic=read.diagnostic,
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
        and str(cached["metadata_diagnostic"]) != "session_meta_unreadable"
    )


def _metadata_contract_is_current(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "select value from schema_meta where key = 'storage_metadata_version'"
    ).fetchone()
    return bool(
        row is not None and str(row["value"]) == str(STORAGE_METADATA_CACHE_VERSION)
    )


def _title_index_is_reusable(
    cached: sqlite3.Row | None,
    fingerprint: _IndexFingerprint,
) -> bool:
    return bool(
        cached is not None
        and str(cached["title_index_path"]) == fingerprint.path
        and int(cached["title_index_size"]) == fingerprint.size_bytes
        and int(cached["title_index_mtime_ns"]) == fingerprint.mtime_ns
    )


def _index_fingerprint(index_path: Path) -> _IndexFingerprint:
    try:
        stat = index_path.stat()
    except OSError:
        return _IndexFingerprint(str(index_path), -1, -1)
    return _IndexFingerprint(str(index_path), stat.st_size, stat.st_mtime_ns)


def _task_title(
    index_entries: dict[str, dict[str, object]],
    task_id: str,
    fallback: str,
) -> str:
    index_entry = index_entries.get(task_id, {})
    return str(
        index_entry.get("thread_name")
        or index_entry.get("title")
        or fallback
        or task_id
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
        task_title=str(row["task_title"]),
        metadata_diagnostic=str(row["metadata_diagnostic"]),
    )


def _parse_storage_role(value: object) -> UsageRole:
    return SUBAGENT_USAGE_ROLE if value == SUBAGENT_USAGE_ROLE else ROOT_USAGE_ROLE
