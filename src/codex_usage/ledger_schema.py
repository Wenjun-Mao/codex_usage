from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from codex_usage.ledger_writer_contract import (
    LEDGER_SCHEMA_VERSION, authorize_writer_connection, install_writer_contract,
    validate_writer_contract, ledger_schema_version, assert_legacy_writer_metadata,
    admit_ledger_privacy_paths,
)

import codex_usage.session_cache_schema as parser_schema
from codex_usage.agent_private_files import (
    ensure_private_directory,
    ensure_private_file,
    ensure_private_sqlite_files,
)


LEDGER_REVISION_KEY = "ledger_revision"


def configure_ledger_connection(connection: sqlite3.Connection, *, journal_mode=True) -> None:
    authorize_writer_connection(connection)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma foreign_keys = on")
    connection.execute("pragma busy_timeout = 5000")
    connection.execute("pragma synchronous = normal")
    if journal_mode:
        connection.execute("pragma journal_mode = wal")


@contextmanager
def open_ledger(
    path: Path,
    *,
    read_only: bool = False,
    maintenance_agent_lock=None,
) -> Iterator[sqlite3.Connection]:
    if read_only:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        path = admit_ledger_privacy_paths(path)
        ensure_private_directory(path.parent)
        connection = sqlite3.connect(path)
    primary = None
    try:
        if read_only:
            connection.row_factory = sqlite3.Row
            connection.execute("pragma foreign_keys = on")
            connection.execute("pragma busy_timeout = 5000")
        else:
            ensure_private_file(path)
            ensure_ledger_schema(connection, path=path, maintenance_agent_lock=maintenance_agent_lock)
            from codex_usage.allowance_window_tracking import repair_existing_tracking
            repair_existing_tracking(connection)
        yield connection
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_failure = None
        cleanups = [connection.close]
        if not read_only:
            cleanups.append(lambda: ensure_private_sqlite_files(path))
        for cleanup in cleanups:
            try:
                cleanup()
            except Exception as error:
                if primary is not None:
                    primary.add_note(f"Ledger cleanup failed: {type(error).__name__}: {error}")
                elif cleanup_failure is None:
                    cleanup_failure = error
                else:
                    cleanup_failure.add_note(f"Additional ledger cleanup failure: {type(error).__name__}: {error}")
        if primary is None and cleanup_failure is not None:
            raise cleanup_failure


def ensure_ledger_schema(
    connection: sqlite3.Connection,
    *,
    path: Path | None = None,
    maintenance_agent_lock=None,
) -> None:
    connection.row_factory = sqlite3.Row
    authorize_writer_connection(connection)
    version = _ledger_version(connection)
    if version > LEDGER_SCHEMA_VERSION:
        raise ValueError(
            f"ledger schema {version} is newer than supported schema {LEDGER_SCHEMA_VERSION}"
        )
    if version == LEDGER_SCHEMA_VERSION:
        validate_writer_contract(connection)
        configure_ledger_connection(connection)
        parser_schema._ensure_schema(connection)
        return
    if version and path is not None:
        assert_legacy_writer_metadata(connection)
        from codex_usage.ledger_maintenance import acquire_ledger_maintenance
        with acquire_ledger_maintenance(path, owned_agent_lock=maintenance_agent_lock):
            if _ledger_version(connection) != version:
                raise RuntimeError("ledger schema changed before maintenance admission")
            configure_ledger_connection(connection, journal_mode=False)
            backup = _backup_before_migration(connection, path, version)
            _migrate_schema(connection, version, backup=backup)
            configure_ledger_connection(connection)
        return
    if version:
        raise ValueError("existing ledger migration requires its owned database path")
    configure_ledger_connection(connection)
    _migrate_schema(connection, version)


def _migrate_schema(connection, version, *, backup=None):
    if not version:
        parser_schema._ensure_schema(connection)
    connection.execute("begin immediate")
    try:
        if version:
            from codex_usage.ledger_migration_backup import assert_backup_current
            assert_backup_current(connection, backup)
            parser_schema._ensure_schema(connection, ledger_migration=True)
        if version == 0:
            _create_schema_v1(connection)
            _migrate_v1_to_v2(connection)
        elif version == 1:
            _migrate_v1_to_v2(connection)
        from codex_usage.allowance_schema import create_allowance_schema, create_credit_schema
        if version < 3:
            create_allowance_schema(connection)
        _create_allowance_cost_schema(connection)
        create_credit_schema(connection)
        from codex_usage.speed_schema import create_speed_ledger
        create_speed_ledger(connection)
        connection.execute(
            "insert or replace into ledger_meta (key, value) values (?, ?)",
            ("schema_version", str(LEDGER_SCHEMA_VERSION)),
        )
        connection.execute(
            "insert or ignore into ledger_meta (key, value) values (?, '0')",
            (LEDGER_REVISION_KEY,),
        )
        if version:
            from codex_usage.history_upgrade_receipts import seed_legacy_checkpoint_discovery
            if seed_legacy_checkpoint_discovery(connection):
                increment_ledger_revision(connection)
        install_writer_contract(connection)
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


def _create_allowance_cost_schema(connection: sqlite3.Connection) -> None:
    """Derived, disposable pricing index; source events remain authoritative."""
    connection.execute("""create table if not exists allowance_event_costs (
        event_id integer primary key references ledger_usage_events(event_id) on delete cascade,
        pricing_revision text not null,
        total_usd real not null,
        unpriced_tokens integer not null
    )""")
    connection.execute("""create table if not exists allowance_report_cache (
        ledger_revision integer not null,
        pricing_revision text not null,
        coverage_complete integer not null,
        report_json text not null,
        primary key (ledger_revision, pricing_revision, coverage_complete)
    )""")


def _ledger_version(connection: sqlite3.Connection) -> int:
    return ledger_schema_version(connection)


def _backup_before_migration(
    connection: sqlite3.Connection,
    path: Path,
    version: int,
) -> None:
    from codex_usage.ledger_migration_backup import backup_before_writer_upgrade
    return backup_before_writer_upgrade(connection, path, version)


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


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    """Add image accounting without rewriting trusted language event rows."""
    statements = (
        """
        create table ledger_image_events (
            image_event_id integer primary key,
            generation_id integer not null references ledger_generations(generation_id) on delete cascade,
            tool_call_id text not null,
            timestamp text not null,
            timestamp_us integer not null,
            task_id text not null references ledger_tasks(task_id),
            root_task_id text not null,
            usage_role text not null check (usage_role in ('root', 'subagent')),
            turn_id text not null,
            project_id integer not null references ledger_projects(project_id),
            kind text not null check (kind in ('generate', 'edit_reference', 'unknown')),
            outcome text not null check (outcome in ('attempted', 'succeeded', 'failed')),
            output_count integer not null check (output_count >= 0),
            output_width integer,
            output_height integer,
            output_format text not null,
            quality text not null,
            model_family text not null,
            model_variant text not null,
            model_raw_identity text not null,
            evidence_json text not null,
            usage_json text not null,
            unique (generation_id, tool_call_id)
        )
        """,
        "create index ledger_image_timestamp_idx on ledger_image_events(timestamp_us)",
        "create index ledger_image_task_idx on ledger_image_events(task_id, timestamp_us)",
    )
    for statement in statements:
        connection.execute(statement)
