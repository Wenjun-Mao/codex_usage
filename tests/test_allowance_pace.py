"""Forecast continuity is deliberately stronger than retrospective dollar history."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import exp, log
from zoneinfo import ZoneInfo

import pytest

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_pace import active_evidence, fit_paces, pace_state
from codex_usage.allowance_windows import boundary, seconds
from codex_usage.report_allowance_pace import pace_rows

BASE = datetime(2026, 9, 30, 12, tzinfo=UTC)
RESET = int((BASE + timedelta(days=2)).timestamp())


def point(hour, used, **kw):
    return replace(QuotaObservation((BASE + timedelta(hours=hour)).isoformat(),
                                   "codex", "primary", "pro", used, 10080, RESET, 3), **kw)


def fit(points):
    return fit_paces(points, points[-1], set(points))


def test_recent_endpoint_invariance_and_direct_daily_integral():
    sparse = [point(0, 10), point(.5, 12), point(1, 20)]
    dense = sparse[:1] + [point(.1, 10), point(.2, 10), point(.3, 10)] + sparse[1:]
    assert fit(sparse)[0]["rate"] == fit(dense)[0]["rate"] == 10
    points = [point(h, 5 + h if h <= 21 else 26 + (h - 21) * 8) for h in range(25)]
    daily = fit(points)[1]
    k = log(2) / 6
    expected = ((exp(-3*k)-exp(-24*k)) + 8*(1-exp(-3*k))) / (1-exp(-24*k))
    assert daily["rate"] == pytest.approx(expected)
    assert daily["span_seconds"] == 86400


def test_signed_corrections_do_not_invent_movement():
    points = [point(i / 4, used) for i, used in enumerate([20, 23, 22, 23, 21])]
    assert fit(points)[0]["rate"] is None
    points[-1] = point(1, 24)
    pace = fit(points)[0]
    assert pace["rate"] == 4 and pace["corrections"] == 1


@pytest.mark.parametrize("changes", [
    {"resets_at": int((BASE + timedelta(hours=.5)).timestamp())},
    {"reset_credits": 2},
    {"resets_at": RESET + 120},
])
def test_strong_boundary_precedes_small_drop_and_remembers_metadata(changes):
    first = point(0, 30, **changes) if "reset_credits" not in changes else point(0, 30)
    missing = point(.25, 30, resets_at=None, reset_credits=None)
    last = point(.5, 29.5, **({"reset_credits": 2} if "reset_credits" in changes else
                            {"resets_at": RESET if changes["resets_at"] != RESET + 120 else RESET}))
    assert boundary(missing, last) == "correction"
    suffix, reason, _ = active_evidence([first, missing, last], last, {last})
    assert suffix == [last] and reason != "left censored"
    assert fit_paces([first, missing, last], last, {last})[0]["rate"] is None


def test_coherent_suffix_recovers_after_conflict_or_unknown_boundary():
    old = [point(-1, 80), point(-.5, 81)]
    new = [point(0, 5), point(.5, 7), point(1, 9)]
    assert fit(old + new)[0]["rate"] == 4
    conflicting = old + [point(-.5, 82)] + new
    assert fit(conflicting)[0]["rate"] == 4
    for field, value in (("used_percent", 10), ("reset_credits", 2), ("plan", "plus"), ("resets_at", RESET+120)):
        points = new + [replace(new[-1], **{field: value})]
        assert fit_paces(points, new[-1], {new[-1]})[0]["reason"] == "live anchor conflict"


def test_future_metadata_cannot_change_plan_resolution_or_membership():
    points = [point(0, 10), point(.5, 12, plan=""), point(1, 14, plan="")]
    before = fit(points)
    assert fit_paces(points + [point(2, 16, plan="plus")], points[-1], set(points)) == before
    assert before[0]["rate"] == 4
    assert fit_paces(points, points[-1], set())[0]["rate"] is None
    assert fit([points[0], replace(points[1], slot="secondary"), points[2]]) == before
    assert fit_paces(points + [point(.25, 90, limit_id="other")], points[-1], set(points)) == before


def test_actual_endpoints_gates_and_missing_live_reset():
    points = [point(0, 10), point(.25, 11), point(.5, 12)]
    assert fit(points)[0]["rate"] == 4
    assert fit([points[0], points[-1]])[0]["reason"] == "too few observations"
    assert fit([point(0, 10), point(.1, 11), point(.2, 12)])[0]["reason"] == "short observed span"
    assert fit([point(0, 10), point(.1, 11), point(1, 14)])[0]["reason"] == "observation gap"
    missing = points[:-1] + [replace(points[-1], resets_at=None)]
    pace = fit(missing)[0]
    assert pace["rate"] == 4 and pace["reset_balance"] is None
    assert pace_state(pace, "fresh", pace["anchor"]) == "missing reset"


def test_expiry_never_slides_capture_anchor_and_partial_succeeds():
    points = [point(0, 95), point(.25, 97), point(.5, 99)]
    pace = fit(points)[0]
    anchor, exhaustion = pace["anchor"], pace["exhaustion"]
    assert exhaustion == anchor + 450
    assert pace_state(pace, "partial", anchor) == "ready"
    assert pace_state(pace, "fresh", exhaustion) == "awaiting"
    assert pace_state(pace, "stale", anchor) == "awaiting"
    assert pace_state(pace, "fresh", anchor + 1800) == "awaiting"
    assert pace["exhaustion"] == exhaustion
    assert pace_state(dict(pace, reset=anchor), "fresh", anchor) == "awaiting"
    assert pace_state(dict(pace, used=100), "fresh", anchor) == "reported full"


def test_local_midnight_dst_rounding_near_reset_and_small_balance():
    pace = fit([point(0, 95), point(.25, 97), point(.5, 99)])[0]
    timezone = ZoneInfo("America/Toronto")
    # Exhaustion is exactly around the repeated autumn hour; include local offset.
    anchor = datetime(2026, 11, 1, 5, 50, tzinfo=UTC).timestamp()
    changed = dict(pace, anchor=anchor, exhaustion=anchor+1200, reset=anchor+7200)
    html = pace_rows([changed], "fresh", timezone=timezone, now=datetime.fromtimestamp(anchor, UTC))
    assert "01:15 EST (-0500)" in html
    midnight = datetime(2026, 10, 1, 3, 50, tzinfo=UTC).timestamp()
    changed.update(anchor=midnight, exhaustion=midnight+1200, reset=midnight+7200)
    assert "2026-10-01" in pace_rows([changed], "fresh", timezone=timezone, now=datetime.fromtimestamp(midnight, UTC))
    changed.update(reset=changed["exhaustion"]+899)
    assert "near reset" in pace_rows([changed], "fresh", timezone=timezone, now=datetime.fromtimestamp(midnight, UTC))
    changed.update(exhaustion=changed["reset"]+1800, reset_balance=.2)
    assert "less than 1%" in pace_rows([changed], "fresh", timezone=timezone, now=datetime.fromtimestamp(midnight, UTC))
    assert seconds(point(0, 10)) == BASE.timestamp()


def test_no_drop_reset_and_jitter_and_exact_live_jump():
    old_reset = int((BASE + timedelta(minutes=30)).timestamp())
    points = [point(0, 20, resets_at=old_reset), point(.25, 21, resets_at=None), point(.5, 22)]
    assert fit(points)[0]["boundary"] == "scheduled reset"
    assert fit(points)[0]["rate"] is None
    stable = [point(0, 20), point(.25, 21, resets_at=RESET+30), point(.5, 22)]
    assert fit(stable)[0]["rate"] == 4
    jumped = stable + [point(.51, 24)]
    assert fit(jumped)[0]["rate"] == pytest.approx(4/.51)
    assert fit(jumped)[0]["anchor"] == seconds(jumped[-1])


def test_daily_signed_corrections_and_nonpositive_weighted_rate():
    points = [point(i, used) for i, used in enumerate([10, 13, 12, 13, 14])]
    pace = fit(points)[1]
    k = log(2)/6
    weights = [exp(k*(i-3))-exp(k*(i-4)) for i in range(4)]
    assert pace["rate"] == pytest.approx(sum(w*r for w, r in zip(weights, [3, -1, 1, 1]))/sum(weights))
    # Positive endpoint movement cannot rescue a negative directly weighted pace.
    points = [point(i*3, used) for i, used in enumerate([10, 14, 18, 16, 12])]
    assert fit(points)[1]["reason"] == "nonpositive rate"


def test_plan_change_in_other_duration_is_not_a_bridge_between_same_plan_points():
    points = [point(0, 10), point(.5, 12), point(1, 14)]
    changed = point(.75, 15, plan="plus", duration_minutes=300)
    pace = fit_paces(points + [changed], points[-1], set(points))[0]
    assert pace["boundary"] == "plan change" and pace["rate"] is None
    # Neither an unrelated limit nor future plan evidence can cause this cut.
    assert fit_paces(points + [replace(changed, limit_id="other")], points[-1], set(points)) == fit(points)
    assert fit_paces(points + [point(2, 15, plan="plus", duration_minutes=300)], points[-1], set(points)) == fit(points)
