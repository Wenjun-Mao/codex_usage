from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

import codex_usage.session_cache_schema as parser_schema
from codex_usage.agent_private_files import (
    ensure_private_directory,
    ensure_private_file,
    ensure_private_sqlite_files,
)


LEDGER_SCHEMA_VERSION = 1
LEDGER_REVISION_KEY = "ledger_revision"


def configure_ledger_connection(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.execute("pragma foreign_keys = on")
    connection.execute("pragma busy_timeout = 5000")
    connection.execute("pragma synchronous = normal")
    connection.execute("pragma journal_mode = wal")


@contextmanager
def open_ledger(
    path: Path,
    *,
    read_only: bool = False,
) -> Iterator[sqlite3.Connection]:
    if read_only:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("pragma foreign_keys = on")
        connection.execute("pragma busy_timeout = 5000")
    else:
        ensure_private_directory(path.parent)
        connection = sqlite3.connect(path)
        ensure_private_file(path)
        configure_ledger_connection(connection)
        ensure_ledger_schema(connection, path=path)
    try:
        yield connection
    finally:
        connection.close()
        if not read_only:
            ensure_private_sqlite_files(path)


def ensure_ledger_schema(
    connection: sqlite3.Connection,
    *,
    path: Path | None = None,
) -> None:
    configure_ledger_connection(connection)
    parser_schema._ensure_schema(connection)
    version = _ledger_version(connection)
    if version > LEDGER_SCHEMA_VERSION:
        raise ValueError(
            f"ledger schema {version} is newer than supported schema {LEDGER_SCHEMA_VERSION}"
        )
    if version == LEDGER_SCHEMA_VERSION:
        return
    if version and path is not None:
        _backup_before_migration(connection, path, version)
    connection.execute("begin immediate")
    try:
        if version == 0:
            _create_schema_v1(connection)
        connection.execute(
            "insert or replace into ledger_meta (key, value) values (?, ?)",
            ("schema_version", str(LEDGER_SCHEMA_VERSION)),
        )
        connection.execute(
            "insert or ignore into ledger_meta (key, value) values (?, '0')",
            (LEDGER_REVISION_KEY,),
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def ledger_revision(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "select value from ledger_meta where key = ?", (LEDGER_REVISION_KEY,)
    ).fetchone()
    return int(row["value"]) if row is not None else 0


def increment_ledger_revision(connection: sqlite3.Connection) -> int:
    revision = ledger_revision(connection) + 1
    connection.execute(
        "insert or replace into ledger_meta (key, value) values (?, ?)",
        (LEDGER_REVISION_KEY, str(revision)),
    )
    return revision


def _ledger_version(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute(
            "select value from ledger_meta where key = 'schema_version'"
        ).fetchone()
    except sqlite3.Error:
        return 0
    return int(row["value"]) if row is not None else 0


def _backup_before_migration(
    connection: sqlite3.Connection,
    path: Path,
    version: int,
) -> None:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = path.with_name(
        f"{path.name}.schema-{version}-backup-{stamp}"
    )
    with sqlite3.connect(backup_path) as backup:
        connection.backup(backup)
    ensure_private_file(backup_path)


def _create_schema_v1(connection: sqlite3.Connection) -> None:
    statements = (
        "create table ledger_meta (key text primary key, value text not null)",
        """
        create table ledger_sources (
            source_id integer primary key,
            source_key text not null unique,
            path text not null,
            session_dir text not null,
            storage_state text not null,
            source_device text not null,
            source_inode text not null,
            size_bytes integer not null check (size_bytes >= 0),
            mtime_ns integer not null,
            last_seen_at text not null,
            missing_since text,
            is_missing integer not null check (is_missing in (0, 1)),
            is_stale integer not null check (is_stale in (0, 1)),
            stale_reason text not null,
            error text not null
        )
        """,
        """
        create table ledger_generations (
            generation_id integer primary key,
            source_id integer not null references ledger_sources(source_id),
            generation_key text not null,
            generation_number integer not null,
            status text not null check (status in ('trusted', 'staging', 'superseded')),
            captured_size integer not null check (captured_size >= 0),
            captured_mtime_ns integer not null,
            head_sha256 text not null,
            boundary_sha256 text not null,
            record_count integer not null check (record_count >= 0),
            captured_at text not null,
            completed_at text,
            unique (source_id, generation_number),
            unique (source_id, generation_key)
        )
        """,
        """
        create unique index ledger_trusted_generation_idx
        on ledger_generations(source_id) where status = 'trusted'
        """,
        """
        create table ledger_projects (
            project_id integer primary key,
            project_key text not null unique,
            label text not null,
            aliases_json text not null,
            repository_url text not null
        )
        """,
        """
        create table ledger_models (
            model_id integer primary key,
            model_key text not null unique
        )
        """,
        """
        create table ledger_tasks (
            task_id text primary key,
            parent_task_id text not null,
            usage_role text not null check (usage_role in ('root', 'subagent')),
            title text not null,
            project_id integer references ledger_projects(project_id),
            cwd text not null,
            first_seen_at text not null,
            last_seen_at text not null
        )
        """,
        """
        create table ledger_contexts (
            context_id integer primary key,
            context_key text not null unique,
            project_id integer not null references ledger_projects(project_id),
            cwd text not null,
            repository_url text not null,
            git_branch text not null,
            effort text not null,
            collaboration_mode text not null,
            project_aliases_json text not null
        )
        """,
        """
        create table ledger_usage_events (
            event_id integer primary key,
            generation_id integer not null references ledger_generations(generation_id) on delete cascade,
            source_record_index integer not null,
            timestamp text not null,
            timestamp_us integer not null,
            task_id text not null references ledger_tasks(task_id),
            turn_id text not null,
            model_id integer not null references ledger_models(model_id),
            context_id integer not null references ledger_contexts(context_id),
            parent_task_id text not null,
            usage_role text not null check (usage_role in ('root', 'subagent')),
            input_tokens integer not null,
            cached_input_tokens integer not null,
            cache_write_input_tokens integer not null,
            output_tokens integer not null,
            reasoning_output_tokens integer not null,
            total_tokens integer not null,
            unique (generation_id, source_record_index)
        )
        """,
        "create index ledger_usage_timestamp_idx on ledger_usage_events(timestamp_us)",
        "create index ledger_usage_task_idx on ledger_usage_events(task_id, timestamp_us)",
        "create index ledger_usage_context_idx on ledger_usage_events(context_id)",
        """
        create table ledger_transitions (
            transition_id integer primary key,
            owner_task_id text not null,
            source_key text not null,
            source_label text not null,
            target_key text not null,
            target_label text not null,
            effective_from text not null,
            confidence integer not null,
            evidence_json text not null,
            task_ids_json text not null
        )
        """,
        """
        create table capture_runs (
            run_id integer primary key,
            request_kind text not null,
            started_at text not null,
            completed_at text,
            outcome text not null,
            ledger_revision integer not null,
            files_total integer not null default 0,
            files_parsed integer not null default 0,
            pending_files integer not null default 0,
            pending_bytes integer not null default 0,
            source_bytes_read integer not null default 0,
            stats_json text not null,
            error text not null
        )
        """,
        """
        create table migration_audit (
            migration_id integer primary key,
            source_path text not null,
            source_digest text not null,
            started_at text not null,
            completed_at text,
            outcome text not null,
            detail_json text not null,
            unique (source_path, source_digest)
        )
        """,
        """
        create table rendered_reports (
            cache_key text primary key,
            ledger_revision integer not null,
            pricing_revision text not null,
            created_at text not null,
            html text not null
        )
        """,
    )
    for statement in statements:
        connection.execute(statement)
