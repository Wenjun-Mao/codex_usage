"""One bounded immutable quota preparation, never a connection or mutable report."""
from pathlib import Path
from threading import RLock

from codex_usage.dashboard_preparation_tracking import token

# Large raw/pace graphs cost every subsequent GC, including unrelated exports.
# Keep this optional memo small; persistent report and fit caches serve history.
MAX_POINTS = 50_000
_lock = RLock()
_key = None
_raw = None
_series = {}


def identity(connection):
    from codex_usage.ledger_schema import ReadOnlyLedgerConnection
    # A rolled-back writable transaction can later reuse the same generation
    # for different evidence. Only pinned, mode=ro handles may publish memo data.
    if not isinstance(connection, ReadOnlyLedgerConnection) or not connection.in_transaction:
        return None
    dependency = token(connection)
    if dependency is None:
        return None
    path = next((row[2] for row in connection.execute("pragma database_list") if row[1] == "main"), "")
    if not path:
        return None
    stat = Path(path).stat()
    return (str(Path(path).resolve()), stat.st_dev, stat.st_ino, dependency[0], dependency[2])


def load(key):
    with _lock:
        return (_raw, dict(_series)) if key is not None and key == _key else (None, {})


def store(key, raw, series):
    global _key, _raw, _series
    if key is None:
        return
    with _lock:
        if len(raw[0]) > MAX_POINTS:
            _key, _raw, _series = None, None, {}
        elif key == _key:
            _series.update(series)
        else:
            _key, _raw, _series = key, raw, dict(series)


def clear():
    global _key, _raw, _series
    with _lock:
        _key, _raw, _series = None, None, {}
