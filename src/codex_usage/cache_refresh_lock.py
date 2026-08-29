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


@contextmanager
def acquire_cache_refresh_lock(cache_database_path: Path) -> Iterator[None]:
    """Serialize complete cache refreshes without locking the SQLite database file."""
    lock = FileLock(cache_refresh_lock_path(cache_database_path))
    with lock.acquire(timeout=-1):
        yield
