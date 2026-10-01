"""Pure, capture-anchored quota pace; independent of monetary segmentation.

Raw metadata is retained for continuity, never used to repair the live endpoint.
Callers supply evidence already available in their ledger snapshot. Historical
replay must additionally enforce first availability before calling this module.
"""
from math import exp, isfinite, log

from codex_usage.allowance_pace_evidence import PreparedPaceEvidence
from codex_usage.allowance_windows import seconds


def active_evidence(prepared, anchor):
    """Select the actual bounded suffix from an already prepared causal index."""
    if not isinstance(prepared, PreparedPaceEvidence):
        raise TypeError("pace fitting requires prepared evidence")
    return prepared.select(anchor)


def fit_paces(prepared, anchor):
    """Serialize disposable rates and projections, without a rendering clock."""
    suffix, boundary, conflicts = active_evidence(prepared, anchor)
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


def pace_state(pace, probe_status, now):
    """Presentation expiry is reevaluated without refitting or moving predictions."""
    if probe_status not in {"fresh", "partial"} or now >= pace["anchor"] + 1800:
        return "awaiting"
    if pace["reset"] is not None and now >= pace["reset"]:
        return "awaiting"
    if pace["used"] == 100:
        return "reported full"
    if pace["rate"] is None:
        return "unmeasurable"
    if pace["reset"] is None:
        return "missing reset"
    if pace["exhaustion"] <= pace["reset"] and now >= pace["exhaustion"]:
        return "awaiting"
    return "ready"


def presentation_identity(report, now):
    return [[pace_state(p, report["status"]["probe_status"], now) for p in row]
            for row in report.get("paces", [])]
