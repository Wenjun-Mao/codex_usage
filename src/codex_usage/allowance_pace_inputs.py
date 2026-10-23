"""Request-local series inputs; all durations retain their plan-event authority."""
from codex_usage.allowance_windows import seconds


class PaceInputs:
    def __init__(self, points, *, cache=None):
        self.cache = cache
        self.grouped, events = {}, {}
        for point in points:
            key = point.limit_id, point.duration_minutes
            self.grouped.setdefault(key, []).append(point)
            if point.plan:
                events.setdefault(point.limit_id, set()).add((seconds(point), point.plan))
        self.events = {key: sorted(value) for key, value in events.items()}

    def prepare(self, live_points, series_keys=None):
        from codex_usage.allowance_pace_evidence import PreparedPaceEvidence, Series
        keys = self.grouped.keys() if series_keys is None else series_keys
        return PreparedPaceEvidence({key: Series.prepare(self.grouped[key], self.events.get(key[0], ()), cache=self.cache)
            for key in keys if key in self.grouped}, frozenset(live_points))
