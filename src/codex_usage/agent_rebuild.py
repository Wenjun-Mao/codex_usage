from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from codex_usage.agent_paths import agent_data_dir, ledger_database_path
from codex_usage.agent_private_files import (
    ensure_private_directory,
    ensure_private_file,
    ensure_private_sqlite_files,
)
from codex_usage.ledger_schema import open_ledger
from codex_usage.ledger_sync import synchronize_parser_workset
from codex_usage.parser import parse_session_append
from codex_usage.session_cache_checkpoints import load_parser_checkpoint
from codex_usage.session_cache_refresh import refresh_files
from codex_usage.session_cache_schema import _ensure_schema
from codex_usage.session_inventory import SessionFileInventoryEntry


STALE_ERROR_PREFIX = "stale append checkpoint:"
_WORKSET_TABLES = (
    "usage_records",
    "session_metadata",
    "transition_candidates",
    "parser_checkpoints",
)


@dataclass(frozen=True, slots=True)
class RebuildSliceResult:
    source_key: str
    complete: bool
    captured_bytes: int
    target_bytes: int
    bytes_read: int


def stale_source_keys(ledger_path: Path) -> tuple[str, ...]:
    with open_ledger(ledger_path, read_only=True) as connection:
        rows = connection.execute(
            """
            select source_key from ledger_sources
            where is_stale = 1 and is_missing = 0
            order by size_bytes, source_key
            """
        ).fetchall()
    return tuple(str(row["source_key"]) for row in rows)


def pending_incremental_source_count(ledger_path: Path) -> int:
    with open_ledger(ledger_path, read_only=True) as connection:
        row = connection.execute(
            """
            select count(*)
            from ledger_sources
            left join ledger_generations
              on ledger_generations.source_id = ledger_sources.source_id
             and ledger_generations.status = 'trusted'
            where ledger_sources.is_missing = 0
              and ledger_sources.is_stale = 0
              and coalesce(ledger_generations.captured_size, 0)
                  < ledger_sources.size_bytes
            """
        ).fetchone()
    return int(row[0])


def rebuild_stale_source_slice(
    codex_home: Path,
    source_key: str,
    *,
    max_bytes: int,
) -> RebuildSliceResult:
    """Advance one isolated rebuild and install it only when complete."""
    ledger_path = ledger_database_path(codex_home)
    source = _load_stale_source(ledger_path, source_key)
    path = Path(source["path"])
    stat = path.stat()
    entry = SessionFileInventoryEntry(
        file_key=source_key,
        path=path,
        session_dir=Path(source["session_dir"]),
        storage_state=str(source["storage_state"]),
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        file_key_is_fallback=source_key.startswith("codex-usage:fallback:path:"),
        source_device=int(stat.st_dev),
        source_inode=int(stat.st_ino),
    )
    staging_path = _staging_path(codex_home, source_key)
    ensure_private_directory(staging_path.parent)
    connection = sqlite3.connect(staging_path)
    ensure_private_file(staging_path)
    try:
        connection.row_factory = sqlite3.Row
        schema = _ensure_schema(connection)
        outcome = refresh_files(
            connection,
            [entry.session_dir],
            [entry],
            rebuilt=schema.created or schema.reset,
            max_workers=1,
            max_parse_bytes=max_bytes,
        )
        checkpoint = load_parser_checkpoint(connection, source_key, path)
        captured = checkpoint.byte_offset if checkpoint is not None else 0
    finally:
        connection.close()
        ensure_private_sqlite_files(staging_path)

    complete = checkpoint is not None and captured == entry.size_bytes
    if complete:
        _install_completed_rebuild(
            ledger_path,
            staging_path,
            entry,
            checkpoint,
        )
        synchronize_parser_workset(ledger_path)
        _remove_staging_files(staging_path)
    return RebuildSliceResult(
        source_key=source_key,
        complete=complete,
        captured_bytes=captured,
        target_bytes=entry.size_bytes,
        bytes_read=outcome.stats.source_bytes_read,
    )


def _load_stale_source(ledger_path: Path, source_key: str) -> sqlite3.Row:
    with open_ledger(ledger_path, read_only=True) as connection:
        row = connection.execute(
            """
            select source_key, path, session_dir, storage_state
            from ledger_sources
            where source_key = ? and is_stale = 1 and is_missing = 0
            """,
            (source_key,),
        ).fetchone()
    if row is None:
        raise ValueError(f"stale source is no longer available: {source_key}")
    return row


def _staging_path(codex_home: Path, source_key: str) -> Path:
    digest = hashlib.sha256(source_key.encode()).hexdigest()
    return agent_data_dir(codex_home) / "rebuilds" / f"{digest}.sqlite3"


def _install_completed_rebuild(
    ledger_path: Path,
    staging_path: Path,
    entry: SessionFileInventoryEntry,
    checkpoint,
) -> None:
    before = entry.path.stat()
    parse_session_append(
        entry.path,
        checkpoint,
        stop_offset=checkpoint.byte_offset,
        max_bytes=1,
    )
    after = entry.path.stat()
    if _file_snapshot(before) != _file_snapshot(after):
        raise OSError("source changed while the rebuilt checkpoint was verified")

    with open_ledger(ledger_path) as connection:
        connection.execute("attach database ? as rebuild", (str(staging_path),))
        try:
            connection.execute("begin immediate")
            current = connection.execute(
                "select path, error from files where file_key = ?",
                (entry.file_key,),
            ).fetchone()
            if (
                current is None
                or str(current["path"]) != str(entry.path)
                or not str(current["error"] or "").startswith(STALE_ERROR_PREFIX)
            ):
                raise RuntimeError("stale source changed before rebuild commit")
            _replace_workset_rows(connection, entry.file_key)
            _mark_rebuilt_tasks_dirty(connection, entry.file_key)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.execute("detach database rebuild")


def _replace_workset_rows(
    connection: sqlite3.Connection,
    source_key: str,
) -> None:
    for table in _WORKSET_TABLES:
        columns = _table_columns(connection, table)
        selected = ", ".join(columns)
        connection.execute(f"delete from {table} where file_key = ?", (source_key,))
        connection.execute(
            f"insert into {table} ({selected}) "
            f"select {selected} from rebuild.{table} where file_key = ?",
            (source_key,),
        )
    file_columns = _table_columns(connection, "files")
    selected = ", ".join(file_columns)
    connection.execute("delete from files where file_key = ?", (source_key,))
    connection.execute(
        f"insert into files ({selected}) "
        f"select {selected} from rebuild.files where file_key = ?",
        (source_key,),
    )


def _table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(
        str(row["name"])
        for row in connection.execute(f"pragma main.table_info({table})")
    )


def _mark_rebuilt_tasks_dirty(
    connection: sqlite3.Connection,
    source_key: str,
) -> None:
    task_ids = {
        str(row[0])
        for query in (
            "select session_id from rebuild.session_metadata where file_key = ?",
            "select distinct session_id from rebuild.usage_records where file_key = ?",
            "select distinct thread_id from rebuild.transition_candidates where file_key = ?",
        )
        for row in connection.execute(query, (source_key,))
        if row[0]
    }
    connection.executemany(
        "insert or ignore into dirty_transition_tasks (thread_id) values (?)",
        ((task_id,) for task_id in sorted(task_ids)),
    )


def _file_snapshot(stat) -> tuple[int, int, int, int]:
    return (int(stat.st_dev), int(stat.st_ino), stat.st_size, stat.st_mtime_ns)


def _remove_staging_files(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
