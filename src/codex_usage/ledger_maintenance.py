"""Quiescent schema/repair admission; never stops an existing collector."""
from contextlib import contextmanager
from pathlib import Path
from filelock import FileLock, Timeout

from codex_usage.agent_paths import AGENT_DATA_DIR_NAME, LEDGER_DATABASE_NAME, agent_lock_path
from codex_usage.cache_refresh_lock import acquire_cache_refresh_lock


class LedgerMaintenanceBusyError(RuntimeError):
    """Another collector or parser owns the state needed for maintenance."""


@contextmanager
def acquire_ledger_maintenance(
    path: Path,
    *,
    owned_agent_lock=None,
    owned_cache_refresh_lock=None,
):
    path = path.expanduser().absolute()
    if path.is_symlink() or path.parent.is_symlink():
        raise LedgerMaintenanceBusyError("ledger maintenance requires a canonical nonsymlink database path")
    path = path.resolve(strict=True)
    managed = path.name == LEDGER_DATABASE_NAME and path.parent.name == AGENT_DATA_DIR_NAME
    expected_agent = agent_lock_path(path.parent.parent) if managed else None
    acquired = []
    try:
        if owned_agent_lock is not None:
            if (not isinstance(owned_agent_lock, FileLock) or expected_agent is None or not owned_agent_lock.is_locked
                    or Path(owned_agent_lock.lock_file).resolve() != expected_agent.resolve()):
                raise LedgerMaintenanceBusyError("maintenance requires the owned home-agent lock")
        elif expected_agent is not None:
            lock = FileLock(expected_agent)
            lock.acquire(timeout=0)
            acquired.append(lock)
        with acquire_cache_refresh_lock(
            path,
            owned_cache_refresh_lock=owned_cache_refresh_lock,
            timeout=0,
        ):
            yield
    except Timeout as error:
        raise LedgerMaintenanceBusyError("ledger maintenance requires a stopped collector and idle parser") from error
    finally:
        for lock in reversed(acquired):
            lock.release()
