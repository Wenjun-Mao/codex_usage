"""Calibrated pace from shared trusted cost prefixes and causal references.

This conversion estimates local included consumption, not account entitlement.
No pricing, history loading, or monetary fitting occurs in the per-row queries.
"""
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from codex_usage.allowance_windows import seconds


def timestamp(value):
    return datetime.fromisoformat(value).timestamp()


@dataclass(frozen=True, slots=True)
class CostPrefix:
    times: list
    costs: list
    unpriced: list

    def period(self, start, end):
        left, right = bisect_right(self.times, start), bisect_right(self.times, end)
        return self.costs[right] - self.costs[left], self.unpriced[right] - self.unpriced[left]


class PaceReferences:
    """Index already fitted windows once; select only capture-available evidence."""
    def __init__(self, windows):
        from codex_usage.allowance_queries import _has_valid_priced_estimate, _series_key
        self.latest = {}
        self.usable = {}
        for window in windows:
            key = _series_key(window)
            self.latest.setdefault(key, []).append(window)
            if _has_valid_priced_estimate(window):
                self.usable.setdefault(key, []).append(window)
        self.ends = {key: [timestamp(w["end"]) for w in values] for key, values in self.usable.items()}
        self.latest_ends = {key: [timestamp(w["end"]) for w in values] for key, values in self.latest.items()}

    def select(self, anchor, plan):
        if not plan or not anchor.duration_minutes:
            return None
        key = (anchor.limit_id, plan, anchor.duration_minutes)
        position = bisect_right(self.ends.get(key, ()), seconds(anchor)) - 1
        if position < 0:
            return None
        window = self.usable[key][position]
        latest_position = bisect_right(self.latest_ends[key], seconds(anchor)) - 1
        return {"value": window["estimate"]["value"], "start": window["start"],
                "end": window.get("fit_end") or window["end"],
                "available_at": window["end"], "plan": plan,
                "confidence": window["estimate"]["confidence"],
                "previous": window is not self.latest[key][latest_position]}


def calibrated_paces(prepared, anchor, direct, prefix, references, *, coverage_complete):
    """Choose one reference for all periods; retain eligible meter fallbacks."""
    evidence = prepared.cycle(anchor)
    reference = references.select(anchor, anchor.plan or evidence.plan)
    common_reason = (evidence.boundary if evidence.first is None else
                     "reported-full cost cutoff" if evidence.reported_full_at is not None else
                     "incomplete local coverage" if not coverage_complete else
                     "no compatible priced reference" if reference is None else "")
    result = []
    for pace in direct:
        row = dict(pace, method="direct meter", reference=reference, cost=None,
                   coverage_complete=coverage_complete, calibrated_reason=common_reason)
        # These spans come from the exact causal suffix, not nominal reset clocks.
        start = pace["anchor"] - pace["span_seconds"]
        row["observed_start"] = (datetime.fromtimestamp(start, datetime.fromisoformat(anchor.timestamp).tzinfo).isoformat()
                                 if evidence.first is not None else None)
        cost, unpriced = prefix.period(start, pace["anchor"])
        reason = common_reason or ("no observed elapsed time" if pace["span_seconds"] <= 0 else
                                   "unpriced period usage" if unpriced else
                                   "invalid period cost" if not isfinite(cost) or cost < 0 else "")
        row["calibrated_reason"] = reason
        row["unpriced_tokens"] = unpriced
        if not reason:
            rate = 100 * cost / reference["value"] / (pace["span_seconds"] / 3600)
            if isfinite(rate):
                row.update(method="calibrated cost", cost=cost, rate=rate, reason="",
                           exhaustion=pace["anchor"] + (100 - pace["used"]) / rate * 3600 if rate > 0 else None,
                           reset_balance=(100 - pace["used"] - rate * (pace["reset"] - pace["anchor"]) / 3600
                                          if pace["reset"] is not None else None))
            else:
                row["calibrated_reason"] = "invalid calibrated rate"
        # Explain the cost failure when neither method can supply a rate.
        if row["rate"] is None:
            row["reason"] = row["calibrated_reason"] + "; direct meter: " + pace["reason"]
        result.append(row)
    return result
