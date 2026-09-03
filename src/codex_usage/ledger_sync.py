from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.ledger_events import insert_generation_events
from codex_usage.ledger_schema import increment_ledger_revision, open_ledger


def synchronize_parser_workset(ledger_path: Path) -> tuple[int, bool]:
    """Mirror parser-owned rows into the normalized, report-owned ledger."""
    with open_ledger(ledger_path) as connection:
        connection.execute("begin immediate")
        try:
            changed = _sync_sources(connection)
            changed |= _sync_transitions(connection)
            revision = (
                increment_ledger_revision(connection)
                if changed
                else _current_revision(connection)
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    return revision, changed


def _sync_sources(connection: sqlite3.Connection) -> bool:
    changed = False
    observed_keys: set[str] = set()
    rows = connection.execute(
        """
        select files.*,
               parser_checkpoints.byte_offset,
               parser_checkpoints.source_device,
               parser_checkpoints.source_inode,
               parser_checkpoints.head_sha256,
               parser_checkpoints.boundary_sha256,
               (select count(*) from usage_records
                where usage_records.file_key = files.file_key) as record_count
        from files
        left join parser_checkpoints on parser_checkpoints.file_key = files.file_key
        order by files.file_key
        """
    ).fetchall()
    for row in rows:
        source_key = str(row["file_key"])
        if bool(row["is_missing"]) and row["byte_offset"] is None:
            continue
        observed_keys.add(source_key)
        source_id, source_changed, was_stale = _upsert_source(connection, row)
        changed |= source_changed
        if row["byte_offset"] is None or bool(row["error"]):
            continue
        changed |= _sync_generation(
            connection,
            source_id,
            source_key,
            row,
            force_event_rebuild=was_stale,
        )

    for row in connection.execute(
        "select source_id, source_key from ledger_sources where is_missing = 0"
    ).fetchall():
        if str(row["source_key"]) in observed_keys:
            continue
        connection.execute(
            """
            update ledger_sources
            set is_missing = 1, missing_since = coalesce(missing_since, ?)
            where source_id = ?
            """,
            (datetime.now(UTC).isoformat(), int(row["source_id"])),
        )
        changed = True
    removed = connection.execute(
        """
        delete from ledger_sources
        where is_missing = 1
          and not exists (
              select 1 from ledger_generations
              where ledger_generations.source_id = ledger_sources.source_id
          )
        """
    )
    changed |= removed.rowcount > 0
    return changed


def _upsert_source(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> tuple[int, bool, bool]:
    key = str(row["file_key"])
    current = connection.execute(
        "select * from ledger_sources where source_key = ?", (key,)
    ).fetchone()
    values = (
        str(row["path"]),
        str(row["session_dir"]),
        str(row["storage_state"]),
        str(row["source_device"] or "0"),
        str(row["source_inode"] or "0"),
        int(row["size_bytes"]),
        int(row["mtime_ns"]),
        str(row["last_seen_at"]),
        str(row["missing_since"] or "") or None,
        int(row["is_missing"]),
        int(bool(row["error"])),
        str(row["error"] or ""),
        str(row["error"] or ""),
    )
    if current is None:
        cursor = connection.execute(
            """
            insert into ledger_sources (
                source_key, path, session_dir, storage_state, source_device,
                source_inode, size_bytes, mtime_ns, last_seen_at, missing_since,
                is_missing, is_stale, stale_reason, error
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (key, *values),
        )
        return int(cursor.lastrowid), True, False
    was_stale = bool(current["is_stale"])
    changed = any(
        current[name] != value
        for name, value in zip(
            (
                "path",
                "session_dir",
                "storage_state",
                "source_device",
                "source_inode",
                "size_bytes",
                "mtime_ns",
                "last_seen_at",
                "missing_since",
                "is_missing",
                "is_stale",
                "stale_reason",
                "error",
            ),
            values,
            strict=True,
        )
        if name != "last_seen_at"
    )
    connection.execute(
        """
        update ledger_sources set
            path = ?, session_dir = ?, storage_state = ?, source_device = ?,
            source_inode = ?, size_bytes = ?, mtime_ns = ?, last_seen_at = ?,
            missing_since = ?, is_missing = ?, is_stale = ?, stale_reason = ?,
            error = ?
        where source_key = ?
        """,
        (*values, key),
    )
    return int(current["source_id"]), changed, was_stale


def _sync_generation(
    connection: sqlite3.Connection,
    source_id: int,
    source_key: str,
    row: sqlite3.Row,
    *,
    force_event_rebuild: bool,
) -> bool:
    generation_key = _generation_key(row)
    trusted = connection.execute(
        """
        select * from ledger_generations
        where source_id = ? and status = 'trusted'
        """,
        (source_id,),
    ).fetchone()
    record_count = int(row["record_count"])
    captured_size = int(row["byte_offset"])
    requires_replace = trusted is None or str(trusted["generation_key"]) != generation_key
    changed = force_event_rebuild or requires_replace or bool(
        trusted is not None
        and (
            int(trusted["captured_size"]) != captured_size
            or int(trusted["captured_mtime_ns"]) != int(row["mtime_ns"])
            or int(trusted["record_count"]) != record_count
        )
    )
    if not changed:
        return False
    now = datetime.now(UTC).isoformat()
    start_record_index = 0
    if requires_replace:
        connection.execute(
            """
            update ledger_generations set status = 'superseded', completed_at = ?
            where source_id = ? and status = 'trusted'
            """,
            (now, source_id),
        )
        generation_number = int(
            connection.execute(
                """
                select coalesce(max(generation_number), 0) + 1
                from ledger_generations where source_id = ?
                """,
                (source_id,),
            ).fetchone()[0]
        )
        cursor = connection.execute(
            """
            insert into ledger_generations (
                source_id, generation_key, generation_number, status,
                captured_size, captured_mtime_ns, head_sha256,
                boundary_sha256, record_count, captured_at, completed_at
            ) values (?, ?, ?, 'trusted', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                generation_key,
                generation_number,
                captured_size,
                int(row["mtime_ns"]),
                str(row["head_sha256"]),
                str(row["boundary_sha256"]),
                record_count,
                now,
                now,
            ),
        )
        generation_id = int(cursor.lastrowid)
    else:
        generation_id = int(trusted["generation_id"])
        previous_record_count = int(trusted["record_count"])
        can_append = (
            not force_event_rebuild
            and record_count >= previous_record_count
            and _event_index_is_complete(
                connection,
                generation_id,
                expected_count=previous_record_count,
            )
        )
        connection.execute(
            """
            update ledger_generations set
                captured_size = ?, captured_mtime_ns = ?, head_sha256 = ?,
                boundary_sha256 = ?, record_count = ?, completed_at = ?
            where generation_id = ?
            """,
            (
                captured_size,
                int(row["mtime_ns"]),
                str(row["head_sha256"]),
                str(row["boundary_sha256"]),
                record_count,
                now,
                generation_id,
            ),
        )
        if can_append:
            start_record_index = previous_record_count
        else:
            connection.execute(
                "delete from ledger_usage_events where generation_id = ?",
                (generation_id,),
            )
    insert_generation_events(
        connection,
        generation_id,
        source_key,
        start_record_index=start_record_index,
    )
    if not _event_index_is_complete(
        connection,
        generation_id,
        expected_count=record_count,
    ):
        raise RuntimeError(
            f"normalized event index does not match parser workset for {source_key}"
        )
    return True


def _event_index_is_complete(
    connection: sqlite3.Connection,
    generation_id: int,
    *,
    expected_count: int,
) -> bool:
    row = connection.execute(
        """
        select count(*) as event_count,
               coalesce(min(source_record_index), -1) as first_index,
               coalesce(max(source_record_index), -1) as last_index
        from ledger_usage_events where generation_id = ?
        """,
        (generation_id,),
    ).fetchone()
    event_count = int(row["event_count"])
    if expected_count == 0:
        return event_count == 0
    return (
        event_count == expected_count
        and int(row["first_index"]) == 0
        and int(row["last_index"]) == expected_count - 1
    )


def _sync_transitions(connection: sqlite3.Connection) -> bool:
    current = [
        tuple(row)
        for row in connection.execute(
            """
            select owner_task_id, source_key, source_label, target_key,
                   target_label, effective_from, confidence, evidence_json,
                   task_ids_json
            from ledger_transitions order by transition_id
            """
        )
    ]
    desired = [
        (
            str(row["owner_thread_id"]),
            str(row["source_key"]),
            str(row["source_label"]),
            str(row["target_key"]),
            str(row["target_label"]),
            str(row["effective_from"]),
            int(row["confidence"]),
            str(row["evidence_json"]),
            str(row["thread_ids_json"]),
        )
        for row in connection.execute(
            """
            select * from project_transitions
            order by effective_from, source_key, target_key
            """
        )
    ]
    if current == desired:
        return False
    connection.execute("delete from ledger_transitions")
    connection.executemany(
        """
        insert into ledger_transitions (
            owner_task_id, source_key, source_label, target_key, target_label,
            effective_from, confidence, evidence_json, task_ids_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        desired,
    )
    return True


def _generation_key(row: sqlite3.Row) -> str:
    source_device = str(row["source_device"] or "0")
    source_inode = str(row["source_inode"] or "0")
    if source_device != "0" and source_inode != "0":
        material = "\0".join(("file-identity", source_device, source_inode))
    else:
        # Guard digests change during ordinary growth while a file is smaller
        # than the digest window. They identify fallback generations only when
        # the OS cannot provide the stable identity required by append parsing.
        material = "\0".join(
            (
                "digest-fallback",
                str(row["file_key"]),
                str(row["head_sha256"] or ""),
            )
        )
    return hashlib.sha256(material.encode()).hexdigest()


def _current_revision(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "select value from ledger_meta where key = 'ledger_revision'"
    ).fetchone()
    return int(row["value"]) if row else 0
