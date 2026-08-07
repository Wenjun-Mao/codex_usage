from __future__ import annotations

import sqlite3
from pathlib import Path

from codex_usage.session_parser_models import (
    SessionParseCheckpoint,
    parser_state_from_json,
    parser_state_to_json,
)


def load_parser_checkpoint(
    connection: sqlite3.Connection,
    file_key: str,
    path: Path,
) -> SessionParseCheckpoint | None:
    row = connection.execute(
        "select * from parser_checkpoints where file_key = ?",
        (file_key,),
    ).fetchone()
    if row is None:
        return None
    try:
        checkpoint = SessionParseCheckpoint(
            byte_offset=int(row["byte_offset"]),
            next_record_index=int(row["next_record_index"]),
            next_candidate_index=int(row["next_candidate_index"]),
            source_device=int(row["source_device"]),
            source_inode=int(row["source_inode"]),
            head_sha256=str(row["head_sha256"]),
            boundary_sha256=str(row["boundary_sha256"]),
            session_id=str(row["session_id"]),
            state=parser_state_from_json(str(row["state_json"]), path),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if (
        checkpoint.byte_offset < 0
        or checkpoint.next_record_index < 0
        or checkpoint.next_candidate_index < 0
        or not checkpoint.head_sha256
        or not checkpoint.boundary_sha256
    ):
        return None
    return checkpoint


def upsert_parser_checkpoint(
    connection: sqlite3.Connection,
    file_key: str,
    checkpoint: SessionParseCheckpoint,
) -> None:
    connection.execute(
        """
        insert or replace into parser_checkpoints (
            file_key, byte_offset, next_record_index, next_candidate_index,
            source_device, source_inode, head_sha256, boundary_sha256,
            session_id, state_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_key,
            checkpoint.byte_offset,
            checkpoint.next_record_index,
            checkpoint.next_candidate_index,
            checkpoint.source_device,
            checkpoint.source_inode,
            checkpoint.head_sha256,
            checkpoint.boundary_sha256,
            checkpoint.session_id,
            parser_state_to_json(checkpoint.state),
        ),
    )


def delete_parser_checkpoint(connection: sqlite3.Connection, file_key: str) -> None:
    connection.execute(
        "delete from parser_checkpoints where file_key = ?",
        (file_key,),
    )


def rekey_parser_checkpoint(
    connection: sqlite3.Connection,
    source_key: str,
    replacement_key: str,
) -> None:
    connection.execute(
        "update parser_checkpoints set file_key = ? where file_key = ?",
        (replacement_key, source_key),
    )
