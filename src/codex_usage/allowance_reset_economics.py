"""One reconciled account-wide economic summary per detected reset period."""
from bisect import bisect_left
from math import nextafter, inf

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_reset_periods import reset_periods
from codex_usage.parser import parse_timestamp


def _cost(prefix, start, end):
    left, right = bisect_left(prefix.times, start), bisect_left(prefix.times, max(start, end))
    return prefix.costs[right]-prefix.costs[left], prefix.unpriced[right]-prefix.unpriced[left]


def reset_history(history, live_points, anchors, windows, prefix, *, coverage_complete):
    """Reuse raw captures, unchanged fits and the existing valued-event prefix.

    Period dollars are additive usage, never a fitted capacity or a sum of
    overlapping fits. Adjacent periods use half-open boundaries; uncertain
    reset intervals retain independent minimum/maximum cost bounds.
    """
    captures = history.get("captures", [])
    if not captures:
        return dict(captures=captures, periods=[], uncertain=[],
                    cross_boundary_fit_indices=list(range(len(windows))), kind="reset-period-economics-v1")
    through = prefix.times[-1] if prefix.times else None
    periods, owners = reset_periods(captures, live_points, anchors, through=through)
    uncertain = []
    for fragment in history.get("periods", [])+history.get("uncertain", []):
        remaining = [i for i in fragment["capture_indices"] if i not in owners]
        if remaining:
            group = dict(fragment, capture_indices=remaining, fit_indices=[], current=False, uncertain=True)
            uncertain.append(group)
            for index in remaining:
                owners[index] = group
    keys = tuple(QuotaObservation.__dataclass_fields__)
    positions = {tuple(p[key] for key in keys): i for i, p in enumerate(captures)}
    cross = []
    for index, window in enumerate(windows):
        found = {id(owners[positions[tuple(p[key] for key in keys)]]):
                 owners[positions[tuple(p[key] for key in keys)]] for p in window["points"]}
        if len(found) == 1:
            next(iter(found.values()))["fit_indices"].append(index)
        else:
            cross.append(index)
    from codex_usage.allowance_queries import _has_valid_priced_estimate
    for period in periods:
        start, end = period["start"], period["end"]
        closing = period["reset_closure"] or period["identity_closure"]
        if not closing:
            end = nextafter(end, inf)
        opening = period["reset_opening"] or period["identity_opening"]
        lower_start = opening["earliest"] if opening else start
        lower_end = closing["earliest"] if closing else end
        cost, unknown = _cost(prefix, start, end)
        minimum, unknown_min = _cost(prefix, start, lower_end)
        maximum, unknown_max = _cost(prefix, lower_start, end)
        candidates = [i for i in period["fit_indices"] if _has_valid_priced_estimate(windows[i])
                      and windows[i]["limit_id"] == period["limit_id"]
                      and windows[i]["duration_minutes"] == period["duration_minutes"]
                      and windows[i]["plan"] == period["plan"]
                      and parse_timestamp(windows[i]["start"]).timestamp() >= start
                      and parse_timestamp(windows[i]["end"]).timestamp() <= end
                      and (period["saturated_at"] is None
                           or parse_timestamp(windows[i]["start"]).timestamp() < period["saturated_at"]
                           and parse_timestamp(windows[i].get("fit_end") or windows[i]["end"]).timestamp()
                           <= period["saturated_at"])]
        fitted = max(candidates, key=lambda i: (windows[i]["estimate"]["span"], windows[i]["end"]), default=None)
        period.update(usage_usd=cost, usage_usd_min=minimum, usage_usd_max=maximum,
            unpriced_tokens=unknown, unpriced_tokens_min=unknown_min, unpriced_tokens_max=unknown_max,
            coverage_complete=coverage_complete,
            allowance_used=period["meter_end"],
            allowance_value=windows[fitted]["estimate"]["value"] if fitted is not None else None,
            allowance_fit_index=fitted,
            allowance_confidence=windows[fitted]["estimate"]["confidence"] if fitted is not None else "insufficient")
    periods.sort(key=lambda p: (p["end"], p["start"]), reverse=True)
    uncertain.sort(key=lambda p: p["capture_indices"][-1], reverse=True)
    return dict(captures=captures, periods=periods, uncertain=uncertain,
                cross_boundary_fit_indices=cross, kind="reset-period-economics-v1")
