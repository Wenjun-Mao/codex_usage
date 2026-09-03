from __future__ import annotations

import hashlib
import json
import sqlite3


def insert_generation_events(
    connection: sqlite3.Connection,
    generation_id: int,
    source_key: str,
    *,
    start_record_index: int = 0,
) -> None:
    title_row = connection.execute(
        "select session_id from session_metadata where file_key = ?", (source_key,)
    ).fetchone()
    default_title = str(title_row["session_id"]) if title_row else source_key
    for row in connection.execute(
        """
        select * from usage_records
        where file_key = ? and record_index >= ? order by record_index
        """,
        (source_key, start_record_index),
    ):
        project_id = _project_id(connection, row)
        model_id = _model_id(connection, str(row["model"]))
        task_id = str(row["session_id"])
        _upsert_task(connection, row, task_id, default_title, project_id)
        context_id = _context_id(connection, row, project_id)
        connection.execute(
            """
            insert into ledger_usage_events (
                generation_id, source_record_index, timestamp, timestamp_us,
                task_id, turn_id, model_id, context_id, parent_task_id,
                usage_role, input_tokens, cached_input_tokens,
                cache_write_input_tokens, output_tokens,
                reasoning_output_tokens, total_tokens
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id,
                int(row["record_index"]),
                str(row["timestamp"]),
                int(row["timestamp_us"]),
                task_id,
                str(row["turn_id"] or ""),
                model_id,
                context_id,
                str(row["parent_thread_id"] or ""),
                str(row["usage_role"]),
                int(row["input_tokens"]),
                int(row["cached_input_tokens"]),
                int(row["cache_write_input_tokens"]),
                int(row["output_tokens"]),
                int(row["reasoning_output_tokens"]),
                int(row["total_tokens"]),
            ),
        )


def _project_id(connection: sqlite3.Connection, row: sqlite3.Row) -> int:
    key = str(row["project_key"] or "unknown")
    connection.execute(
        """
        insert into ledger_projects (
            project_key, label, aliases_json, repository_url
        ) values (?, ?, ?, ?)
        on conflict(project_key) do update set
            label = excluded.label,
            aliases_json = excluded.aliases_json,
            repository_url = excluded.repository_url
        """,
        (
            key,
            str(row["project_label"] or key),
            str(row["project_aliases_json"] or "[]"),
            str(row["git_repository_url"] or ""),
        ),
    )
    return int(
        connection.execute(
            "select project_id from ledger_projects where project_key = ?", (key,)
        ).fetchone()[0]
    )


def _model_id(connection: sqlite3.Connection, model: str) -> int:
    key = model or "unknown"
    connection.execute(
        "insert or ignore into ledger_models (model_key) values (?)", (key,)
    )
    return int(
        connection.execute(
            "select model_id from ledger_models where model_key = ?", (key,)
        ).fetchone()[0]
    )


def _upsert_task(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    task_id: str,
    title: str,
    project_id: int,
) -> None:
    timestamp = str(row["timestamp"])
    connection.execute(
        """
        insert into ledger_tasks (
            task_id, parent_task_id, usage_role, title, project_id, cwd,
            first_seen_at, last_seen_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(task_id) do update set
            parent_task_id = excluded.parent_task_id,
            usage_role = excluded.usage_role,
            project_id = excluded.project_id,
            cwd = excluded.cwd,
            last_seen_at = max(ledger_tasks.last_seen_at, excluded.last_seen_at)
        """,
        (
            task_id,
            str(row["parent_thread_id"] or ""),
            str(row["usage_role"]),
            title,
            project_id,
            str(row["cwd"] or ""),
            timestamp,
            timestamp,
        ),
    )


def _context_id(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    project_id: int,
) -> int:
    values = (
        str(row["cwd"] or ""),
        str(row["git_repository_url"] or ""),
        str(row["git_branch"] or ""),
        str(row["effort"] or ""),
        str(row["collaboration_mode"] or ""),
        str(row["project_aliases_json"] or "[]"),
    )
    material = json.dumps((project_id, *values), separators=(",", ":"))
    key = hashlib.sha256(material.encode()).hexdigest()
    connection.execute(
        """
        insert or ignore into ledger_contexts (
            context_key, project_id, cwd, repository_url, git_branch,
            effort, collaboration_mode, project_aliases_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (key, project_id, *values),
    )
    return int(
        connection.execute(
            "select context_id from ledger_contexts where context_key = ?", (key,)
        ).fetchone()[0]
    )
