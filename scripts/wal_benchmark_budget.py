"""The existing SQLite inventory guard, scoped to an owned WAL fixture."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import sqlite3
import stat
from time import monotonic, perf_counter
from unittest.mock import patch

from collector_benchmark_guard import database_path


SQL_RESERVE = 128 * 1024**2
WORK_RESERVE = 512 * 1024**2
TOTAL = 6 * 1024**3  # Experiment inventory only, never installed data retention.


def size(root):
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file())


def unlinked_bytes():
    directory = next((p for p in (Path('/proc/self/fd'), Path('/dev/fd')) if p.is_dir()), None)
    if directory is None:
        raise RuntimeError('WAL fixture requires process descriptor inventory')
    files = {}
    for name in os.listdir(directory):
        if not name.isdigit():
            continue
        try:
            value = os.fstat(int(name))
        except OSError:
            continue
        if stat.S_ISREG(value.st_mode) and value.st_nlink == 0:
            key = value.st_dev, value.st_ino
            files[key] = max(files.get(key, 0), value.st_size, value.st_blocks * 512)
    return sum(files.values())


class Budget:
    def __init__(self, root, snapshot):
        self.root, self.snapshot = root.resolve(), snapshot.resolve()
        if not self.snapshot.is_relative_to(self.root):
            raise ValueError('WAL fixture ledger must belong to its owned root')
        self.high_water = self.unlinked_high_water = self.guard_checks = 0
        self.guard_seconds = 0.0
        self.last = 0.0

    def check(self, reserve=0, *, unlinked=False):
        extra = unlinked_bytes() if unlinked else 0
        self.unlinked_high_water = max(self.unlinked_high_water, extra)
        used = size(self.root) + extra
        self.high_water = max(self.high_water, used)
        if used + reserve > TOTAL or shutil.disk_usage(self.root).free < reserve + SQL_RESERVE:
            raise ValueError('WAL fixture exceeds experiment inventory/headroom')
        return used

    def observation(self):
        return {'inventory_guard_checks': self.guard_checks,
                'inventory_guard_seconds': self.guard_seconds,
                'total_inventory_limit_bytes': TOTAL,
                'unlinked_temporary_high_water_bytes': self.unlinked_high_water,
                'inventory_guard_scope': 'all owned fixture files and unlinked temporary files'}

    @contextmanager
    def observe_sqlite(self, *, writable_root):
        if writable_root.resolve() != self.root:
            raise ValueError('WAL fixture must use its complete owned writable root')
        self.check(SQL_RESERVE + WORK_RESERVE, unlinked=True)
        original = sqlite3.connect
        guard_error = None

        def progress():
            nonlocal guard_error
            if monotonic() - self.last > .05:
                started = perf_counter()
                try:
                    self.check(SQL_RESERVE + WORK_RESERVE, unlinked=True)
                except ValueError as error:
                    guard_error = error
                    return 1
                finally:
                    self.guard_checks += 1
                    self.guard_seconds += perf_counter() - started
                    self.last = monotonic()
            return 0

        def authorize(action, first, second, database, trigger):
            if action == sqlite3.SQLITE_ATTACH and first != ':memory:':
                if not database_path(first).is_relative_to(self.root):
                    return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_PRAGMA and first.lower() == 'temp_store_directory' and second:
                if not Path(second).resolve().is_relative_to(self.root):
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        def connect(*args, **kwargs):
            connection = original(*args, **kwargs)
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, SQL_RESERVE)
            connection.set_authorizer(authorize)
            connection.set_progress_handler(progress, 10000)
            return connection

        with patch.object(sqlite3, 'connect', connect):
            try:
                yield self
            finally:
                self.check(unlinked=True)
                if guard_error is not None:
                    raise guard_error
