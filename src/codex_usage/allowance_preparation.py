"""Request-local quota preparation pinned to the caller's read snapshot."""
from functools import cached_property
from types import MappingProxyType

from codex_usage.allowance_pace_evidence import PreparedPaceEvidence, prepare_pace_evidence


class AllowancePreparation:
    """Share raw evidence and identical series, never across requests/revisions."""

    def __init__(self, connection):
        self.connection = connection
        self._series = {}
        self._prepared_keys = set()

    @cached_property
    def raw(self):
        from codex_usage.allowance_queries import load_quota_evidence
        points, provenance, live = load_quota_evidence(self.connection)
        return (tuple(points), MappingProxyType({p: frozenset(v) for p, v in provenance.items()}),
                frozenset(live))

    def pace(self, series_keys):
        points, _, live = self.raw
        missing = series_keys - self._prepared_keys
        if missing:
            # All raw durations remain available for limit-wide plan continuity.
            prepared = prepare_pace_evidence(points, live, series_keys=missing)
            self._series.update(prepared.series)
            self._prepared_keys.update(missing)
        return PreparedPaceEvidence(
            MappingProxyType({k: v for k, v in self._series.items() if k in series_keys}), live)
