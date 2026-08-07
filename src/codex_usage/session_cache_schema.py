from __future__ import annotations

import sqlite3
from dataclasses import dataclass

CACHE_SCHEMA_VERSION = 6
PARSER_CACHE_VERSION = 5
PROJECT_TRANSITION_CACHE_VERSION = 2
_REPARSE_REQUIRED_ERROR = "cache schema rebuild requires reparse"
_PROJECT_TRANSITIONS_DIRTY_KEY = "project_transitions_dirty"
_DIRTY_VALUE = "1"
_CLEAN_VALUE = "0"
_KNOWN_CACHE_TABLES = frozenset(
    {
        "schema_meta",
        "files",
        "usage_records",
        "session_metadata",
        "parser_checkpoints",
        "transition_candidates",
        "dirty_transition_tasks",
        "project_transitions",
    }
)
_KNOWN_CACHE_INDEXES = frozenset(
    {
        "usage_records_timestamp_us_idx",
        "usage_records_session_timestamp_idx",
        "transition_candidates_thread_idx",
    }
)


@dataclass(frozen=True, slots=True)
class CacheSchemaState:
    created: bool = False
    reset: bool = False
    reset_reason: str = ""


def _ensure_schema(connection: sqlite3.Connection) -> CacheSchemaState:
    if _schema_matches(connection):
        return CacheSchemaState()

    connection.execute("begin immediate")
    try:
        prior_tables = _existing_cache_tables(connection)
        prior_version = _prior_schema_version(connection)
        _drop_cache_schema(connection)
        _create_cache_schema(connection)
        connection.executemany(
            "insert into schema_meta (key, value) values (?, ?)",
            [
                ("schema_version", str(CACHE_SCHEMA_VERSION)),
                ("parser_version", str(PARSER_CACHE_VERSION)),
                (
                    "project_transition_version",
                    str(PROJECT_TRANSITION_CACHE_VERSION),
                ),
                (_PROJECT_TRANSITIONS_DIRTY_KEY, _DIRTY_VALUE),
            ],
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise

    return CacheSchemaState(
        created=not prior_tables,
        reset=bool(prior_tables),
        reset_reason=(
            f"schema {prior_version}" if prior_version else "unrecognized schema"
        ),
    )


def _create_cache_schema(connection: sqlite3.Connection) -> None:
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
            timestamp_us integer not null,
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
            usage_role text not null check (usage_role in ('root', 'subagent')),
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
        create table parser_checkpoints (
            file_key text primary key,
            byte_offset integer not null,
            next_record_index integer not null,
            next_candidate_index integer not null,
            source_device text not null,
            source_inode text not null,
            head_sha256 text not null,
            boundary_sha256 text not null,
            session_id text not null,
            state_json text not null
        )
        """,
        """
        create table transition_candidates (
            file_key text not null,
            candidate_index integer not null,
            timestamp text not null,
            timestamp_us integer not null,
            thread_id text not null,
            raw_path text not null,
            source text not null,
            primary key (file_key, candidate_index)
        )
        """,
        """
        create table dirty_transition_tasks (
            thread_id text primary key
        )
        """,
        """
        create table project_transitions (
            owner_thread_id text not null,
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
        "create index usage_records_timestamp_us_idx on usage_records (timestamp_us)",
        "create index usage_records_session_timestamp_idx on usage_records (session_id, timestamp_us)",
        "create index transition_candidates_thread_idx on transition_candidates (thread_id)",
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
    if not all(metadata.get(key) == value for key, value in expected_versions.items()):
        return False
    try:
        invalid_role = connection.execute(
            """
            select 1 from usage_records
            where usage_role is null or usage_role not in ('root', 'subagent')
            limit 1
            """
        ).fetchone()
        connection.execute("select 1 from parser_checkpoints limit 1").fetchone()
    except sqlite3.Error:
        return False
    return invalid_role is None


def _existing_cache_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(
            "select name from sqlite_master where type = 'table'"
        )
        if str(row["name"]) in _KNOWN_CACHE_TABLES
    }


def _prior_schema_version(connection: sqlite3.Connection) -> str:
    if "schema_meta" not in _existing_cache_tables(connection):
        return ""
    try:
        row = connection.execute(
            "select value from schema_meta where key = 'schema_version'"
        ).fetchone()
    except sqlite3.Error:
        return ""
    return "" if row is None else str(row["value"])


def _drop_cache_schema(connection: sqlite3.Connection) -> None:
    for index in sorted(_KNOWN_CACHE_INDEXES):
        connection.execute(f"drop index if exists {index}")
    for table in (
        "project_transitions",
        "dirty_transition_tasks",
        "transition_candidates",
        "parser_checkpoints",
        "session_metadata",
        "usage_records",
        "files",
        "schema_meta",
    ):
        connection.execute(f"drop table if exists {table}")
