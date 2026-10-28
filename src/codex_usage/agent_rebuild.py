from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path

from codex_usage.agent_capture import session_dirs_for_home
from codex_usage.agent_rebuild_models import (
    RebuildOutcome,
    RebuildReason,
    RebuildSliceResult,
    checkpoint_advanced,
    checkpoint_progress,
)
from codex_usage.agent_rebuild_authority import (
    assert_attached_stage,
    assert_installed_authority,
    assert_live_rebuild_authority,
    bind_rebuild_authority,
    load_rebuild_source,
    validate_staged_capture,
)
from codex_usage.agent_paths import agent_data_dir, ledger_database_path
from codex_usage.agent_private_files import (
    ensure_private_directory,
    ensure_private_file,
    ensure_private_sqlite_files,
)
from codex_usage.ledger_schema import open_ledger
from codex_usage.ledger_sync import synchronize_parser_workset_in_transaction
from codex_usage.ledger_rebuild_receipts import supersede_rebuilt_generations
from codex_usage.parser import parse_session_append
from codex_usage.session_cache_checkpoints import load_parser_checkpoint
from codex_usage.session_cache_refresh import refresh_files
from codex_usage.session_cache_schema import _ensure_schema
from codex_usage.history_upgrade_receipts import pending_upgrade_keys
from codex_usage.session_history_invalidation import (
    parse_invalidation_epoch, invalidate_dependents, rekey_invalidation, complete_invalidation,
    pending_invalidation,
)
from codex_usage.session_inventory import (
    SessionFileInventoryEntry,
    collect_session_file_inventory,
)


STALE_ERROR_PREFIX = "stale append checkpoint:"
_WORKSET_TABLES = (
    "usage_records",
    "session_metadata",
    "transition_candidates",
    "image_operations",
    "quota_cache",
    "parser_checkpoints",
    "speed_cache_facts",
    "speed_cache_tools",
    "speed_cache_uncertain_tools",
    "speed_cache_dirty",
)


def stale_source_keys(ledger_path: Path) -> tuple[str, ...]:
    with open_ledger(ledger_path, read_only=True) as connection:
        excluded = pending_upgrade_keys(connection)
        rows = connection.execute(
            """
            select source_key, is_missing from ledger_sources
            where is_stale = 1
            order by size_bytes, source_key
            """
        ).fetchall()
        return tuple(str(row["source_key"]) for row in rows if str(row["source_key"]) not in excluded
                     and (not row["is_missing"] or load_rebuild_source(connection, row["source_key"]) is not None))


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
        discovery_pending = len(pending_upgrade_keys(connection, budget_only=True))
    return int(row[0]) + discovery_pending


def rebuild_stale_source_slice(
    codex_home: Path,
    source_key: str,
    *,
    max_bytes: int,
) -> RebuildSliceResult:
    """Advance one isolated rebuild and install it only when complete."""
    ledger_path = ledger_database_path(codex_home)
    source = _load_stale_source(ledger_path, source_key)
    from codex_usage.history_upgrade_relocation import assert_relocation_snapshot
    assert_relocation_snapshot(source)
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
    epoch = parse_invalidation_epoch(source["history_epoch"])
    staging_path = _staging_path(codex_home, source_key, history_epoch=epoch,
                                 recovery_id=dict(source).get("recovery_id", ""))
    # One owned-home stat inventory supplies history candidates, separately from
    # the parse worklist.
    history_inventory = collect_session_file_inventory(
        session_dirs_for_home(codex_home),
        read_metadata=False,
    )
    ensure_private_directory(staging_path.parent)
    connection = sqlite3.connect(staging_path)
    ensure_private_file(staging_path)
    try:
        connection.row_factory = sqlite3.Row
        authority = bind_rebuild_authority(connection, source)
        schema = _ensure_schema(connection)
        staged_entry = _staged_entry(connection, entry)
        previous = checkpoint_progress(load_parser_checkpoint(connection, staged_entry.file_key, path))
        worklist = [staged_entry]
        outcome = refresh_files(
            connection,
            [entry.session_dir],
            worklist,
            rebuilt=schema.created or schema.reset,
            max_workers=1,
            max_parse_bytes=max_bytes,
            history_inventory=history_inventory,
        )
        staged_entry = worklist[0]
        checkpoint = load_parser_checkpoint(connection, staged_entry.file_key, path)
        captured = checkpoint.byte_offset if checkpoint is not None else 0
        successful = validate_staged_capture(connection, staged_entry, checkpoint, authority)
    finally:
        connection.close()
        ensure_private_sqlite_files(staging_path)

    complete = successful and checkpoint is not None and captured == entry.size_bytes
    advanced = checkpoint_advanced(previous, checkpoint_progress(checkpoint))
    if complete:
        _install_completed_rebuild(
            ledger_path,
            staging_path,
            entry,
            staged_entry,
            checkpoint,
            authority,
        )
        _remove_staging_files(staging_path)
    return RebuildSliceResult(
        source_key=source_key,
        outcome=(RebuildOutcome.COMPLETE if complete else
                 RebuildOutcome.PROGRESS if advanced else RebuildOutcome.BLOCKED),
        captured_bytes=captured,
        target_bytes=entry.size_bytes,
        bytes_read=outcome.stats.source_bytes_read,
        reason=RebuildReason.NO_PROGRESS if not complete and not advanced else RebuildReason.NONE,
    )


def rebuild_source_fingerprint(ledger_path, source_key):
    with open_ledger(ledger_path, read_only=True) as connection:
        row = load_rebuild_source(connection, source_key)
        observed = connection.execute("select size_bytes,mtime_ns from files where file_key=?", (source_key,)).fetchone()
    if row is None:
        return None
    import json
    return hashlib.sha256(json.dumps((dict(row), tuple(observed) if observed else None), sort_keys=True).encode()).hexdigest()


def _staged_entry(connection, entry):
    rows = connection.execute("select file_key from files where path=?", (str(entry.path),)).fetchall()
    if len(rows) > 1:
        raise RuntimeError("staged rebuild has ambiguous source ownership")
    if not rows:
        return entry
    key = str(rows[0]["file_key"])
    return replace(entry, file_key=key, file_key_is_fallback=key.startswith("codex-usage:fallback:path:"))


def _load_stale_source(ledger_path: Path, source_key: str) -> sqlite3.Row:
    with open_ledger(ledger_path, read_only=True) as connection:
        row = load_rebuild_source(connection, source_key)
    if row is None:
        raise ValueError(f"stale source is no longer available: {source_key}")
    return row


def _staging_path(codex_home: Path, source_key: str, *, history_epoch=0, recovery_id="") -> Path:
    digest = hashlib.sha256(source_key.encode()).hexdigest()
    suffix = f"-history-{history_epoch}" if history_epoch else ""
    if recovery_id:
        suffix += "-recovery-"+recovery_id
    return agent_data_dir(codex_home) / "rebuilds" / f"accounting-v2-{digest}{suffix}.sqlite3"


def _install_completed_rebuild(
    ledger_path: Path,
    staging_path: Path,
    entry: SessionFileInventoryEntry,
    staged_entry: SessionFileInventoryEntry,
    checkpoint,
    authority,
) -> None:
    before = entry.path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            entry.source_device, entry.source_inode, entry.size_bytes, entry.mtime_ns):
        raise OSError("source changed before the rebuilt checkpoint was verified")
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
                or str(current["path"]) != str(authority.get("captured_path", entry.path))
                or (not str(current["error"] or "").startswith(STALE_ERROR_PREFIX)
                    and not pending_invalidation(connection, entry.file_key))
            ):
                raise RuntimeError("stale source changed before rebuild commit")
            assert_live_rebuild_authority(connection, entry.file_key, authority)
            assert_attached_stage(connection, staged_entry, checkpoint)
            _check_identity_target(connection, entry.file_key, staged_entry.file_key)
            invalidate_dependents(connection, [entry.path, Path(authority.get("captured_path", entry.path))],
                                  exclude={entry.file_key, staged_entry.file_key})
            _mark_rebuilt_tasks_dirty(connection, staged_entry.file_key, entry.file_key)
            _replace_workset_rows(connection, entry.file_key, staged_entry.file_key)
            rekey_invalidation(connection, entry.file_key, staged_entry.file_key)
            complete_invalidation(connection, staged_entry.file_key)
            from codex_usage.session_cache_source_identity import record_physical_identity
            record_physical_identity(connection, checkpoint)
            # Byte-identical semantic repairs can retain the same row count.
            # Force a new normalized generation, not the append fast path.
            supersede_rebuilt_generations(connection, entry.file_key, staged_entry.file_key, checkpoint, authority)
            synchronize_parser_workset_in_transaction(connection)
            assert_installed_authority(connection, staged_entry, checkpoint)
            from codex_usage.history_upgrade_relocation import clear_relocation, assert_relocation_snapshot
            assert_relocation_snapshot(authority)
            clear_relocation(connection, entry.file_key)
            if _file_snapshot(entry.path.stat()) != _file_snapshot(before):
                raise OSError("source changed before rebuild commit")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.execute("detach database rebuild")
    from codex_usage.sqlite_activity import notify
    notify(ledger_path, "reclaim")


def _replace_workset_rows(
    connection: sqlite3.Connection,
    source_key: str,
    staged_key: str,
) -> None:
    for table in _WORKSET_TABLES:
        columns = _table_columns(connection, table)
        selected = ", ".join(columns)
        connection.execute(f"delete from {table} where file_key in (?, ?)", (source_key, staged_key))
        connection.execute(
            f"insert into {table} ({selected}) "
            f"select {selected} from rebuild.{table} where file_key = ?",
            (staged_key,),
        )
    file_columns = _table_columns(connection, "files")
    selected = ", ".join(file_columns)
    connection.execute("delete from files where file_key in (?, ?)", (source_key, staged_key))
    connection.execute(
        f"insert into files ({selected}) "
        f"select {selected} from rebuild.files where file_key = ?",
        (staged_key,),
    )


def _check_identity_target(connection, source_key, staged_key):
    if source_key == staged_key:
        return
    retained = connection.execute("""select 1 from ledger_generations g
        join ledger_sources s using(source_id)
        where s.source_key=? and g.status!='superseded' limit 1""", (staged_key,)).fetchone()
    if retained is not None:
        raise RuntimeError("rebuilt source identity target already has retained facts")
    target = connection.execute("select parsed_at from files where file_key=?", (staged_key,)).fetchone()
    if target is None:
        return
    populated = target["parsed_at"] or any(connection.execute(
        f"select 1 from {table} where file_key=? limit 1", (staged_key,)).fetchone()
        for table in _WORKSET_TABLES)
    if populated:
        raise RuntimeError("rebuilt source identity target already has retained facts")


def _table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(
        str(row["name"])
        for row in connection.execute(f"pragma main.table_info({table})")
    )


def _mark_rebuilt_tasks_dirty(
    connection: sqlite3.Connection,
    source_key: str,
    previous_key: str,
) -> None:
    task_ids = {
        str(row[0])
        for query in (
            "select session_id from rebuild.session_metadata where file_key = ?",
            "select distinct session_id from rebuild.usage_records where file_key = ?",
            "select distinct thread_id from rebuild.transition_candidates where file_key = ?",
            "select distinct task_id from rebuild.image_operations where file_key = ?",
            "select distinct root_task_id from rebuild.image_operations where file_key = ?",
        )
        for row in connection.execute(query, (source_key,))
        if row[0]
    }
    from codex_usage.session_cache_generations import affected_task_ids_for_file
    task_ids.update(affected_task_ids_for_file(connection, previous_key))
    connection.executemany(
        "insert or ignore into dirty_transition_tasks (thread_id) values (?)",
        ((task_id,) for task_id in sorted(task_ids)),
    )


def _file_snapshot(stat) -> tuple[int, int, int, int, int]:
    return (int(stat.st_dev), int(stat.st_ino), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _remove_staging_files(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
