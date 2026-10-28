"""Operation lifetime notifications for one agent-owned ledger's idle work."""
from contextlib import contextmanager
import logging
from pathlib import Path
import threading


_lock = threading.Lock()
_active: dict[Path, dict[object, bool]] = {}
_listeners: dict[Path, object] = {}


def subscribe(path, listener):
    key = Path(path).resolve()
    with _lock:
        if key in _listeners:
            raise RuntimeError("Ledger already has an idle-maintenance owner")
        _listeners[key] = listener

    def unsubscribe():
        with _lock:
            if _listeners.get(key) is listener:
                del _listeners[key]
    return unsubscribe


def idle(path, *, readers=()):
    """Exclude only exact live read activities explicitly owned by the caller."""
    with _lock:
        active = _active.get(Path(path).resolve(), {})
        return (all(active.get(token) is True for token in readers)
                and not active.keys()-set(readers))


def notify(path, event):
    with _lock:
        listener = _listeners.get(Path(path).resolve())
    if listener is not None:
        try:
            listener(event)
        except Exception:
            logging.getLogger(__name__).exception("Idle-maintenance notification failed")


@contextmanager
def operation(path, *, read_only):
    key = Path(path).resolve()
    token = object()
    with _lock:
        _active.setdefault(key, {})[token] = read_only
    try:
        yield token
    finally:
        with _lock:
            del _active[key][token]
            if not _active[key]:
                del _active[key]
        notify(key, "reader_release" if read_only else "write")
