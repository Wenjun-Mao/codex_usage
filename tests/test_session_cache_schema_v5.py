import sqlite3
from pathlib import Path

from parallel_cache_test_support import normalized_sqlite_master

import codex_usage.session_cache_schema as cache_schema
from codex_usage.models import SessionMetadata
from codex_usage.session_cache import CACHE_DB_NAME
from codex_usage.session_cache_checkpoints import (
    load_parser_checkpoint,
    upsert_parser_checkpoint,
)
from codex_usage.session_parser_models import (
    SessionParseCheckpoint,
    SessionParserState,
)


def create_schema_four_database(db_path: Path, *, sentinel_total_tokens: int) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            create table schema_meta (key text primary key, value text not null);
            create table files (file_key text primary key);
            create table usage_records (
                file_key text not null,
                record_index integer not null,
                total_tokens integer not null,
                primary key (file_key, record_index)
            );
            create table session_metadata (file_key text primary key);
            create table project_transitions (source_key text not null);
            """
        )
        connection.executemany(
            "insert into schema_meta (key, value) values (?, ?)",
            (
                ("schema_version", "4"),
                ("parser_version", "3"),
                ("project_transition_version", "2"),
            ),
        )
        connection.execute(
            "insert into usage_records (file_key, record_index, total_tokens) values (?, ?, ?)",
            ("sentinel", 0, sentinel_total_tokens),
        )


def test_schema_four_is_discarded_instead_of_migrated(tmp_path: Path) -> None:
    db_path = tmp_path / CACHE_DB_NAME
    create_schema_four_database(db_path, sentinel_total_tokens=999)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        state = cache_schema._ensure_schema(connection)

    assert state.reset is True
    assert state.reset_reason == "schema 4"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("select count(*) from usage_records").fetchone()[0] == 0
        assert connection.execute(
            "select value from schema_meta where key = 'schema_version'"
        ).fetchone()[0] == "8"
        columns = {
            row[1]: row for row in connection.execute("pragma table_info(usage_records)")
        }
    assert columns["usage_role"][3] == 1


def test_schema_six_is_discarded_and_rebuilt_as_eight(tmp_path: Path) -> None:
    db_path = tmp_path / CACHE_DB_NAME
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        cache_schema._ensure_schema(connection)
        connection.execute(
            "update schema_meta set value = '6' where key = 'schema_version'"
        )
        connection.commit()
        state = cache_schema._ensure_schema(connection)

    assert state.reset is True
    assert state.reset_reason == "schema 6"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "select value from schema_meta where key = 'schema_version'"
        ).fetchone() == ("8",)


def test_schema_eight_contains_incremental_and_storage_contract(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / CACHE_DB_NAME
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        cache_schema._ensure_schema(connection)
        objects = normalized_sqlite_master(connection)

    names = {(kind, name) for kind, name, _table, _sql in objects}
    assert ("table", "parser_checkpoints") in names
    assert ("table", "storage_files") in names
    assert ("table", "storage_content_diagnostics") in names
    assert ("table", "transition_candidates") in names
    assert ("table", "dirty_transition_tasks") in names
    assert ("index", "usage_records_timestamp_us_idx") in names
    assert ("index", "usage_records_session_timestamp_idx") in names
    assert ("index", "transition_candidates_thread_idx") in names
    assert ("index", "storage_files_task_idx") in names
    assert ("index", "storage_content_diagnostics_task_idx") in names


def test_checkpoint_identity_round_trips_unsigned_windows_values(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / CACHE_DB_NAME
    session_path = tmp_path / "thread.jsonl"
    metadata = SessionMetadata(session_id="thread", file_path=session_path)
    state = SessionParserState(
        metadata=metadata,
        root_metadata=metadata,
        previous_usage=None,
        root_session_id="thread",
        root_session_is_fork=False,
        counted_root_fork_usage=False,
        subagent_own_activity_started=False,
        current_model="",
        current_turn_id="",
        current_effort="",
        current_mode="",
    )
    checkpoint = SessionParseCheckpoint(
        byte_offset=10,
        next_record_index=1,
        next_candidate_index=0,
        source_device=(2**63) + 123,
        source_inode=(2**64) - 1,
        head_sha256="head",
        boundary_sha256="boundary",
        session_id="thread",
        state=state,
    )

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        cache_schema._ensure_schema(connection)
        upsert_parser_checkpoint(connection, "thread", checkpoint)
        stored = connection.execute(
            "select source_device, source_inode, typeof(source_device), "
            "typeof(source_inode) from parser_checkpoints"
        ).fetchone()
        loaded = load_parser_checkpoint(connection, "thread", session_path)

    assert tuple(stored) == (
        str(checkpoint.source_device),
        str(checkpoint.source_inode),
        "text",
        "text",
    )
    assert loaded == checkpoint


def test_matching_version_without_checkpoint_table_is_rebuilt(tmp_path: Path) -> None:
    db_path = tmp_path / CACHE_DB_NAME
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        cache_schema._ensure_schema(connection)
        connection.execute("drop table parser_checkpoints")
        connection.commit()
        state = cache_schema._ensure_schema(connection)

    assert state.reset is True
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "select 1 from parser_checkpoints limit 1"
        ).fetchone() is None


def test_matching_version_without_storage_index_is_rebuilt(tmp_path: Path) -> None:
    db_path = tmp_path / CACHE_DB_NAME
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        cache_schema._ensure_schema(connection)
        connection.execute("drop index storage_files_task_idx")
        connection.commit()
        state = cache_schema._ensure_schema(connection)

    assert state.reset is True
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "select 1 from sqlite_master where type = 'index' and name = 'storage_files_task_idx'"
        ).fetchone() is not None


def test_matching_schema_returns_empty_state(tmp_path: Path) -> None:
    db_path = tmp_path / CACHE_DB_NAME
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        cache_schema._ensure_schema(connection)
        state = cache_schema._ensure_schema(connection)

    assert state.created is False
    assert state.reset is False
    assert state.reset_reason == ""


def test_invalid_usage_role_resets_matching_schema(tmp_path: Path) -> None:
    db_path = tmp_path / CACHE_DB_NAME
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        cache_schema._ensure_schema(connection)
        connection.execute("pragma ignore_check_constraints = true")
        connection.execute(
            """
            insert into usage_records (
                file_key, file_path, record_index, timestamp, timestamp_us, session_id,
                model, project_key, project_label, project_aliases_json, usage_role,
                input_tokens, cached_input_tokens, cache_write_input_tokens,
                output_tokens, reasoning_output_tokens, total_tokens
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "file", "file.jsonl", 0, "2026-08-04T00:00:00+00:00", 0, "thread",
                "gpt-5", "project", "Project", "[]", "worker", 1, 0, 0, 0, 0, 1,
            ),
        )
        connection.commit()
        state = cache_schema._ensure_schema(connection)

    assert state.reset is True
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("select count(*) from usage_records").fetchone()[0] == 0
