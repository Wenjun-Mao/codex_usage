"""Reuse window calculations under transactional source invalidation."""
import hashlib
import json

from codex_usage.allowance_window_tracking import ensure_tracking

WINDOW_CACHE_REVISION = 3


class WindowCalculationCache:
    """Owned by the same guarded writer transaction as the account report.

    Segmentation and ordered cost prefixes remain authoritative. Never infer
    immutability from a window's age, closure, timestamp or source generation.
    """

    def __init__(self, connection, pricing_revision, report_revision, coverage_complete):
        self.connection = connection
        self.contract = (WINDOW_CACHE_REVISION, pricing_revision, report_revision, coverage_complete)
        self.loaded = {}
        ensure_tracking(connection)
        self.dirty = {row[0]: (row[1], row[2]) for row in connection.execute(
            "select kind, start, end from allowance_window_dirty")}
        self.generation = connection.execute(
            "select coalesce(max(last_used), 0) + 1 from allowance_window_cache").fetchone()[0]

    def result(self, window, scope, build):
        state = tuple(getattr(window, field) for field in window.__dataclass_fields__ if field != "points")
        # Fresh segmentation supplies all boundary/identity decisions. Source
        # tracking covers interior changes without hashing every observation.
        inputs = (scope, state, len(window.points), window.points[0].to_dict(), window.points[-1].to_dict())
        key = hashlib.sha256(json.dumps((self.contract, inputs),
            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        if key not in self.loaded:
            row = self.connection.execute("select report_json, start, end from allowance_window_cache where cache_key=?", (key,)).fetchone()
            if row is not None and not self._affected(row[1], row[2]):
                self.loaded[key] = json.loads(row[0])
            else:
                result, start, end = build()
                self.connection.execute("insert or replace into allowance_window_cache values (?,?,?,?,?)",
                    (key, json.dumps(result), start, end, self.generation))
                self.loaded[key] = result
        return self.loaded[key]

    def _affected(self, start, end):
        usage, quota = self.dirty.get("usage"), self.dirty.get("quota")
        # A changed earlier prefix can alter floating-point cancellation even
        # when the event lies before this window's first observation.
        return ((usage is not None and usage[0] <= end)
                or (quota is not None and quota[0] <= end and quota[1] >= start))

    def finish(self):
        # Keep only this build's full-history and capture-causal windows, not
        # every evolving version of an active window or old pricing contract.
        self.connection.executemany("update allowance_window_cache set last_used=? where cache_key=?",
            [(self.generation, key) for key in self.loaded])
        self.connection.execute("delete from allowance_window_cache where last_used != ?", (self.generation,))
        self.connection.execute("delete from allowance_window_dirty")
