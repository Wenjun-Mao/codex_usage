from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.session_parser_models import SessionParseCheckpoint
from codex_usage.storage_content import StorageContentMetrics


@dataclass(frozen=True, slots=True)
class StorageContentDiagnostic:
    path: str
    task_id: str
    analyzed_offset: int
    source_device: int
    source_inode: int
    source_mtime_ns: int
    head_sha256: str
    boundary_sha256: str
    metrics: StorageContentMetrics
    last_analyzed_at: str
    error: str = ""


def replace_content_diagnostic(
    connection: sqlite3.Connection,
    path: Path,
    task_id: str,
    checkpoint: SessionParseCheckpoint,
    metrics: StorageContentMetrics,
    *,
    source_mtime_ns: int = 0,
    error: str = "",
) -> None:
    upsert_content_diagnostic(
        connection,
        StorageContentDiagnostic(
            path=str(path),
            task_id=task_id,
            analyzed_offset=checkpoint.byte_offset,
            source_device=checkpoint.source_device,
            source_inode=checkpoint.source_inode,
            source_mtime_ns=source_mtime_ns,
            head_sha256=checkpoint.head_sha256,
            boundary_sha256=checkpoint.boundary_sha256,
            metrics=metrics,
            last_analyzed_at=datetime.now(UTC).isoformat(),
            error=error,
        ),
    )


def append_content_diagnostic(
    connection: sqlite3.Connection,
    path: Path,
    task_id: str,
    *,
    start_offset: int,
    checkpoint: SessionParseCheckpoint,
    metrics: StorageContentMetrics,
    source_mtime_ns: int = 0,
) -> bool:
    """Append metrics only when the diagnostic owns the exact same prefix."""
    existing = load_content_diagnostic(connection, path)
    if (
        existing is None
        or existing.task_id != task_id
        or existing.analyzed_offset != start_offset
        or existing.source_device != checkpoint.source_device
        or existing.source_inode != checkpoint.source_inode
    ):
        return False
    combined = existing.metrics + metrics
    upsert_content_diagnostic(
        connection,
        StorageContentDiagnostic(
            path=str(path),
            task_id=task_id,
            analyzed_offset=checkpoint.byte_offset,
            source_device=checkpoint.source_device,
            source_inode=checkpoint.source_inode,
            source_mtime_ns=source_mtime_ns,
            head_sha256=checkpoint.head_sha256,
            boundary_sha256=checkpoint.boundary_sha256,
            metrics=combined,
            last_analyzed_at=datetime.now(UTC).isoformat(),
        ),
    )
    return True


def load_content_diagnostic(
    connection: sqlite3.Connection, path: Path | str
) -> StorageContentDiagnostic | None:
    row = connection.execute(
        "select * from storage_content_diagnostics where path = ?",
        (str(path),),
    ).fetchone()
    return None if row is None else content_diagnostic_from_row(row)


def delete_content_diagnostic(
    connection: sqlite3.Connection, path: Path | str
) -> None:
    connection.execute(
        "delete from storage_content_diagnostics where path = ?", (str(path),)
    )


def content_diagnostic_from_row(
    row: sqlite3.Row,
    *,
    prefix: str = "",
) -> StorageContentDiagnostic | None:
    key = lambda name: f"{prefix}{name}"  # noqa: E731
    if row[key("analyzed_offset")] is None:
        return None
    return StorageContentDiagnostic(
        path=str(row[key("path")]),
        task_id=str(row[key("task_id")]),
        analyzed_offset=int(row[key("analyzed_offset")]),
        source_device=int(row[key("source_device")]),
        source_inode=int(row[key("source_inode")]),
        source_mtime_ns=int(row[key("source_mtime_ns")]),
        head_sha256=str(row[key("head_sha256")]),
        boundary_sha256=str(row[key("boundary_sha256")]),
        metrics=StorageContentMetrics(
            compacted_record_count=int(row[key("compacted_record_count")]),
            compacted_bytes=int(row[key("compacted_bytes")]),
            largest_compacted_record_bytes=int(
                row[key("largest_compacted_record_bytes")]
            ),
            media_compacted_record_count=int(
                row[key("media_compacted_record_count")]
            ),
            embedded_media_occurrence_count=int(
                row[key("embedded_media_occurrence_count")]
            ),
            unclassified_record_count=int(row[key("unclassified_record_count")]),
        ),
        last_analyzed_at=str(row[key("last_analyzed_at")]),
        error=str(row[key("error")]),
    )


def upsert_content_diagnostic(
    connection: sqlite3.Connection,
    diagnostic: StorageContentDiagnostic,
) -> None:
    metrics = diagnostic.metrics
    connection.execute(
        """
        insert into storage_content_diagnostics (
            path, task_id, analyzed_offset, source_device, source_inode, source_mtime_ns,
            head_sha256, boundary_sha256, compacted_record_count,
            compacted_bytes, largest_compacted_record_bytes,
            media_compacted_record_count, embedded_media_occurrence_count,
            unclassified_record_count, last_analyzed_at, error
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(path) do update set
            task_id = excluded.task_id,
            analyzed_offset = excluded.analyzed_offset,
            source_device = excluded.source_device,
            source_inode = excluded.source_inode,
            source_mtime_ns = excluded.source_mtime_ns,
            head_sha256 = excluded.head_sha256,
            boundary_sha256 = excluded.boundary_sha256,
            compacted_record_count = excluded.compacted_record_count,
            compacted_bytes = excluded.compacted_bytes,
            largest_compacted_record_bytes = excluded.largest_compacted_record_bytes,
            media_compacted_record_count = excluded.media_compacted_record_count,
            embedded_media_occurrence_count = excluded.embedded_media_occurrence_count,
            unclassified_record_count = excluded.unclassified_record_count,
            last_analyzed_at = excluded.last_analyzed_at,
            error = excluded.error
        """,
        (
            diagnostic.path,
            diagnostic.task_id,
            diagnostic.analyzed_offset,
            str(diagnostic.source_device),
            str(diagnostic.source_inode),
            diagnostic.source_mtime_ns,
            diagnostic.head_sha256,
            diagnostic.boundary_sha256,
            metrics.compacted_record_count,
            metrics.compacted_bytes,
            metrics.largest_compacted_record_bytes,
            metrics.media_compacted_record_count,
            metrics.embedded_media_occurrence_count,
            metrics.unclassified_record_count,
            diagnostic.last_analyzed_at,
            diagnostic.error,
        ),
    )
