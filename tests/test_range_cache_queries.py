from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import codex_usage.session_cache_queries as cache_queries
from codex_usage import aggregation
from codex_usage.session_cache import load_cached_session_data


def test_resolve_range_bounds_uses_utc_microseconds_for_all_ranges() -> None:
    now = datetime(2026, 8, 3, 12, tzinfo=UTC)

    bounds = {
        name: aggregation.resolve_range_bounds(name, UTC, now)
        for name in aggregation.RANGE_CHOICES
    }

    assert bounds["today"] == aggregation.RangeBounds(
        start_us=1_785_715_200_000_000,
        end_us=1_785_801_600_000_000,
    )
    assert bounds["yesterday"] == aggregation.RangeBounds(
        start_us=1_785_628_800_000_000,
        end_us=1_785_715_200_000_000,
    )
    assert bounds["7d"] == aggregation.RangeBounds(
        start_us=1_785_196_800_000_000,
        end_us=1_785_801_600_000_000,
    )
    assert bounds["30d"] == aggregation.RangeBounds(
        start_us=1_783_209_600_000_000,
        end_us=1_785_801_600_000_000,
    )
    assert bounds["month"] == aggregation.RangeBounds(
        start_us=1_785_542_400_000_000,
        end_us=1_788_220_800_000_000,
    )
    assert bounds["all"] == aggregation.RangeBounds(start_us=None, end_us=None)


def test_resolve_range_bounds_preserves_local_midnight_across_dst() -> None:
    timezone = ZoneInfo("America/Toronto")

    spring = aggregation.resolve_range_bounds(
        "today", timezone, datetime(2026, 3, 8, 12, tzinfo=timezone)
    )
    fall = aggregation.resolve_range_bounds(
        "today", timezone, datetime(2026, 11, 1, 12, tzinfo=timezone)
    )

    assert spring == aggregation.RangeBounds(
        start_us=1_772_946_000_000_000,
        end_us=1_773_028_800_000_000,
    )
    assert fall == aggregation.RangeBounds(
        start_us=1_793_505_600_000_000,
        end_us=1_793_595_600_000_000,
    )


def test_range_query_uses_timestamp_index_and_selected_file_keys() -> None:
    connection = _range_query_connection()
    connection.execute(
        "insert into files (file_key, session_id) values (?, ?)", ("stale-child", "child")
    )
    _insert_usage_record(
        connection, "stale-child", 0, "2026-08-03T12:00:00Z", "stale"
    )
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    today = aggregation.resolve_range_bounds(
        "today", UTC, datetime(2026, 8, 3, 12, tzinfo=UTC)
    )

    records = cache_queries.load_records_for_range(
        connection, {"child", "stale-child"}, today
    )

    assert [(record.file_path.name, record.turn_id) for record in records] == [
        ("child.jsonl", "today"),
    ]
    usage_queries = [sql for sql in statements if "usage_records" in sql]
    assert len(usage_queries) == 1
    assert "timestamp_us >=" in usage_queries[0]
    assert "timestamp_us <" in usage_queries[0]
    assert "files.file_key = files.session_id" in usage_queries[0]
    assert " in (" not in usage_queries[0].casefold()


def test_range_query_uses_fixed_shapes_for_open_and_unbounded_ranges() -> None:
    connection = _range_query_connection()
    selected = {"child"}
    shapes = (
        (aggregation.RangeBounds(start_us=None, end_us=None), 2, ""),
        (aggregation.RangeBounds(start_us=1_785_715_200_000_000, end_us=None), 1, "timestamp_us >="),
        (aggregation.RangeBounds(start_us=None, end_us=1_785_715_200_000_000), 1, "timestamp_us <"),
    )

    for bounds, expected_count, required_clause in shapes:
        statements: list[str] = []
        connection.set_trace_callback(statements.append)

        records = cache_queries.load_records_for_range(connection, selected, bounds)

        assert len(records) == expected_count
        usage_query = next(sql for sql in statements if "usage_records" in sql)
        assert required_clause in usage_query


def test_cached_range_uses_out_of_range_parent_for_identity_only(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_range_session(
        sessions / "2026" / "08" / "02" / "parent.jsonl",
        session_id="parent-thread",
        timestamp="2026-08-02T12:00:00Z",
        cwd="/repo/parent",
        repository_url="https://github.com/example/parent.git",
        total_tokens=100,
    )
    _write_range_session(
        sessions / "2026" / "08" / "03" / "child.jsonl",
        session_id="child-thread",
        timestamp="2026-08-03T12:00:00Z",
        cwd="/repo/child",
        parent_thread_id="parent-thread",
        total_tokens=50,
    )
    bounds = aggregation.resolve_range_bounds(
        "today", UTC, datetime(2026, 8, 3, 12, tzinfo=UTC)
    )

    data = load_cached_session_data(
        [sessions],
        cache_dir=tmp_path / "cache",
        auto_transitions=False,
        range_bounds=bounds,
    )

    assert [record.session_id for record in data.records] == ["child-thread"]
    assert data.records[0].project_key == "https://github.com/example/parent"
    assert data.records[0].usage.total_tokens == 50


def test_parent_identity_lookup_chunks_ids_and_uses_canonical_rows() -> None:
    connection = _range_query_connection()
    connection.execute(
        "update usage_records set git_repository_url = ? where session_id = ?",
        ("https://github.com/example/parent.git", "parent"),
    )
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    parent_ids = {"parent", *(f"missing-{index:03d}" for index in range(500))}

    identities = cache_queries.load_parent_identity_records(connection, parent_ids)

    assert [identity.session_id for identity in identities] == ["parent"]
    queries = [sql for sql in statements if "from usage_records" in sql]
    assert len(queries) == 2
    assert all("files.file_key = files.session_id" in query for query in queries)
    assert all("timestamp_us desc" in query for query in queries)


def test_cached_range_keeps_retained_missing_records(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    retained = sessions / "2026" / "08" / "03" / "retained.jsonl"
    _write_range_session(
        retained,
        session_id="retained-thread",
        timestamp="2026-08-03T12:00:00Z",
        cwd="/repo/retained",
        total_tokens=25,
    )
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    retained.unlink()
    bounds = aggregation.resolve_range_bounds(
        "today", UTC, datetime(2026, 8, 3, 12, tzinfo=UTC)
    )

    ranged = load_cached_session_data(
        [sessions],
        cache_dir=cache_dir,
        auto_transitions=False,
        range_bounds=bounds,
    )

    assert [record.session_id for record in ranged.records] == ["retained-thread"]
    assert ranged.stats.files_missing_retained == 1


@pytest.mark.parametrize(
    ("now", "timestamps", "expected_sessions"),
    [
        (
            datetime(2026, 3, 8, 12, tzinfo=ZoneInfo("America/Toronto")),
            (
                "2026-03-08T04:59:59Z",
                "2026-03-08T05:00:00Z",
                "2026-03-09T03:59:59Z",
                "2026-03-09T04:00:00Z",
            ),
            ("record-1", "record-2"),
        ),
        (
            datetime(2026, 11, 1, 12, tzinfo=ZoneInfo("America/Toronto")),
            (
                "2026-11-01T03:59:59Z",
                "2026-11-01T04:00:00Z",
                "2026-11-02T04:59:59Z",
                "2026-11-02T05:00:00Z",
            ),
            ("record-1", "record-2"),
        ),
    ],
)
def test_cached_range_matches_direct_oracle_across_dst_boundaries(
    tmp_path: Path,
    now: datetime,
    timestamps: tuple[str, ...],
    expected_sessions: tuple[str, ...],
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    for index, timestamp in enumerate(timestamps):
        _write_range_session(
            sessions / f"record-{index}.jsonl",
            session_id=f"record-{index}",
            timestamp=timestamp,
            cwd=f"/repo/record-{index}",
            total_tokens=index + 1,
        )
    cache_dir = tmp_path / "cache"
    full = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    timezone = ZoneInfo("America/Toronto")
    bounds = aggregation.resolve_range_bounds("today", timezone, now)

    ranged = load_cached_session_data(
        [sessions],
        cache_dir=cache_dir,
        auto_transitions=False,
        range_bounds=bounds,
    )

    expected = aggregation.filter_records_by_range(full.records, "today", timezone, now)
    assert ranged.records == expected
    assert [record.session_id for record in ranged.records] == list(expected_sessions)


def _range_query_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        create table files (file_key text primary key, session_id text not null);
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
            input_tokens integer not null,
            cached_input_tokens integer not null,
            cache_write_input_tokens integer not null,
            output_tokens integer not null,
            reasoning_output_tokens integer not null,
            total_tokens integer not null
        );
        create index usage_records_timestamp_us_idx on usage_records (timestamp_us);
        create index usage_records_session_timestamp_idx on usage_records (session_id, timestamp_us);
        """
    )
    connection.executemany(
        "insert into files (file_key, session_id) values (?, ?)",
        [("parent", "parent"), ("child", "child"), ("other", "other")],
    )
    _insert_usage_record(connection, "parent", 0, "2026-08-01T12:00:00Z", "parent")
    _insert_usage_record(connection, "child", 0, "2026-08-02T12:00:00Z", "old")
    _insert_usage_record(connection, "child", 1, "2026-08-03T12:00:00Z", "today")
    _insert_usage_record(connection, "other", 0, "2026-08-03T12:00:00Z", "other")
    return connection


def _insert_usage_record(
    connection: sqlite3.Connection,
    file_key: str,
    record_index: int,
    timestamp: str,
    turn_id: str,
) -> None:
    timestamp_us = aggregation.datetime_to_utc_microseconds(
        datetime.fromisoformat(timestamp)
    )
    connection.execute(
        """
        insert into usage_records values (
            ?, ?, ?, ?, ?, ?, ?, 'gpt-5.5', '', '', 'project', 'Project', '[]',
            '', '', '', '', 1, 0, 0, 0, 0, 1
        )
        """,
        (file_key, f"{file_key}.jsonl", record_index, timestamp, timestamp_us, file_key, turn_id),
    )


def _write_range_session(
    path: Path,
    *,
    session_id: str,
    timestamp: str,
    cwd: str,
    total_tokens: int,
    repository_url: str = "",
    parent_thread_id: str = "",
) -> None:
    metadata: dict[str, object] = {
        "id": session_id,
        "timestamp": timestamp,
        "cwd": cwd,
    }
    if repository_url:
        metadata["git"] = {"repository_url": repository_url, "branch": "main"}
    if parent_thread_id:
        metadata["source"] = {
            "subagent": {"thread_spawn": {"parent_thread_id": parent_thread_id}}
        }
    rows = [
        {"timestamp": timestamp, "type": "session_meta", "payload": metadata},
        {"timestamp": timestamp, "type": "turn_context", "payload": {"model": "gpt-5.5"}},
        {
            "timestamp": timestamp,
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {"total_tokens": total_tokens}},
            },
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
