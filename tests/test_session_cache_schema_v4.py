import sqlite3
from pathlib import Path

from parallel_cache_test_support import normalized_sqlite_master

import codex_usage.session_cache_schema as cache_schema
from codex_usage.session_cache import CACHE_DB_NAME


def create_schema_three_database(db_path: Path, *, sentinel_total_tokens: int) -> None:
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
                ("schema_version", "3"),
                ("parser_version", "2"),
                ("project_transition_version", "1"),
            ),
        )
        connection.execute(
            "insert into usage_records (file_key, record_index, total_tokens) values (?, ?, ?)",
            ("sentinel", 0, sentinel_total_tokens),
        )


def test_schema_three_is_discarded_instead_of_migrated(tmp_path: Path) -> None:
    db_path = tmp_path / CACHE_DB_NAME
    create_schema_three_database(db_path, sentinel_total_tokens=999)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        state = cache_schema._ensure_schema(connection)

    assert getattr(state, "reset", False) is True
    assert getattr(state, "reset_reason", "") == "schema 3"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("select count(*) from usage_records").fetchone()[0] == 0
        assert connection.execute(
            "select value from schema_meta where key = 'schema_version'"
        ).fetchone()[0] == "4"


def test_schema_four_contains_incremental_query_contract(tmp_path: Path) -> None:
    db_path = tmp_path / CACHE_DB_NAME
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        cache_schema._ensure_schema(connection)
        objects = normalized_sqlite_master(connection)

    names = {(kind, name) for kind, name, _table, _sql in objects}
    assert ("table", "transition_candidates") in names
    assert ("table", "dirty_transition_tasks") in names
    assert ("index", "usage_records_timestamp_us_idx") in names
    assert ("index", "usage_records_session_timestamp_idx") in names
    assert ("index", "transition_candidates_thread_idx") in names


def test_matching_schema_returns_empty_state(tmp_path: Path) -> None:
    db_path = tmp_path / CACHE_DB_NAME
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        cache_schema._ensure_schema(connection)
        state = cache_schema._ensure_schema(connection)

    assert getattr(state, "created", True) is False
    assert getattr(state, "reset", True) is False
    assert getattr(state, "reset_reason", "missing") == ""
