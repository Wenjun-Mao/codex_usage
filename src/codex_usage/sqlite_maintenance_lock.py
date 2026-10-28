"""Cross-process exclusion between checkpoints and destructive maintenance."""
from contextlib import contextmanager
import threading
from filelock import FileLock

from codex_usage.agent_private_files import ensure_private_file
from codex_usage.ledger_writer_contract import admit_ledger_privacy_paths


_registry_lock = threading.Lock()
_locks = {}


@contextmanager
def exclude_physical_maintenance(path):
    path = admit_ledger_privacy_paths(path)
    lock_path = path.with_name(f".{path.name}.maintenance.lock")
    if lock_path.is_symlink():
        raise ValueError("Physical maintenance lock cannot be a symlink")
    with _registry_lock:
        entry = _locks.setdefault(lock_path, [FileLock(lock_path), 0])
        entry[1] += 1
    try:
        # FileLock's thread-local context makes nested maintenance reentrant on
        # its owning thread, while another thread/process still fails admission.
        with entry[0].acquire(timeout=0):
            ensure_private_file(lock_path)
            yield
    finally:
        with _registry_lock:
            entry[1] -= 1
            if not entry[1]:
                del _locks[lock_path]
