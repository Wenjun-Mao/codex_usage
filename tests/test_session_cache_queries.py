from __future__ import annotations

import sqlite3

from codex_usage.session_cache_queries import (
    load_raw_candidates_for_task_ids,
    load_records_for_task_ids,
)


def test_current_generation_usage_records_are_ordered_by_file_and_index() -> None:
    connection = _query_connection()
    _insert_usage_records(connection)

    records = load_records_for_task_ids(connection, _task_ids())

    assert [(record.file_path.name, record.turn_id) for record in records] == [
        ("file-a.jsonl", "turn-a-1"),
        ("file-a.jsonl", "turn-a-3"),
        ("file-z.jsonl", "turn-z-0"),
        ("file-z.jsonl", "turn-z-1"),
    ]


def test_current_generation_candidates_are_ordered_by_file_and_index() -> None:
    connection = _query_connection()
    _insert_transition_candidates(connection)

    candidates = load_raw_candidates_for_task_ids(
        connection, _task_ids()
    )

    assert [candidate.raw_path for candidate in candidates] == [
        "/repo/a/one",
        "/repo/a/three",
        "/repo/z/zero",
        "/repo/z/one",
    ]


def _query_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "create table files (file_key text primary key, session_id text not null)"
    )
    connection.execute(
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
            cache_write_input_tokens integer not null,
            output_tokens integer not null,
            reasoning_output_tokens integer not null,
            total_tokens integer not null
        )
        """
    )
    connection.execute(
        """
        create table transition_candidates (
            file_key text not null,
            candidate_index integer not null,
            timestamp text not null,
            thread_id text not null,
            raw_path text not null,
            source text not null
        )
        """
    )
    connection.executemany(
        "insert into files (file_key, session_id) values (?, ?)",
        [
            ("file-z", "file-z"),
            ("file-a", "file-a"),
            ("archive-z", "file-z"),
        ],
    )
    return connection


def _insert_usage_records(connection: sqlite3.Connection) -> None:
    rows = [
        ("file-z", "file-z.jsonl", 1, "thread-a", "turn-z-1"),
        ("archive-z", "archive-z.jsonl", 0, "thread-a", "archive-z-0"),
        ("file-a", "file-a.jsonl", 3, "thread-z", "turn-a-3"),
        ("file-z", "file-z.jsonl", 0, "thread-a", "turn-z-0"),
        ("file-a", "file-a.jsonl", 1, "thread-z", "turn-a-1"),
    ]
    connection.executemany(
        """
        insert into usage_records values (
            ?, ?, ?, '2026-08-03T12:00:00Z', ?, ?, 'gpt-5.5', '', '',
            'project', 'Project', '[]', '', '', '', '', 1, 0, 0, 0, 0, 1
        )
        """,
        rows,
    )


def _insert_transition_candidates(connection: sqlite3.Connection) -> None:
    rows = [
        ("file-z", 1, "thread-a", "/repo/z/one"),
        ("archive-z", 0, "thread-a", "/repo/archive/zero"),
        ("file-a", 3, "thread-z", "/repo/a/three"),
        ("file-z", 0, "thread-a", "/repo/z/zero"),
        ("file-a", 1, "thread-z", "/repo/a/one"),
    ]
    connection.executemany(
        """
        insert into transition_candidates values (
            ?, ?, '2026-08-03T12:00:00Z', ?, ?, 'function_call'
        )
        """,
        rows,
    )


def _task_ids() -> set[str]:
    return {
        "thread-a",
        "thread-z",
        *(f"thread-b-{index:03d}" for index in range(500)),
    }
