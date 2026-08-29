from __future__ import annotations

import sqlite3
from pathlib import Path

from codex_usage.session_cache_checkpoints import load_parser_checkpoint
from codex_usage.session_inventory import SessionFileInventoryEntry
from codex_usage.session_parser_models import SessionParseCheckpoint


class StaleAppendCheckpointError(RuntimeError):
    """An append result was parsed from a checkpoint another writer replaced."""


def load_cached_rows(
    connection: sqlite3.Connection,
) -> dict[str, sqlite3.Row]:
    return {
        str(row["file_key"]): row
        for row in connection.execute(
            """
            select files.file_key, files.path, files.size_bytes, files.mtime_ns,
                   files.is_missing, files.session_id, files.error,
                   parser_checkpoints.byte_offset as checkpoint_offset
            from files
            left join parser_checkpoints
              on parser_checkpoints.file_key = files.file_key
            """
        )
    }


def eligible_append_checkpoint(
    connection: sqlite3.Connection,
    entry: SessionFileInventoryEntry,
    cached: sqlite3.Row | None,
    *,
    rebuilt: bool,
) -> SessionParseCheckpoint | None:
    if (
        rebuilt
        or cached is None
        or entry.storage_state != "active"
        or str(cached["path"]) != str(entry.path)
        or int(cached["is_missing"]) != 0
        or not entry.source_device
        or not entry.source_inode
    ):
        return None
    checkpoint = load_parser_checkpoint(connection, entry.file_key, entry.path)
    if checkpoint is None:
        return None
    if (
        entry.size_bytes <= checkpoint.byte_offset
        or entry.source_device != checkpoint.source_device
        or entry.source_inode != checkpoint.source_inode
        or str(cached["session_id"] or "") != checkpoint.session_id
    ):
        return None
    return checkpoint


def is_current_append_checkpoint(
    connection: sqlite3.Connection,
    *,
    file_key: str,
    path: Path,
    expected: SessionParseCheckpoint | None,
) -> bool:
    if expected is None:
        return False
    return load_parser_checkpoint(connection, file_key, path) == expected


def assert_current_append_checkpoint(
    connection: sqlite3.Connection,
    *,
    file_key: str,
    path: Path,
    expected: SessionParseCheckpoint | None,
) -> None:
    if not is_current_append_checkpoint(
        connection,
        file_key=file_key,
        path=path,
        expected=expected,
    ):
        raise StaleAppendCheckpointError(
            f"append checkpoint changed before commit for {file_key!r}"
        )
