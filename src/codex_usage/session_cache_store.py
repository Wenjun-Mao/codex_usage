from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.models import UsageRecord
from codex_usage.session_cache_models import CachedFileSummary
from codex_usage.session_cache_queries import row_to_usage_record
from codex_usage.session_files import owning_session_dir
from codex_usage.session_inventory import SessionFileInventoryEntry


def record_file_error(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    entry: SessionFileInventoryEntry,
    error: str,
) -> None:
    now = datetime.now(UTC).isoformat()
    existing = connection.execute(
        "select 1 from files where file_key = ?", (entry.file_key,)
    ).fetchone()
    if existing is not None:
        connection.execute(
            """
            update files
            set last_seen_at = ?, missing_since = null, is_missing = 0, error = ?
            where file_key = ?
            """,
            (now, error, entry.file_key),
        )
        connection.execute(
            "update session_metadata set is_missing = 0 where file_key = ?",
            (entry.file_key,),
        )
        return
    connection.execute(
        """
        insert into files
            (
                file_key, path, session_dir, storage_state, size_bytes, mtime_ns,
                parsed_at, last_seen_at, missing_since, is_missing, session_id, error
            )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.file_key,
            str(entry.path),
            str(owning_session_dir(entry.path, session_dirs)),
            entry.storage_state,
            entry.size_bytes,
            entry.mtime_ns,
            now,
            now,
            "",
            0,
            entry.path.stem,
            error,
        ),
    )


def record_file_stale(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    entry: SessionFileInventoryEntry,
    reason: str,
) -> None:
    """Retain trusted rows while recording the newer source snapshot as stale."""
    now = datetime.now(UTC).isoformat()
    cursor = connection.execute(
        """
        update files set
            path = ?, session_dir = ?, storage_state = ?, size_bytes = ?,
            mtime_ns = ?, last_seen_at = ?, missing_since = null,
            is_missing = 0, error = ?
        where file_key = ?
        """,
        (
            str(entry.path),
            str(owning_session_dir(entry.path, session_dirs)),
            entry.storage_state,
            entry.size_bytes,
            entry.mtime_ns,
            now,
            f"stale append checkpoint: {reason}",
            entry.file_key,
        ),
    )
    if cursor.rowcount != 1:
        raise RuntimeError(
            f"cannot retain stale source without a trusted generation: {entry.file_key}"
        )
    connection.execute(
        """
        update session_metadata
        set file_path = ?, session_dir = ?, storage_state = ?, is_missing = 0,
            session_bytes = ?, estimated_sync_bytes = ?
        where file_key = ?
        """,
        (
            str(entry.path),
            str(owning_session_dir(entry.path, session_dirs)),
            entry.storage_state,
            entry.size_bytes,
            entry.size_bytes + 4096,
            entry.file_key,
        ),
    )


def _load_records_by_file_key(
    connection: sqlite3.Connection, selected_keys: set[str]
) -> dict[str, list[UsageRecord]]:
    if not selected_keys:
        return {}
    records_by_file: dict[str, list[UsageRecord]] = {}
    for row in connection.execute(
        "select * from usage_records order by file_key, record_index"
    ):
        if row["file_key"] not in selected_keys:
            continue
        records_by_file.setdefault(str(row["file_key"]), []).append(
            row_to_usage_record(row)
        )
    return records_by_file


def _load_file_summaries(
    connection: sqlite3.Connection,
    inventory: list[SessionFileInventoryEntry],
    session_dirs: list[Path],
) -> dict[Path, CachedFileSummary]:
    selected = {entry.file_key for entry in inventory}
    summaries: dict[Path, CachedFileSummary] = {}
    for row in connection.execute("select * from session_metadata"):
        if row["file_key"] not in selected:
            continue
        path = Path(row["file_path"])
        summaries[path] = CachedFileSummary(
            file_path=path,
            session_dir=Path(row["session_dir"])
            if row["session_dir"]
            else owning_session_dir(path, session_dirs),
            session_id=row["session_id"],
            cwd=row["cwd"] or "",
            project_key=row["project_key"] or "",
            project_label=row["project_label"] or "",
            project_aliases=tuple(json.loads(row["project_aliases_json"] or "[]")),
            git_repository_url=row["git_repository_url"] or "",
            git_branch=row["git_branch"] or "",
            memory_mode=row["memory_mode"] or "",
            has_base_instructions=bool(row["has_base_instructions"]),
            session_bytes=int(row["session_bytes"]),
            estimated_sync_bytes=int(row["estimated_sync_bytes"]),
            file_key=row["file_key"] or "",
            storage_state=row["storage_state"] or "active",
            is_missing=bool(row["is_missing"]),
        )
    return summaries


def _load_file_errors(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row["path"]): str(row["error"])
        for row in connection.execute(
            "select path, error from files where error is not null and error != ''"
        )
    }


def _missing_file_keys(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row["file_key"])
        for row in connection.execute("select file_key from files where is_missing = 1")
    }


def _retained_missing_files(connection: sqlite3.Connection) -> list[Path]:
    return [
        Path(row["path"])
        for row in connection.execute(
            "select path from files where is_missing = 1 order by path"
        )
    ]
