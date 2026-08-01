from __future__ import annotations

import sqlite3
from typing import Any

from codex_usage.session_cache_models import CachedRowsSnapshot

CACHE_SCHEMA_VERSION = 3
PARSER_CACHE_VERSION = 2
PROJECT_TRANSITION_CACHE_VERSION = 1
_REPARSE_REQUIRED_ERROR = "cache schema rebuild requires reparse"
_PROJECT_TRANSITIONS_DIRTY_KEY = "project_transitions_dirty"
_DIRTY_VALUE = "1"
_CLEAN_VALUE = "0"
_KNOWN_CACHE_TABLES = frozenset(
    {"schema_meta", "files", "usage_records", "session_metadata", "project_transitions"}
)
_REQUIRED_HISTORY_TABLES = frozenset({"files", "usage_records", "session_metadata"})


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
                (_PROJECT_TRANSITIONS_DIRTY_KEY, _DIRTY_VALUE),
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
    metadata = {str(row["key"]): str(row["value"]) for row in rows}
    expected_versions = {
        "schema_version": str(CACHE_SCHEMA_VERSION),
        "parser_version": str(PARSER_CACHE_VERSION),
        "project_transition_version": str(PROJECT_TRANSITION_CACHE_VERSION),
    }
    return all(metadata.get(key) == value for key, value in expected_versions.items())


def _drop_cache_tables(connection: sqlite3.Connection) -> None:
    for table in ("project_transitions", "session_metadata", "usage_records", "files", "schema_meta"):
        connection.execute(f"drop table if exists {table}")


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
