"""Parser-owned image metadata persistence."""
import json
import sqlite3
from datetime import UTC
from codex_usage.image_capture_models import captured_operation_to_dict


def insert_image_operations(
    connection: sqlite3.Connection,
    file_key: str,
    operations: tuple,
) -> None:
    """Persist normalized metadata only; tool payloads never reach SQLite."""
    for operation in operations:
        values = captured_operation_to_dict(operation)
        timestamp = operation.timestamp
        connection.execute(
            """
            insert into image_operations (
                file_key, tool_call_id, timestamp, timestamp_us, task_id,
                root_task_id, usage_role, turn_id, project_key, project_label,
                kind, outcome, output_count, output_width, output_height,
                output_format, quality, evidence_json, usage_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(file_key, tool_call_id) do update set
                timestamp = excluded.timestamp,
                timestamp_us = excluded.timestamp_us,
                task_id = excluded.task_id,
                root_task_id = excluded.root_task_id,
                usage_role = excluded.usage_role,
                turn_id = excluded.turn_id,
                project_key = excluded.project_key,
                project_label = excluded.project_label,
                kind = excluded.kind,
                outcome = excluded.outcome,
                output_count = excluded.output_count,
                output_width = excluded.output_width,
                output_height = excluded.output_height,
                output_format = excluded.output_format,
                quality = excluded.quality,
                evidence_json = excluded.evidence_json,
                usage_json = excluded.usage_json
            """,
            (
                file_key,
                operation.tool_call_id,
                timestamp.isoformat(),
                int(timestamp.astimezone(UTC).timestamp() * 1_000_000),
                operation.task_id,
                operation.root_task_id,
                operation.usage_role,
                operation.turn_id,
                operation.project_key,
                operation.project_label,
                operation.kind.value,
                operation.outcome.value,
                operation.output_count,
                operation.output_width,
                operation.output_height,
                operation.output_format,
                operation.quality,
                json.dumps(values["evidence"], separators=(",", ":"), sort_keys=True),
                json.dumps(values["usage"], separators=(",", ":"), sort_keys=True),
            ),
        )
