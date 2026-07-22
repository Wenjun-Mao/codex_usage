from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.parser import finalize_session_records, parse_session_file, parse_timestamp
from codex_usage.project_identity import resolve_project_identity
from codex_usage.project_transitions import (
    ProjectTransition,
    apply_project_transitions,
    collect_repo_path_observations,
    infer_project_transitions,
)
from codex_usage.session_files import owning_session_dir, read_session_metadata
from codex_usage.session_inventory import SessionFileInventoryEntry, collect_session_file_inventory

CACHE_DB_NAME = "usage-cache.sqlite3"
CACHE_SCHEMA_VERSION = 3
PARSER_CACHE_VERSION = 2
PROJECT_TRANSITION_CACHE_VERSION = 1
_ESTIMATED_SYNC_METADATA_BYTES = 4096
_REPARSE_REQUIRED_ERROR = "cache schema rebuild requires reparse"
_KNOWN_CACHE_TABLES = frozenset(
    {"schema_meta", "files", "usage_records", "session_metadata", "project_transitions"}
)
_REQUIRED_HISTORY_TABLES = frozenset({"files", "usage_records", "session_metadata"})


@dataclass(frozen=True)
class CacheStats:
    files_total: int = 0
    files_current: int = 0
    files_archived: int = 0
    files_parsed: int = 0
    files_reused: int = 0
    files_removed: int = 0
    files_missing_retained: int = 0
    file_errors: int = 0
    rebuilt: bool = False


@dataclass(frozen=True)
class CachedFileSummary:
    file_path: Path
    session_dir: Path
    session_id: str
    cwd: str
    project_key: str
    project_label: str
    project_aliases: tuple[str, ...]
    git_repository_url: str
    git_branch: str
    memory_mode: str
    has_base_instructions: bool
    session_bytes: int
    estimated_sync_bytes: int
    file_key: str = ""
    storage_state: str = "active"
    is_missing: bool = False


@dataclass(frozen=True)
class CachedSessionData:
    session_dirs: list[Path]
    files: list[Path]
    records: list[UsageRecord]
    file_summaries: dict[Path, CachedFileSummary]
    project_transitions: list[ProjectTransition]
    stats: CacheStats
    file_errors: dict[str, str]
    retained_missing_files: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class CachedRowsSnapshot:
    files: list[dict[str, Any]]
    usage_records: list[dict[str, Any]]
    session_metadata: list[dict[str, Any]]


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
) -> CachedSessionData:
    resolved_cache_dir = resolve_cache_dir(session_dirs, cache_dir)
    resolved_cache_dir.mkdir(parents=True, exist_ok=True)
    inventory = collect_session_file_inventory(session_dirs)
    session_files = [entry.path for entry in inventory]
    with sqlite3.connect(resolved_cache_dir / CACHE_DB_NAME) as connection:
        connection.row_factory = sqlite3.Row
        rebuilt = _ensure_schema(connection)
        stats = _refresh_files(connection, session_dirs, inventory, rebuilt=rebuilt)
        current_keys = {entry.file_key for entry in inventory}
        missing_keys = _missing_file_keys(connection)
        records_by_file_key = _load_records_by_file_key(connection, current_keys | missing_keys)
        ordered_keys = [entry.file_key for entry in inventory] + sorted(missing_keys - current_keys)
        records = finalize_session_records([records_by_file_key.get(file_key, []) for file_key in ordered_keys])
        transitions = _refresh_or_load_transitions(
            connection,
            session_dirs=session_dirs,
            session_files=session_files,
            records=records,
            stats=stats,
            auto_transitions=auto_transitions,
        )
        if auto_transitions:
            records = apply_project_transitions(records, transitions)
        summaries = _load_file_summaries(connection, inventory, session_dirs)
        errors = _load_file_errors(connection)
        retained_missing_files = _retained_missing_files(connection)
    return CachedSessionData(
        session_dirs=session_dirs,
        files=session_files,
        records=records,
        file_summaries=summaries,
        project_transitions=transitions,
        stats=stats,
        file_errors=errors,
        retained_missing_files=retained_missing_files,
    )


def _ensure_schema(connection: sqlite3.Connection) -> bool:
    if _schema_matches(connection):
        return False
    connection.execute("begin immediate")
    try:
        cached_rows = _snapshot_cached_rows(connection)
        _drop_cache_tables(connection)
        _create_cache_tables(connection)
        connection.executemany(
            "insert into schema_meta (key, value) values (?, ?)",
            [
                ("schema_version", str(CACHE_SCHEMA_VERSION)),
                ("parser_version", str(PARSER_CACHE_VERSION)),
                ("project_transition_version", str(PROJECT_TRANSITION_CACHE_VERSION)),
            ],
        )
        _restore_cached_rows(connection, cached_rows)
        connection.execute(
            "update files set error = ? where is_missing = 0",
            (_REPARSE_REQUIRED_ERROR,),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return True


def _create_cache_tables(connection: sqlite3.Connection) -> None:
    statements = (
        "create table schema_meta (key text primary key, value text not null)",
        """
        create table files (
            file_key text primary key,
            path text not null,
            session_dir text not null,
            storage_state text not null,
            size_bytes integer not null,
            mtime_ns integer not null,
            parsed_at text not null,
            last_seen_at text not null,
            missing_since text,
            is_missing integer not null,
            session_id text,
            error text
        )
        """,
        """
        create table usage_records (
            file_key text not null,
            file_path text not null,
            record_index integer not null,
            timestamp text not null,
            session_id text not null,
            turn_id text,
            model text not null,
            effort text,
            collaboration_mode text,
            project_key text not null,
            project_label text not null,
            project_aliases_json text not null,
            cwd text,
            git_repository_url text,
            git_branch text,
            parent_thread_id text,
            input_tokens integer not null,
            cached_input_tokens integer not null,
            cache_write_input_tokens integer not null default 0,
            output_tokens integer not null,
            reasoning_output_tokens integer not null,
            total_tokens integer not null,
            primary key (file_key, record_index)
        )
        """,
        """
        create table session_metadata (
            file_key text primary key,
            file_path text not null,
            session_dir text not null,
            storage_state text not null,
            is_missing integer not null,
            session_id text not null,
            cwd text,
            project_key text,
            project_label text,
            project_aliases_json text not null,
            git_repository_url text,
            git_branch text,
            memory_mode text,
            has_base_instructions integer not null,
            session_bytes integer not null,
            estimated_sync_bytes integer not null
        )
        """,
        """
        create table project_transitions (
            source_key text not null,
            source_label text not null,
            target_key text not null,
            target_label text not null,
            effective_from text not null,
            confidence integer not null,
            evidence_json text not null,
            thread_ids_json text not null
        )
        """,
    )
    for statement in statements:
        connection.execute(statement)


def _schema_matches(connection: sqlite3.Connection) -> bool:
    try:
        rows = connection.execute("select key, value from schema_meta").fetchall()
    except sqlite3.Error:
        return False
    return {str(row["key"]): str(row["value"]) for row in rows} == {
        "schema_version": str(CACHE_SCHEMA_VERSION),
        "parser_version": str(PARSER_CACHE_VERSION),
        "project_transition_version": str(PROJECT_TRANSITION_CACHE_VERSION),
    }


def _drop_cache_tables(connection: sqlite3.Connection) -> None:
    for table in ("project_transitions", "session_metadata", "usage_records", "files", "schema_meta"):
        connection.execute(f"drop table if exists {table}")


def _refresh_files(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    inventory: list[SessionFileInventoryEntry],
    *,
    rebuilt: bool,
) -> CacheStats:
    now = datetime.now(UTC).isoformat()
    cached_rows = {
        str(row["file_key"]): row
        for row in connection.execute("select file_key, path, size_bytes, mtime_ns, is_missing, error from files")
    }
    current_keys = {entry.file_key for entry in inventory}
    missing_marked = 0
    for file_key, row in cached_rows.items():
        if file_key not in current_keys and int(row["is_missing"]) == 0:
            connection.execute(
                """
                update files
                set is_missing = 1, missing_since = ?, last_seen_at = ?,
                    error = case when error = ? then '' else error end
                where file_key = ?
                """,
                (now, now, _REPARSE_REQUIRED_ERROR, file_key),
            )
            connection.execute("update session_metadata set is_missing = 1 where file_key = ?", (file_key,))
            missing_marked += 1

    parsed = 0
    reused = 0
    errors = 0
    for entry in inventory:
        cached = cached_rows.get(entry.file_key)
        if (
            not rebuilt
            and cached
            and str(cached["path"]) == str(entry.path)
            and int(cached["size_bytes"]) == entry.size_bytes
            and int(cached["mtime_ns"]) == entry.mtime_ns
            and int(cached["is_missing"]) == 0
            and not cached["error"]
        ):
            reused += 1
            connection.execute("update files set last_seen_at = ? where file_key = ?", (now, entry.file_key))
            continue
        _record_count, error = _refresh_one_file(connection, session_dirs, entry)
        parsed += 1
        if error:
            errors += 1
    connection.commit()
    missing_count = connection.execute("select count(*) from files where is_missing = 1").fetchone()[0]
    return CacheStats(
        files_total=len(inventory),
        files_current=len(inventory),
        files_archived=sum(1 for entry in inventory if entry.storage_state == "archived"),
        files_parsed=parsed,
        files_reused=reused,
        files_removed=missing_marked,
        files_missing_retained=int(missing_count),
        file_errors=errors,
        rebuilt=rebuilt,
    )


def _refresh_one_file(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    entry: SessionFileInventoryEntry,
) -> tuple[int, str]:
    path = entry.path
    try:
        records = parse_session_file(path)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        _record_file_error(connection, session_dirs, entry, error)
        return (0, error)

    _delete_file_rows(connection, entry.file_key)
    for index, record in enumerate(records):
        _insert_record(connection, entry.file_key, path, index, record)
    _insert_file_summary(connection, session_dirs, entry, records)
    now = datetime.now(UTC).isoformat()
    connection.execute(
        """
        insert or replace into files
            (
                file_key, path, session_dir, storage_state, size_bytes, mtime_ns,
                parsed_at, last_seen_at, missing_since, is_missing, session_id, error
            )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.file_key,
            str(path),
            str(owning_session_dir(path, session_dirs)),
            entry.storage_state,
            entry.size_bytes,
            entry.mtime_ns,
            now,
            now,
            "",
            0,
            records[0].session_id if records else path.stem,
            "",
        ),
    )
    return (len(records), "")


def _snapshot_cached_rows(connection: sqlite3.Connection) -> CachedRowsSnapshot:
    existing_tables = {
        str(row["name"])
        for row in connection.execute("select name from sqlite_master where type = 'table'")
        if str(row["name"]) in _KNOWN_CACHE_TABLES
    }
    if not existing_tables:
        return CachedRowsSnapshot(files=[], usage_records=[], session_metadata=[])
    missing_history_tables = _REQUIRED_HISTORY_TABLES - existing_tables
    if missing_history_tables:
        missing = ", ".join(sorted(missing_history_tables))
        raise sqlite3.DatabaseError(f"incomplete cache history; missing required table(s): {missing}")
    file_rows = _dict_rows(connection, "select * from files")
    usage_rows = _dict_rows(connection, "select * from usage_records order by file_key, record_index")
    metadata_rows = _dict_rows(connection, "select * from session_metadata")
    return CachedRowsSnapshot(files=file_rows, usage_records=usage_rows, session_metadata=metadata_rows)


def _restore_cached_rows(connection: sqlite3.Connection, snapshot: CachedRowsSnapshot) -> None:
    _insert_dict_rows(connection, "files", snapshot.files)
    _insert_dict_rows(connection, "usage_records", snapshot.usage_records)
    _insert_dict_rows(connection, "session_metadata", snapshot.session_metadata)


def _dict_rows(
    connection: sqlite3.Connection,
    query: str,
    parameters: list[str] | None = None,
) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query, parameters or [])]


def _insert_dict_rows(connection: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = _table_columns(connection, table)
    selected_columns = [column for column in columns if column in rows[0]]
    if not selected_columns:
        raise sqlite3.DatabaseError(f"cannot restore {table}: snapshot has no compatible columns")
    placeholders = ",".join("?" for _ in selected_columns)
    column_sql = ",".join(selected_columns)
    sql = f"insert into {table} ({column_sql}) values ({placeholders})"
    for row in rows:
        connection.execute(sql, [row.get(column) for column in selected_columns])


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row["name"]) for row in connection.execute(f"pragma table_info({table})")]


def _record_file_error(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    entry: SessionFileInventoryEntry,
    error: str,
) -> None:
    now = datetime.now(UTC).isoformat()
    existing = connection.execute("select 1 from files where file_key = ?", (entry.file_key,)).fetchone()
    if existing is not None:
        connection.execute(
            """
            update files
            set last_seen_at = ?, missing_since = null, is_missing = 0, error = ?
            where file_key = ?
            """,
            (now, error, entry.file_key),
        )
        connection.execute("update session_metadata set is_missing = 0 where file_key = ?", (entry.file_key,))
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


def _delete_file_rows(connection: sqlite3.Connection, file_key: str) -> None:
    connection.execute("delete from usage_records where file_key = ?", (file_key,))
    connection.execute("delete from session_metadata where file_key = ?", (file_key,))


def _insert_record(connection: sqlite3.Connection, file_key: str, file_path: Path, index: int, record: UsageRecord) -> None:
    usage = record.usage
    connection.execute(
        """
        insert into usage_records (
            file_key, file_path, record_index, timestamp, session_id, turn_id, model, effort,
            collaboration_mode, project_key, project_label, project_aliases_json,
            cwd, git_repository_url, git_branch, parent_thread_id,
            input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens,
            reasoning_output_tokens, total_tokens
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_key,
            str(file_path),
            index,
            record.timestamp.isoformat(),
            record.session_id,
            record.turn_id,
            record.model,
            record.effort,
            record.collaboration_mode,
            record.project_key,
            record.project_label,
            json.dumps(list(record.project_aliases)),
            record.cwd,
            record.git_repository_url,
            record.git_branch,
            record.parent_thread_id,
            usage.input_tokens,
            usage.cached_input_tokens,
            usage.cache_write_input_tokens,
            usage.output_tokens,
            usage.reasoning_output_tokens,
            usage.total_tokens,
        ),
    )


def _insert_file_summary(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    entry: SessionFileInventoryEntry,
    records: list[UsageRecord],
) -> None:
    path = entry.path
    metadata = read_session_metadata(path)
    selected = records[-1] if records else None
    identity = None if selected is not None or metadata is None else resolve_project_identity(metadata)
    session_id = selected.session_id if selected else (metadata.session_id if metadata else path.stem)
    project_key = selected.project_key if selected else (identity.key if identity else "")
    project_label = selected.project_label if selected else (identity.label if identity else "")
    project_aliases = selected.project_aliases if selected else (identity.aliases if identity else ())
    connection.execute(
        """
        insert or replace into session_metadata (
            file_key, file_path, session_dir, storage_state, is_missing, session_id, cwd, project_key, project_label,
            project_aliases_json, git_repository_url, git_branch, memory_mode,
            has_base_instructions, session_bytes, estimated_sync_bytes
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.file_key,
            str(path),
            str(owning_session_dir(path, session_dirs)),
            entry.storage_state,
            0,
            session_id,
            selected.cwd if selected else (metadata.cwd if metadata else ""),
            project_key,
            project_label,
            json.dumps(list(project_aliases)),
            selected.git_repository_url if selected else (metadata.git_repository_url if metadata else ""),
            selected.git_branch if selected else (metadata.git_branch if metadata else ""),
            metadata.memory_mode if metadata else "",
            1 if metadata and metadata.has_base_instructions else 0,
            entry.size_bytes,
            entry.size_bytes + _ESTIMATED_SYNC_METADATA_BYTES,
        ),
    )


def _load_records_by_file_key(connection: sqlite3.Connection, selected_keys: set[str]) -> dict[str, list[UsageRecord]]:
    if not selected_keys:
        return {}
    records_by_file: dict[str, list[UsageRecord]] = {}
    for row in connection.execute("select * from usage_records order by file_key, record_index"):
        if row["file_key"] not in selected_keys:
            continue
        records_by_file.setdefault(str(row["file_key"]), []).append(_row_to_record(row))
    return records_by_file


def _row_to_record(row: sqlite3.Row) -> UsageRecord:
    return UsageRecord(
        timestamp=parse_timestamp(row["timestamp"]) or datetime.fromtimestamp(0, tz=UTC),
        usage=TokenUsage(
            input_tokens=int(row["input_tokens"]),
            cached_input_tokens=int(row["cached_input_tokens"]),
            cache_write_input_tokens=int(row["cache_write_input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            reasoning_output_tokens=int(row["reasoning_output_tokens"]),
            total_tokens=int(row["total_tokens"]),
        ),
        session_id=row["session_id"],
        file_path=Path(row["file_path"]),
        model=row["model"],
        turn_id=row["turn_id"] or "",
        effort=row["effort"] or "",
        collaboration_mode=row["collaboration_mode"] or "",
        project_key=row["project_key"],
        project_label=row["project_label"],
        project_aliases=tuple(json.loads(row["project_aliases_json"] or "[]")),
        cwd=row["cwd"] or "",
        git_repository_url=row["git_repository_url"] or "",
        git_branch=row["git_branch"] or "",
        parent_thread_id=row["parent_thread_id"] or "",
    )


def _refresh_or_load_transitions(
    connection: sqlite3.Connection,
    *,
    session_dirs: list[Path],
    session_files: list[Path],
    records: list[UsageRecord],
    stats: CacheStats,
    auto_transitions: bool,
) -> list[ProjectTransition]:
    if not auto_transitions:
        return []
    if stats.rebuilt or stats.files_parsed or stats.files_removed:
        observations = collect_repo_path_observations(session_dirs, session_files)
        transitions = infer_project_transitions(records, observations)
        connection.execute("delete from project_transitions")
        for transition in transitions:
            connection.execute(
                """
                insert into project_transitions (
                    source_key, source_label, target_key, target_label,
                    effective_from, confidence, evidence_json, thread_ids_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transition.source_key,
                    transition.source_label,
                    transition.target_key,
                    transition.target_label,
                    transition.effective_from.isoformat(),
                    transition.confidence,
                    json.dumps(list(transition.evidence)),
                    json.dumps(list(transition.thread_ids)),
                ),
            )
        connection.commit()
        return transitions
    return _load_transitions(connection)


def _load_transitions(connection: sqlite3.Connection) -> list[ProjectTransition]:
    transitions: list[ProjectTransition] = []
    for row in connection.execute("select * from project_transitions order by effective_from, source_key, target_key"):
        timestamp = parse_timestamp(row["effective_from"])
        if timestamp is None:
            continue
        transitions.append(
            ProjectTransition(
                source_key=row["source_key"],
                source_label=row["source_label"],
                target_key=row["target_key"],
                target_label=row["target_label"],
                effective_from=timestamp,
                confidence=int(row["confidence"]),
                evidence=tuple(json.loads(row["evidence_json"] or "[]")),
                thread_ids=tuple(json.loads(row["thread_ids_json"] or "[]")),
            )
        )
    return transitions


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
            session_dir=Path(row["session_dir"]) if row["session_dir"] else owning_session_dir(path, session_dirs),
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
        for row in connection.execute("select path, error from files where error is not null and error != ''")
    }


def _missing_file_keys(connection: sqlite3.Connection) -> set[str]:
    return {str(row["file_key"]) for row in connection.execute("select file_key from files where is_missing = 1")}


def _retained_missing_files(connection: sqlite3.Connection) -> list[Path]:
    return [
        Path(row["path"])
        for row in connection.execute("select path from files where is_missing = 1 order by path")
    ]
