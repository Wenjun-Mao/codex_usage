"""Observed-cycle baselines use raw endpoints, not an invented reset origin."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_pace import fit_paces, pace_state
from codex_usage.allowance_pace_evidence import Series, prepare_pace_evidence
from codex_usage.report_allowance_pace import pace_details, pace_rows


BASE = datetime(2026, 10, 2, tzinfo=UTC)
RESET = int((BASE + timedelta(hours=72)).timestamp())


def point(hour, used, **changes):
    return replace(QuotaObservation((BASE + timedelta(hours=hour)).isoformat(),
                                   "codex", "primary", "pro", used, 10080, RESET, 3), **changes)


def cycle(points, anchor=None, live=None):
    anchor = anchor or points[-1]
    return fit_paces(prepare_pace_evidence(points, {anchor} if live is None else live), anchor)[2]


def test_cycle_uses_whole_observed_suffix_and_nonzero_first_capture():
    points = [point(0, 7), point(12, 12), point(24, 14), point(48, 19)]
    result = cycle(points)
    assert result["name"] == "Cycle"
    assert result["horizon_seconds"] is None
    assert result["span_seconds"] == 48 * 3600
    assert result["movement"] == 12
    assert result["rate"] == .25
    assert result["reset_balance"] == 75
    assert result["exhaustion"] == BASE.timestamp() + (48 + 81/.25) * 3600
    assert result["observed_start"] == points[0].timestamp
    assert result["gap_seconds"] == 24 * 3600
    html = pace_rows([result], "fresh", timezone=ZoneInfo("America/Toronto"), now=BASE+timedelta(hours=48))
    assert "Cycle average · 2d" in html and "75% would remain at reset" in html
    details = pace_details([[result]], "fresh", now=BASE+timedelta(hours=48))
    assert "reset instant may be unobserved" in details
    assert "weighted" not in details and "None" not in details


def test_idle_time_and_capture_density_do_not_change_cycle_rate():
    points = [point(0, 10), point(2, 10), point(4, 18)]
    dense = points[:1] + [point(h, 10) for h in (.5, 1, 1.5)] + points[1:]
    assert cycle(points)["rate"] == cycle(dense)["rate"] == 2
    assert cycle(points)["exhaustion"] == cycle(dense)["exhaustion"]


def test_cycle_preserves_signed_corrections_and_gate_semantics():
    result = cycle([point(0, 10), point(1, 13), point(2, 12), point(3, 16)])
    assert result["rate"] == 2 and result["corrections"] == 1
    assert cycle([point(0, 10), point(.5, 12)])["reason"] == "too few observations"
    assert cycle([point(0, 10), point(.1, 11), point(.2, 12)])["reason"] == "short observed span"
    assert cycle([point(0, 10), point(1, 14), point(2, 11)])["reason"] == "insufficient signed movement"
    assert cycle([point(0, 12), point(1, 11), point(2, 10)])["rate"] is None


@pytest.mark.parametrize("change, expected", [
    ({"reset_credits": 2}, "reset credit decrease"),
    ({"resets_at": RESET+120}, "deadline rebase"),
    ({"used_percent": 5}, "unknown boundary"),
    ({"plan": "plus"}, "plan change"),
])
def test_cycle_restarts_at_actual_first_point_after_a_boundary(change, expected):
    old = [point(-4, 30), point(-3, 32)]
    first = replace(point(0, 31), **change)
    new = [first, replace(first, timestamp=point(1, 0).timestamp, used_percent=first.used_percent+2),
           replace(first, timestamp=point(2, 0).timestamp, used_percent=first.used_percent+4)]
    result = cycle(old + new)
    assert result["boundary"] == expected
    assert result["observed_start"] == first.timestamp
    assert result["rate"] == 2 and result["observations"] == 3
    assert result["span_seconds"] == 7200


def test_cycle_remembers_strong_reset_evidence_across_missing_metadata():
    old_reset = int((BASE + timedelta(hours=1)).timestamp())
    points = [point(0, 40, resets_at=old_reset), point(.5, 40, resets_at=None, reset_credits=None),
              point(1, 39.5), point(1.5, 40.5), point(2, 41.5)]
    result = cycle(points)
    assert result["boundary"] == "scheduled reset"
    assert result["observations"] == 3 and result["rate"] == 2
    assert result["observed_start"] == points[2].timestamp


def test_cycle_conflicts_cut_history_and_ambiguous_anchor_is_refused():
    old = [point(-2, 20), point(-1, 21), point(-1, 22)]
    new = [point(0, 22), point(.5, 23), point(1, 24)]
    result = cycle(old + new)
    assert result["boundary"] == "observation conflict" and result["rate"] == 2
    assert result["conflicts"] == 1 and result["observations"] == 3
    for changes in ({"used_percent": 25}, {"reset_credits": 2}, {"plan": "plus"}, {"resets_at": RESET+120}):
        result = cycle(new + [replace(new[-1], **changes)], anchor=new[-1])
        assert result["rate"] is None and result["reason"] == "live anchor conflict"


def test_cycle_retains_exact_live_anchor_and_causal_origin():
    points = [point(0, 10, plan=""), point(.5, 11, plan=""), point(1, 12)]
    result = cycle(points)
    future = [point(2, 15, plan="plus", reset_credits=2), point(1, 99, limit_id="other")]
    assert cycle(points+future, anchor=points[-1]) == result
    assert cycle(points, live=set())["reason"] == "exact live anchor missing"
    changed_slot = points[:1] + [replace(points[1], slot="secondary")] + points[2:]
    assert cycle(changed_slot) == result
    missing = points[:-1] + [replace(points[-1], resets_at=None)]
    result = cycle(missing)
    assert result["rate"] == 2 and result["reset"] is None and result["reset_balance"] is None
    assert pace_state(result, "fresh", result["anchor"]) == "missing reset"


def test_cycle_expiry_is_capture_anchored_not_a_sliding_prediction():
    result = cycle([point(0, 95), point(.25, 97), point(.5, 99)])
    assert result["exhaustion"] == result["anchor"] + 450
    assert pace_state(result, "fresh", result["anchor"]+449) == "ready"
    assert pace_state(result, "fresh", result["exhaustion"]) == "awaiting"
    assert pace_state(result, "stale", result["anchor"]) == "awaiting"
    assert pace_state(result, "partial", result["anchor"]) == "ready"
    assert pace_state(result, "fresh", result["anchor"]+1800) == "awaiting"
    assert pace_state(dict(result, reset=result["anchor"]), "fresh", result["anchor"]) == "awaiting"
    assert pace_state(dict(result, used=100), "fresh", result["anchor"]) == "reported full"


def test_cycle_endpoints_and_summaries_never_slice_or_walk_the_cycle():
    points = [point(i/4, 10+i/2000, resets_at=None) for i in range(52000)]
    prepared = prepare_pace_evidence(points, {points[-1]})
    original = prepared.series[("codex", 10080)]

    class EndpointOnlyGroups:
        def __len__(self):
            return len(original.groups)

        def __getitem__(self, index):
            assert isinstance(index, int), "Cycle must never slice historical observations"
            assert index in {0, len(points)-1}, "Cycle must only read its endpoints"
            return original.groups[index]

        def __iter__(self):
            raise AssertionError("Cycle must never walk historical observations")

    prepared.series[("codex", 10080)] = Series(original.times, EndpointOnlyGroups(),
                                              original.checkpoints, original.cycle_stats)
    result = prepared.cycle(points[-1])
    assert result.observations == 52000 and result.first == points[0]
    assert result.maximum_gap == 900 and result.corrections == 0
