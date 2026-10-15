from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock


def cache_refresh_lock_path(cache_database_path: Path) -> Path:
    """Return the separate cross-process lock path for one cache database."""
    return cache_database_path.with_name(
        f".{cache_database_path.name}.refresh.lock"
    )


def validate_owned_cache_refresh_lock(
    cache_database_path: Path,
    owned_cache_refresh_lock: FileLock,
) -> None:
    """Require an explicitly borrowed lock held for this database's refresh path."""
    if not isinstance(owned_cache_refresh_lock, FileLock) or not owned_cache_refresh_lock.is_locked:
        raise ValueError("borrowed cache refresh lock must be a currently held FileLock")
    try:
        expected = cache_refresh_lock_path(cache_database_path).resolve()
        actual = Path(owned_cache_refresh_lock.lock_file).resolve()
    except (OSError, RuntimeError) as error:
        raise ValueError("borrowed cache refresh lock must match this database") from error
    if actual != expected:
        raise ValueError("borrowed cache refresh lock must match this database")


@contextmanager
def acquire_cache_refresh_lock(
    cache_database_path: Path,
    *,
    owned_cache_refresh_lock: FileLock | None = None,
    timeout: float = -1,
) -> Iterator[None]:
    """Serialize complete cache refreshes without locking the SQLite database file."""
    if owned_cache_refresh_lock is not None:
        validate_owned_cache_refresh_lock(cache_database_path, owned_cache_refresh_lock)
        yield
        return
    lock = FileLock(cache_refresh_lock_path(cache_database_path))
    with lock.acquire(timeout=timeout):
        yield
