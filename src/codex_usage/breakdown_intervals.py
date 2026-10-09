"""Calendar [start,end) versus capture-causal (origin,capture] intervals."""
from dataclasses import dataclass

from codex_usage.aggregation import RangeBounds


@dataclass(frozen=True, slots=True)
class BreakdownInterval:
    start: float
    end: float
    causal: bool = False

    def contains(self, at):
        return self.start < at <= self.end if self.causal else self.start <= at < self.end

    @property
    def sql_bounds(self):
        # Ledger timestamps are integer microseconds. Inclusion padding belongs
        # only to SQL, never to the evidence endpoints or displayed time axis.
        offset = int(self.causal)
        return RangeBounds(round(self.start * 1e6) + offset, round(self.end * 1e6) + offset)

    def occurrence_time(self, at):
        # A capture exactly at an hour/day boundary closes the preceding bin.
        return at - .000001 if self.causal else at

    def clip(self, start, end):
        return BreakdownInterval(max(self.start, start), min(self.end, end), self.causal)

    @property
    def notation(self):
        return "(origin, capture]" if self.causal else "[start, end)"
