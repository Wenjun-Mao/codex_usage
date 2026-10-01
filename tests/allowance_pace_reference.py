"""Frozen full-prefix oracle for prepared-index regression tests only."""
from dataclasses import dataclass, replace
from itertools import groupby
from math import exp, isfinite, log

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_windows import _identity_plans, seconds


@dataclass(slots=True)
class Continuity:
    previous: QuotaObservation | None = None
    reset: int | None = None
    reset_seen: float | None = None
    credits: int | None = None

    def push(self, point, group):
        reset = next((p.resets_at for p in reversed(group) if p.resets_at is not None), None)
        credits = next((p.reset_credits for p in reversed(group) if p.reset_credits is not None), None)
        crossed = self.reset is not None and self.reset_seen < self.reset <= seconds(point)
        advanced = self.reset is not None and reset is not None and reset > self.reset + 60
        credit_drop = self.credits is not None and credits is not None and credits < self.credits
        rebase = self.reset is not None and reset is not None and abs(reset - self.reset) > 60
        reason = ("scheduled reset" if crossed and advanced else
                  "reset credit decrease" if credit_drop else
                  "deadline rebase" if rebase else
                  "unknown boundary" if self.previous and self.previous.used_percent - point.used_percent >= 5 else "")
        if reason:
            self.reset = self.reset_seen = self.credits = None
        if reset is not None:
            self.reset, self.reset_seen = reset, seconds(point)
        if credits is not None:
            self.credits = credits
        self.previous = point
        return reason


def active_evidence(points, anchor, live_points):
    """Cut off future evidence before identity resolution or boundary checks."""
    plan_events = sorted({(seconds(p), p.plan) for p in points
                          if p.limit_id == anchor.limit_id and p.plan and seconds(p) <= seconds(anchor)})
    prefix = sorted(dict.fromkeys(p for p in points
                    if p.limit_id == anchor.limit_id and p.duration_minutes == anchor.duration_minutes
                    and seconds(p) <= seconds(anchor)), key=lambda p: (seconds(p), p.slot))
    canonical, metadata, cuts = [], [], set()
    pending_cut = False
    conflicts = 0
    for stamp, grouped in groupby(prefix, seconds):
        group = list(grouped)
        resets = [p.resets_at for p in group if p.resets_at is not None]
        conflict = (len({p.used_percent for p in group}) > 1
                    or len({p.plan for p in group if p.plan}) > 1
                    or len({p.reset_credits for p in group if p.reset_credits is not None}) > 1
                    or bool(resets and max(resets) - min(resets) > 60))
        if conflict:
            conflicts += 1
            if stamp == seconds(anchor):
                return [], "live anchor conflict", conflicts
            pending_cut = True
            continue
        chosen = anchor if anchor in group else next((p for p in reversed(group) if p.plan), group[-1])
        if pending_cut:
            cuts.add(len(canonical))
            pending_cut = False
        canonical.append(chosen)
        metadata.append(group)
    if anchor not in live_points or not canonical or canonical[-1] != anchor:
        return [], "exact live anchor missing", conflicts
    plans = _identity_plans([replace(p, plan=next((q.plan for q in group if q.plan), p.plan))
                             for p, group in zip(canonical, metadata)])
    continuity = Continuity()
    start, boundary = 0, "left censored"
    plan_cursor = 0
    for index, point in enumerate(canonical):
        reason = ("observation conflict" if index in cuts else
                  "plan change" if index and plans[index] != plans[index - 1] else "")
        # Plan transitions belong to the limit, even when the transport only
        # reported its other duration bucket between this bucket's samples.
        while plan_cursor < len(plan_events) and plan_events[plan_cursor][0] <= seconds(point):
            stamp, plan = plan_events[plan_cursor]
            if index and stamp > seconds(canonical[index - 1]) and plan != plans[index - 1]:
                reason = "plan change"
            plan_cursor += 1
        if reason:
            continuity = Continuity()
        detected = continuity.push(point, metadata[index])
        reason = reason or detected
        if reason:
            start, boundary = index, reason
    return canonical[start:], boundary, conflicts


def fit_paces(points, anchor, live_points):
    """Serialize disposable rates and projections, without a rendering clock."""
    suffix, boundary, conflicts = active_evidence(points, anchor, live_points)
    results = []
    for name, horizon, count, span, gap in (("Recent", 3600, 3, 1800, 1800),
                                           ("Daily", 86400, 5, 10800, 10800)):
        sample = [p for p in suffix if seconds(p) >= seconds(anchor) - horizon]
        times = [seconds(p) for p in sample]
        coverage = times[-1] - times[0] if times else 0
        movement = sample[-1].used_percent - sample[0].used_percent if sample else 0
        gaps = [b - a for a, b in zip(times, times[1:])]
        reason = (boundary if not sample else "too few observations" if len(sample) < count else
                  "short observed span" if coverage < span else
                  "observation gap" if max(gaps, default=0) > gap else
                  "insufficient signed movement" if movement < 2 else "")
        rate = None
        if not reason:
            if name == "Recent":
                rate = movement / (coverage / 3600)
            else:
                decay = log(2) / (6 * 3600)
                weights = [(exp(decay * (b - times[-1])) - exp(decay * (a - times[-1]))) / decay
                           for a, b in zip(times, times[1:])]
                rates = [(b.used_percent - a.used_percent) / (elapsed / 3600)
                         for a, b, elapsed in zip(sample, sample[1:], gaps)]
                rate = sum(w * r for w, r in zip(weights, rates)) / sum(weights)
            if not isfinite(rate) or rate <= 0:
                rate, reason = None, "nonpositive rate"
        exhaustion = seconds(anchor) + (100 - anchor.used_percent) / rate * 3600 if rate else None
        reset_balance = (100 - anchor.used_percent - rate * (anchor.resets_at - seconds(anchor)) / 3600
                         if rate and anchor.resets_at is not None else None)
        results.append({"limit_id": anchor.limit_id, "duration_minutes": anchor.duration_minutes,
                        "name": name, "horizon_seconds": horizon, "span_seconds": coverage,
                        "observations": len(sample), "movement": movement, "rate": rate,
                        "gap_seconds": max(gaps, default=0), "reason": reason,
                        "boundary": boundary, "conflicts": conflicts,
                        "corrections": sum(b.used_percent < a.used_percent for a, b in zip(sample, sample[1:])),
                        "anchor": seconds(anchor), "reset": anchor.resets_at,
                        "used": anchor.used_percent, "exhaustion": exhaustion,
                        "reset_balance": reset_balance})
    return results
