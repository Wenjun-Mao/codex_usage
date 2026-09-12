from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC

from codex_usage.image_capture_models import captured_operation_from_dict
from codex_usage.image_models import resolve_image_model_evidence
from codex_usage.models import UsageRecord
from codex_usage.session_cache_queries import row_to_usage_record
from codex_usage.session_project_lineage import finalize_session_records


def insert_generation_events(
    connection: sqlite3.Connection,
    generation_id: int,
    source_key: str,
    *,
    start_record_index: int = 0,
) -> None:
    records = _resolved_generation_records(
        connection,
        source_key,
        start_record_index=start_record_index,
    )
    title_row = connection.execute(
        "select session_id from session_metadata where file_key = ?", (source_key,)
    ).fetchone()
    default_title = str(title_row["session_id"]) if title_row else source_key
    for record_index, record in records:
        _insert_event(
            connection,
            generation_id=generation_id,
            source_record_index=record_index,
            record=record,
            default_title=default_title,
        )


def insert_generation_image_events(
    connection: sqlite3.Connection,
    generation_id: int,
    source_key: str,
) -> None:
    """Upsert content-free image activity for one trusted source generation."""
    rows = connection.execute(
        "select * from image_operations where file_key = ? order by tool_call_id",
        (source_key,),
    ).fetchall()
    for row in rows:
        _insert_image_event(connection, generation_id, row)


def rebuild_normalized_events(connection: sqlite3.Connection) -> None:
    """Rebuild durable ownership from the parser workset in a stable order."""
    source_rows = list(
        connection.execute(
            """
            select usage_records.*, ledger_generations.generation_id
            from usage_records
            join ledger_sources
              on ledger_sources.source_key = usage_records.file_key
            join ledger_generations
              on ledger_generations.source_id = ledger_sources.source_id
             and ledger_generations.status = 'trusted'
            order by usage_records.file_key, usage_records.record_index
            """
        )
    )
    raw_records = [row_to_usage_record(row) for row in source_rows]
    resolved_records = finalize_session_records([raw_records])

    connection.execute("delete from ledger_usage_events")
    connection.execute("delete from ledger_image_events")
    connection.execute("delete from ledger_contexts")
    connection.execute("delete from ledger_tasks")
    connection.execute("delete from ledger_projects")
    connection.execute("delete from ledger_models")

    default_titles = {
        str(row["file_key"]): str(row["session_id"])
        for row in connection.execute("select file_key, session_id from session_metadata")
    }
    for row, record in zip(source_rows, resolved_records, strict=True):
        _insert_event(
            connection,
            generation_id=int(row["generation_id"]),
            source_record_index=int(row["record_index"]),
            record=record,
            default_title=default_titles.get(str(row["file_key"]), str(row["file_key"])),
        )
    _rebuild_image_events(connection)


def _rebuild_image_events(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        select image_operations.*, ledger_generations.generation_id
        from image_operations
        join ledger_sources on ledger_sources.source_key = image_operations.file_key
        join ledger_generations
          on ledger_generations.source_id = ledger_sources.source_id
         and ledger_generations.status = 'trusted'
        order by image_operations.file_key, image_operations.tool_call_id
        """
    ).fetchall()
    for row in rows:
        _insert_image_event(connection, int(row["generation_id"]), row)


def _resolved_generation_records(
    connection: sqlite3.Connection,
    source_key: str,
    *,
    start_record_index: int,
) -> list[tuple[int, UsageRecord]]:
    rows = list(
        connection.execute(
            """
            select * from usage_records
            where file_key = ? and record_index >= ? order by record_index
            """,
            (source_key, start_record_index),
        )
    )
    records = [row_to_usage_record(row) for row in rows]
    parent_records = _parent_identity_records(
        connection,
        {record.parent_thread_id for record in records if record.parent_thread_id},
    )
    resolved = finalize_session_records([records], identity_records=parent_records)
    return [
        (int(row["record_index"]), record)
        for row, record in zip(rows, resolved, strict=True)
    ]


def _parent_identity_records(
    connection: sqlite3.Connection,
    parent_ids: set[str],
) -> list[UsageRecord]:
    records: list[UsageRecord] = []
    pending = set(parent_ids)
    seen: set[str] = set()
    while pending:
        batch = tuple(sorted(pending - seen))
        if not batch:
            break
        seen.update(batch)
        placeholders = ", ".join("?" for _ in batch)
        rows = list(
            connection.execute(
                f"""
                select * from usage_records
                where session_id in ({placeholders})
                  and git_repository_url != ''
                order by file_key, record_index
                """,
                batch,
            )
        )
        resolved_rows = [row_to_usage_record(row) for row in rows]
        records.extend(resolved_rows)
        pending.update(
            record.parent_thread_id
            for record in resolved_rows
            if record.parent_thread_id and record.parent_thread_id not in seen
        )
    return records


def _insert_event(
    connection: sqlite3.Connection,
    *,
    generation_id: int,
    source_record_index: int,
    record: UsageRecord,
    default_title: str,
) -> None:
    project_id = _project_id(connection, record)
    model_id = _model_id(connection, record.model)
    task_id = record.session_id
    _upsert_task(connection, record, task_id, default_title, project_id)
    context_id = _context_id(connection, record, project_id)
    usage = record.usage
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
            source_record_index,
            record.timestamp.isoformat(),
            int(record.timestamp.timestamp() * 1_000_000),
            task_id,
            record.turn_id,
            model_id,
            context_id,
            record.parent_thread_id,
            record.usage_role,
            usage.input_tokens,
            usage.cached_input_tokens,
            usage.cache_write_input_tokens,
            usage.output_tokens,
            usage.reasoning_output_tokens,
            usage.total_tokens,
        ),
    )


def _insert_image_event(
    connection: sqlite3.Connection,
    generation_id: int,
    row: sqlite3.Row,
) -> None:
    operation = captured_operation_from_dict(
        {
            "tool_call_id": str(row["tool_call_id"]),
            "timestamp": str(row["timestamp"]),
            "task_id": str(row["task_id"]),
            "root_task_id": str(row["root_task_id"]),
            "usage_role": str(row["usage_role"]),
            "turn_id": str(row["turn_id"]),
            "project_key": str(row["project_key"]),
            "project_label": str(row["project_label"]),
            "kind": str(row["kind"]),
            "outcome": str(row["outcome"]),
            "output_count": int(row["output_count"]),
            "output_width": row["output_width"],
            "output_height": row["output_height"],
            "output_format": str(row["output_format"]),
            "quality": str(row["quality"]),
            "evidence": json.loads(str(row["evidence_json"])),
            "usage": json.loads(str(row["usage_json"])),
        }
    )
    project_id = _image_project_id(connection, operation.project_key, operation.project_label)
    _upsert_image_task(connection, operation, project_id)
    resolved = resolve_image_model_evidence(operation.evidence)
    timestamp_us = int(operation.timestamp.astimezone(UTC).timestamp() * 1_000_000)
    connection.execute(
        """
        insert into ledger_image_events (
            generation_id, tool_call_id, timestamp, timestamp_us, task_id,
            root_task_id, usage_role, turn_id, project_id, kind, outcome,
            output_count, output_width, output_height, output_format, quality,
            model_family, model_variant, model_raw_identity, evidence_json,
            usage_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(generation_id, tool_call_id) do update set
            timestamp = excluded.timestamp,
            timestamp_us = excluded.timestamp_us,
            task_id = excluded.task_id,
            root_task_id = excluded.root_task_id,
            usage_role = excluded.usage_role,
            turn_id = excluded.turn_id,
            project_id = excluded.project_id,
            kind = excluded.kind,
            outcome = excluded.outcome,
            output_count = excluded.output_count,
            output_width = excluded.output_width,
            output_height = excluded.output_height,
            output_format = excluded.output_format,
            quality = excluded.quality,
            model_family = excluded.model_family,
            model_variant = excluded.model_variant,
            model_raw_identity = excluded.model_raw_identity,
            evidence_json = excluded.evidence_json,
            usage_json = excluded.usage_json
        """,
        (
            generation_id,
            operation.tool_call_id,
            operation.timestamp.isoformat(),
            timestamp_us,
            operation.task_id,
            operation.root_task_id,
            operation.usage_role,
            operation.turn_id,
            project_id,
            operation.kind.value,
            operation.outcome.value,
            operation.output_count,
            operation.output_width,
            operation.output_height,
            operation.output_format,
            operation.quality,
            resolved.model.family.value,
            resolved.model.variant.value,
            resolved.model.raw_identity,
            json.dumps(
                [
                    {
                        "raw_identity": item.raw_identity,
                        "source": item.source.value,
                        "confidence": item.confidence.value,
                        "version": item.version,
                    }
                    for item in operation.evidence
                ],
                separators=(",", ":"),
                sort_keys=True,
            ),
            json.dumps(
                {
                    "text_input_tokens": operation.usage.text_input_tokens,
                    "cached_text_input_tokens": operation.usage.cached_text_input_tokens,
                    "text_output_tokens": operation.usage.text_output_tokens,
                    "image_input_tokens": operation.usage.image_input_tokens,
                    "cached_image_input_tokens": operation.usage.cached_image_input_tokens,
                    "image_output_tokens": operation.usage.image_output_tokens,
                    "total_tokens": operation.usage.total_tokens,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        ),
    )


def _image_project_id(
    connection: sqlite3.Connection,
    project_key: str,
    project_label: str,
) -> int:
    key = project_key or "unknown"
    connection.execute(
        """
        insert into ledger_projects (project_key, label, aliases_json, repository_url)
        values (?, ?, '[]', '')
        on conflict(project_key) do update set label = excluded.label
        """,
        (key, project_label or key),
    )
    row = connection.execute(
        "select project_id from ledger_projects where project_key = ?", (key,)
    ).fetchone()
    assert row is not None
    return int(row["project_id"])


def _upsert_image_task(
    connection: sqlite3.Connection,
    operation,
    project_id: int,
) -> None:
    timestamp = operation.timestamp.isoformat()
    connection.execute(
        """
        insert into ledger_tasks (
            task_id, parent_task_id, usage_role, title, project_id, cwd,
            first_seen_at, last_seen_at
        ) values (?, ?, ?, ?, ?, '', ?, ?)
        on conflict(task_id) do update set
            project_id = excluded.project_id,
            last_seen_at = max(ledger_tasks.last_seen_at, excluded.last_seen_at)
        """,
        (
            operation.task_id,
            "" if operation.root_task_id == operation.task_id else operation.root_task_id,
            operation.usage_role,
            operation.task_id,
            project_id,
            timestamp,
            timestamp,
        ),
    )


def _project_id(connection: sqlite3.Connection, record: UsageRecord) -> int:
    key = record.project_key or "unknown"
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
            record.project_label or key,
            json.dumps(list(record.project_aliases)),
            record.git_repository_url,
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
    record: UsageRecord,
    task_id: str,
    title: str,
    project_id: int,
) -> None:
    timestamp = record.timestamp.isoformat()
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
            record.parent_thread_id,
            record.usage_role,
            title,
            project_id,
            record.cwd,
            timestamp,
            timestamp,
        ),
    )


def _context_id(
    connection: sqlite3.Connection,
    record: UsageRecord,
    project_id: int,
) -> int:
    values = (
        record.cwd,
        record.git_repository_url,
        record.git_branch,
        record.effort,
        record.collaboration_mode,
        json.dumps(list(record.project_aliases)),
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
