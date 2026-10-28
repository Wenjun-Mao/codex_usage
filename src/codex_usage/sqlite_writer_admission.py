"""Serialize owned writable connections; SQLite readers remain concurrent."""
from contextlib import contextmanager
from pathlib import Path
import threading


class _Admission:
    def __init__(self):
        self.lock = threading.RLock()
        self.users = 0


_registry_lock = threading.Lock()
_writers: dict[Path, _Admission] = {}


@contextmanager
def admit_sqlite_writer(path: Path):
    """Wait before opening SQLite, not inside its finite busy timeout.

    The agent owns one managed-ledger process, but report requests and capture
    execute on different threads. Parser and normalized ledger connections must
    share this boundary. Cross-process maintenance fencing remains independent.
    """
    with _admit(path, blocking=True):
        yield


@contextmanager
def try_admit_sqlite_writer(path: Path):
    """Try maintenance admission without queuing behind a capture writer."""
    with _admit(path, blocking=False) as acquired:
        yield acquired


@contextmanager
def _admit(path: Path, *, blocking: bool):
    key = path.expanduser().resolve()
    with _registry_lock:
        admission = _writers.get(key)
        if admission is None:
            admission = _writers[key] = _Admission()
        admission.users += 1
    acquired = False
    try:
        acquired = admission.lock.acquire(blocking=blocking)
        yield acquired
    finally:
        if acquired:
            admission.lock.release()
        with _registry_lock:
            admission.users -= 1
            if not admission.users:
                del _writers[key]
