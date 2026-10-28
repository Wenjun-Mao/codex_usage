"""Owned, no-wait physical WAL progress and event-driven reclamation."""
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
import shutil
import sqlite3
from time import perf_counter

from filelock import FileLock, Timeout

from codex_usage.agent_paths import agent_lock_path, AGENT_DATA_DIR_NAME, LEDGER_DATABASE_NAME
from codex_usage.agent_private_files import ensure_private_sqlite_files
from codex_usage.cache_refresh_lock import acquire_cache_refresh_lock
from codex_usage.ledger_writer_contract import admit_ledger_privacy_paths, validate_writer_contract
from codex_usage.sqlite_activity import idle
from codex_usage.sqlite_maintenance_lock import exclude_physical_maintenance
from codex_usage.sqlite_runtime import require_release_runtime
from codex_usage.sqlite_writer_admission import try_admit_sqlite_writer


PRESSURE_RESERVE = 512 * 1024**2  # Free-space signal, never a derived-data ceiling.


@dataclass
class CheckpointResult:
    outcome: str
    mode: str = "PASSIVE"
    busy: int | None = None
    log_frames: int | None = None
    checkpointed_frames: int | None = None
    wal_before: int = 0
    wal_after: int = 0
    main_growth_reservation: int = 0
    free_bytes: int | None = None
    seconds: float = 0.0

    def to_dict(self):
        return asdict(self)


def validate_owner(path, owner):
    expected = agent_lock_path(path.parent.parent)
    if (path.name != LEDGER_DATABASE_NAME or path.parent.name != AGENT_DATA_DIR_NAME
            or not isinstance(owner, FileLock) or not owner.is_locked
            or Path(owner.lock_file).resolve() != expected.resolve()):
        raise ValueError("Checkpoint requires the currently owned canonical home-agent lock")


def allocation(path):
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def reserve_checkpoint_growth(connection, path):
    page_size = connection.execute("pragma main.page_size").fetchone()[0]
    logical = connection.execute("pragma main.page_count").fetchone()[0] * page_size
    growth = max(0, logical - path.stat().st_size)
    free = shutil.disk_usage(path.parent).free
    return growth, free, free >= growth + 8 * page_size


def _progress(connection, result, mode):
    busy, frames, copied = connection.execute(f"pragma main.wal_checkpoint({mode})").fetchone()
    result.mode, result.busy = mode, busy
    result.log_frames, result.checkpointed_frames = frames, copied
    caught_up = frames >= 0 and copied >= 0 and frames == copied
    result.outcome = "complete" if not busy and caught_up else "partial" if not busy else "busy"
    return caught_up and not busy


def checkpoint(path, *, owner, reclaim=False, readers=()):
    """PASSIVE never owns the general writer lease through its I/O.

    TRUNCATE additionally claims SQLite's own cross-process exclusive lock and
    rechecks no-work frame telemetry, so a raced append is deferred rather than
    copied through a long exclusive writer hold.
    """
    started = perf_counter()
    result = CheckpointResult("deferred")
    path = admit_ledger_privacy_paths(Path(path))
    wal = path.with_name(path.name + "-wal")
    try:
        require_release_runtime()
        validate_owner(path, owner)
        result.wal_before = allocation(wal)
        if not wal.exists() or result.wal_before == 0:
            result.outcome = "absent"
            return result
        if not idle(path, readers=readers):
            return result
        with exclude_physical_maintenance(path):
            with try_admit_sqlite_writer(path) as admitted:
                if not admitted or not idle(path, readers=readers):
                    return result
                connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=0)
            with closing(connection):
                connection.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
                connection.execute("pragma busy_timeout=0")
                connection.execute("pragma synchronous=normal")
                validate_writer_contract(connection)
                if connection.execute("pragma journal_mode").fetchone()[0] != "wal":
                    result.outcome = "not_wal"
                    return result
                growth, free, fits = reserve_checkpoint_growth(connection, path)
                result.main_growth_reservation, result.free_bytes = growth, free
                if not fits:
                    result.outcome = "storage_pressure"
                    return result
                if not _progress(connection, result, "PASSIVE"):
                    return result
                if not (reclaim or free < PRESSURE_RESERVE):
                    return result
                if not idle(path):
                    result.outcome = "reclaim_deferred"
                    return result
                with acquire_cache_refresh_lock(path, timeout=0), try_admit_sqlite_writer(path) as admitted:
                    if not admitted or not idle(path):
                        result.outcome = "reclaim_deferred"
                        return result
                    # Unlike the Python lease, SQLite's exclusive connection
                    # fence also excludes old/uncoordinated process writers.
                    # The empty transaction claims the lock without appending
                    # source data; timeout=0 refuses to wait for external readers.
                    connection.execute("pragma main.locking_mode=exclusive")
                    connection.execute("begin exclusive")
                    connection.commit()
                    busy, frames, copied = connection.execute("pragma main.wal_checkpoint(NOOP)").fetchone()
                    if busy or frames < 0 or copied != frames:
                        result.mode, result.busy = "NOOP", busy
                        result.log_frames, result.checkpointed_frames = frames, copied
                        result.outcome = "reclaim_deferred"
                        return result
                    _progress(connection, result, "TRUNCATE")
                    if result.outcome == "complete":
                        result.outcome = "reclaimed"
        return result
    except Timeout:
        result.outcome = "busy"
        return result
    except sqlite3.OperationalError as error:
        if getattr(error, "sqlite_errorcode", None) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise
        result.outcome = "busy"
        return result
    finally:
        result.wal_after = allocation(wal)
        result.seconds = perf_counter() - started
        ensure_private_sqlite_files(path)
