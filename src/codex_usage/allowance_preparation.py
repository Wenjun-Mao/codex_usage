"""Snapshot-pinned quota preparation with independently tracked immutable reuse."""
from functools import cached_property
from types import MappingProxyType

from codex_usage.allowance_pace_evidence import PreparedPaceEvidence
from codex_usage.allowance_pace_inputs import PaceInputs
from codex_usage import allowance_prepared_cache as cache


class AllowancePreparation:
    """Share raw/pace facts only; dictionaries and histories remain request-local."""

    def __init__(self, connection, *, reuse_history=True):
        self.connection = connection
        self.reuse_history = reuse_history
        self._key = cache.identity(connection)
        self._raw, self._series = cache.load(self._key)
        self._prepared_keys = set(self._series)

    @cached_property
    def raw(self):
        from codex_usage.allowance_queries import load_quota_evidence
        if self._raw is not None:
            return self._raw
        points, provenance, live = load_quota_evidence(self.connection)
        result = (tuple(points), MappingProxyType({p: frozenset(v) for p, v in provenance.items()}),
                  frozenset(live))
        cache.store(self._key, result, self._series)
        return result

    def pace(self, series_keys):
        points, _, live = self.raw
        missing = series_keys - self._prepared_keys
        if missing:
            # All raw durations remain available for limit-wide plan continuity.
            prepared = self._pace_inputs.prepare(live, series_keys=missing)
            self._series.update(prepared.series)
            self._prepared_keys.update(missing)
            cache.store(self._key, self.raw, self._series)
        return PreparedPaceEvidence(
            MappingProxyType({k: v for k, v in self._series.items() if k in series_keys}), live)

    @cached_property
    def _pace_inputs(self):
        return PaceInputs(self.raw[0], cache=self.history_cache if self.reuse_history else None)

    @cached_property
    def captures(self):
        from codex_usage.allowance_captures import CaptureDirectory
        return CaptureDirectory(*self.raw[:2])

    @cached_property
    def history_cache(self):
        from codex_usage.history_preparation_cache import HistoryPreparationCache
        return HistoryPreparationCache(self.connection)
