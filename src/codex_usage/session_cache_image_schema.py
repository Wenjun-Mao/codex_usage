"""Additive image cache table definition."""
import sqlite3


def _create_image_operations_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table image_operations (
            file_key text not null,
            tool_call_id text not null,
            timestamp text not null,
            timestamp_us integer not null,
            task_id text not null,
            root_task_id text not null,
            usage_role text not null check (usage_role in ('root', 'subagent')),
            turn_id text not null,
            project_key text not null,
            project_label text not null,
            kind text not null check (kind in ('generate', 'edit_reference', 'unknown')),
            outcome text not null check (outcome in ('attempted', 'succeeded', 'failed')),
            output_count integer not null check (output_count >= 0),
            output_width integer,
            output_height integer,
            output_format text not null,
            quality text not null,
            evidence_json text not null,
            usage_json text not null,
            primary key (file_key, tool_call_id)
        )
        """
    )
    connection.execute(
        "create index image_operations_task_idx on image_operations (task_id, timestamp_us)"
    )


