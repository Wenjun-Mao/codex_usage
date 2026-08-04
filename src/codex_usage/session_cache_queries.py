from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Iterator
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.parser import parse_timestamp
from codex_usage.session_generation_models import RawRepoPathCandidate

_MAX_IN_QUERY_IDS = 500


def row_to_usage_record(row: sqlite3.Row) -> UsageRecord:
    return UsageRecord(
        timestamp=parse_timestamp(row["timestamp"])
        or datetime.fromtimestamp(0, tz=UTC),
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


def load_records_for_task_ids(
    connection: sqlite3.Connection,
    task_ids: Collection[str],
) -> list[UsageRecord]:
    rows = _query_current_generation_rows_in_chunks(
        connection,
        table="usage_records",
        column="session_id",
        task_ids=task_ids,
    )
    return [row_to_usage_record(row) for row in rows]


def load_raw_candidates_for_task_ids(
    connection: sqlite3.Connection,
    task_ids: Collection[str],
) -> list[RawRepoPathCandidate]:
    rows = _query_current_generation_rows_in_chunks(
        connection,
        table="transition_candidates",
        column="thread_id",
        task_ids=task_ids,
    )
    return [row_to_raw_candidate(row) for row in rows]


def load_all_raw_candidates(
    connection: sqlite3.Connection,
) -> list[RawRepoPathCandidate]:
    rows = connection.execute(
        """
        select transition_candidates.*
        from transition_candidates
        join files on files.file_key = transition_candidates.file_key
        where files.file_key = files.session_id
        order by transition_candidates.file_key, transition_candidates.candidate_index
        """
    )
    return [row_to_raw_candidate(row) for row in rows]


def query_rows_in_chunks(
    connection: sqlite3.Connection,
    column: str,
    task_ids: Collection[str],
) -> list[sqlite3.Row]:
    if column != "session_id":
        raise ValueError(f"unsupported usage-record task column: {column}")
    rows = _query_rows_in_chunks(
        connection,
        table="usage_records",
        column=column,
        task_ids=task_ids,
    )
    return sorted(
        rows, key=lambda row: (str(row["file_key"]), int(row["record_index"]))
    )


def query_candidate_rows_in_chunks(
    connection: sqlite3.Connection,
    task_ids: Collection[str],
) -> list[sqlite3.Row]:
    rows = _query_rows_in_chunks(
        connection,
        table="transition_candidates",
        column="thread_id",
        task_ids=task_ids,
    )
    return sorted(
        rows, key=lambda row: (str(row["file_key"]), int(row["candidate_index"]))
    )


def row_to_raw_candidate(row: sqlite3.Row) -> RawRepoPathCandidate:
    timestamp = parse_timestamp(row["timestamp"])
    if timestamp is None:
        raise ValueError("cached transition candidate has no valid timestamp")
    return RawRepoPathCandidate(
        raw_path=str(row["raw_path"]),
        timestamp=timestamp,
        thread_id=str(row["thread_id"]),
        source=str(row["source"]),
    )


def _query_rows_in_chunks(
    connection: sqlite3.Connection,
    *,
    table: str,
    column: str,
    task_ids: Collection[str],
) -> list[sqlite3.Row]:
    rows: list[sqlite3.Row] = []
    for task_id_chunk in _task_id_chunks(task_ids):
        placeholders = ", ".join("?" for _ in task_id_chunk)
        rows.extend(
            connection.execute(
                f"select * from {table} where {column} in ({placeholders})",
                task_id_chunk,
            )
        )
    return rows


def _query_current_generation_rows_in_chunks(
    connection: sqlite3.Connection,
    *,
    table: str,
    column: str,
    task_ids: Collection[str],
) -> list[sqlite3.Row]:
    index_column = {
        ("usage_records", "session_id"): "record_index",
        ("transition_candidates", "thread_id"): "candidate_index",
    }.get((table, column))
    if index_column is None:
        raise ValueError("unsupported current-generation query")
    rows: list[sqlite3.Row] = []
    for task_id_chunk in _task_id_chunks(task_ids):
        placeholders = ", ".join("?" for _ in task_id_chunk)
        rows.extend(
            connection.execute(
                f"""
                select {table}.*
                from {table}
                join files on files.file_key = {table}.file_key
                where {table}.{column} in ({placeholders})
                    and files.file_key = files.session_id
                order by {table}.file_key, {table}.{index_column}
                """,
                task_id_chunk,
            )
        )
    return sorted(
        rows,
        key=lambda row: (str(row["file_key"]), int(row[index_column])),
    )


def _task_id_chunks(task_ids: Collection[str]) -> Iterator[tuple[str, ...]]:
    ordered = tuple(sorted({task_id for task_id in task_ids if task_id}))
    for start in range(0, len(ordered), _MAX_IN_QUERY_IDS):
        yield ordered[start : start + _MAX_IN_QUERY_IDS]
