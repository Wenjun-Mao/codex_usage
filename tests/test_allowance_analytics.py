from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from codex_usage.allowance_estimation import estimate_window
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_windows import AllowanceWindow, boundary, segment_windows


BASE = datetime(2026, 9, 1, tzinfo=UTC)


def point(index, used, **kwargs):
    return QuotaObservation((BASE + timedelta(hours=index)).isoformat(), "codex", "primary", "pro", used, 333,
                            int((BASE + timedelta(hours=20)).timestamp()), **kwargs)


@pytest.mark.parametrize("drop", [1, 2, 4.9])
def test_unsupported_small_drops_are_corrections(drop):
    assert boundary(point(0, 50), point(1, 50 - drop)) == "correction"
    windows = segment_windows([point(0, 50), point(1, 50 - drop), point(2, 55)])
    assert len(windows) == 1 and windows[0].corrections == 1


def test_irregular_scheduled_boundary_and_slot_migration():
    points = [point(0, 10), replace(point(1, 60), slot="secondary"),
              replace(point(21, 2), resets_at=int((BASE + timedelta(hours=30)).timestamp()))]
    windows = segment_windows(points)
    assert len(windows) == 2
    assert windows[0].closure == "scheduled-compatible"
    assert windows[0].completed
    assert len(windows[0].points) == 2


def test_banked_and_global_reset_evidence():
    windows = segment_windows([point(0, 70, reset_credits=2), point(1, 2, reset_credits=1)])
    assert windows[0].closure == "banked-reset-compatible"
    points = [point(0, 70), point(1, 2)]
    points += [replace(p, limit_id="other") for p in points]
    assert [w.closure for w in segment_windows(points)].count("global-reset-compatible") == 2


@pytest.mark.parametrize("completed,span,bins,priced,coverage,expected", [
    (True, 60, 13, True, True, "High"),
    (True, 30, 7, True, True, "Medium"),
    (True, 12, 5, True, True, "Low/provisional"),
    (False, 60, 13, True, True, "Low/provisional"),
    (True, 60, 13, False, True, "Low/provisional"),
    (True, 60, 13, True, False, "Low/provisional"),
    (True, 9, 10, True, True, "insufficient"),
    (True, 50, 4, True, True, "insufficient"),
])
def test_confidence_gates_and_independent_slope_oracle(completed, span, bins, priced, coverage, expected):
    points = [point(i, round(i * span / (bins - 1))) for i in range(bins)]
    window = AllowanceWindow(points, "scheduled-compatible" if completed else "ongoing")
    # A nonzero intercept must have no effect on the expected $1,200 slope.
    estimate = estimate_window(window, [321 + 12 * p.used_percent for p in points],
                               fully_priced=priced, coverage_complete=coverage)
    assert estimate.confidence == expected
    if priced and expected != "insufficient":
        assert estimate.value == pytest.approx(1200)
        assert estimate.r_squared == pytest.approx(1)
    else:
        assert estimate.value is None


def test_ten_percentage_points_is_the_existing_sufficiency_boundary():
    nine_point_samples = [0, 2, 5, 7, 9]
    ten_point_samples = [0, 2, 5, 8, 10]
    nine_point = estimate_window(
        AllowanceWindow([point(i, used) for i, used in enumerate(nine_point_samples)], "ongoing"),
        [used * 12 for used in nine_point_samples],
        fully_priced=True,
    )
    ten_point = estimate_window(
        AllowanceWindow([point(i, used) for i, used in enumerate(ten_point_samples)], "ongoing"),
        [used * 12 for used in ten_point_samples],
        fully_priced=True,
    )

    assert nine_point.span == 9 and nine_point.value is None
    assert ten_point.span == 10
    assert ten_point.confidence == "Low/provisional"
    assert ten_point.value == pytest.approx(1200)


def test_bins_remove_repetition_weight_and_ambiguous_boundary_blocks_high():
    points = [point(i, i * 5) for i in range(13)]
    costs = [10 * p.used_percent for p in points]
    window = AllowanceWindow(points, "early/unknown", ambiguous=True)
    assert estimate_window(window, costs, fully_priced=True).confidence == "Medium"
    repeated = [replace(points[2], timestamp=(BASE + timedelta(minutes=i)).isoformat()) for i in range(1, 80)]
    window.points += repeated
    estimate = estimate_window(window, costs + [100] * len(repeated), fully_priced=True)
    assert estimate.value == pytest.approx(1000)


def test_never_fits_across_reset():
    points = [point(i, i * 10) for i in range(6)] + [point(6 + i, i * 10) for i in range(6)]
    windows = segment_windows(points)
    assert len(windows) == 2
    for window in windows:
        costs = [p.used_percent * 3 for p in window.points]
        assert estimate_window(window, costs, fully_priced=True).value == pytest.approx(300)


def test_noisy_or_inconsistent_fit_does_not_qualify():
    points = [point(i, i * 5) for i in range(13)]
    window = AllowanceWindow(points, "scheduled-compatible")
    noisy = [i * i * 10 for i in range(13)]
    estimate = estimate_window(window, noisy, fully_priced=True)
    assert estimate.confidence == "Low/provisional"
    assert estimate.sensitivity_ratio > 1.35
    assert estimate_window(window, list(reversed(noisy)), fully_priced=True).value is None


def test_plan_change_closes_identity_and_cannot_join_later_return():
    windows = segment_windows([point(0, 10), replace(point(1, 20), plan="plus"), point(2, 30)])
    assert len(windows) == 3
    assert windows[0].closure == "identity-change"
    assert not windows[0].completed


def test_missing_identity_is_never_a_qualified_estimate():
    points = [replace(point(i, i * 5), plan="") for i in range(13)]
    estimate = estimate_window(AllowanceWindow(points, "scheduled-compatible"),
                               [i * 20 for i in range(13)], fully_priced=True)
    assert estimate.confidence == "Low/provisional"


def test_same_limit_different_duration_can_support_global_reset():
    points = [point(0, 70), point(1, 2)]
    points += [replace(p, duration_minutes=300, slot="secondary") for p in points]
    assert [w.closure for w in segment_windows(points)].count("global-reset-compatible") == 2


@pytest.mark.parametrize("plans,identities,sizes", [
    (["pro", "", "pro", "", "pro"], ["pro"], [5]),
    (["", "", "pro", "", ""], ["pro"], [5]),
    (["", "", "", "", ""], [""], [5]),
    (["pro", "", "", "plus", ""], ["pro", "", "plus"], [1, 2, 2]),
    (["pro", "", "plus", "", "pro"], ["pro", "", "plus", "", "pro"], [1] * 5),
])
def test_unknown_plan_runs_have_separate_derived_identity(plans, identities, sizes):
    points = [replace(point(i, i * 5), plan=plan) for i, plan in enumerate(plans)]
    windows = segment_windows(points)
    assert [w.identity_plan for w in windows] == identities
    assert [len(w.points) for w in windows] == sizes
    assert [p for w in windows for p in w.points] == points
    assert all(w.closure == "identity-change" for w in windows[:-1])


@pytest.mark.parametrize("kind", ["scheduled-compatible", "banked-reset-compatible", "global-reset-compatible"])
def test_unknown_plans_preserve_supported_resets(kind):
    points = [point(0, 20, reset_credits=2), replace(point(1, 70, reset_credits=2), plan="")]
    last = replace(point(21, 2, reset_credits=2), plan="")
    if kind == "scheduled-compatible":
        last = replace(last, resets_at=int((BASE + timedelta(hours=30)).timestamp()))
    elif kind == "banked-reset-compatible":
        last = replace(last, reset_credits=1)
    points += [last, point(22, 10, reset_credits=last.reset_credits)]
    if kind == "global-reset-compatible":
        points += [replace(p, limit_id="other") for p in points]
    windows = segment_windows(points)
    assert windows[0].closure == kind
    assert windows[0].points[-1].used_percent == 70
    assert windows[1].points[0].used_percent == 2
    assert all(w.identity_plan == "pro" for w in windows)


def test_unknown_plan_identity_isolated_by_limit_and_duration_with_slot_moves():
    points = [point(0, 10), replace(point(1, 20), plan="", slot="secondary"), point(2, 30)]
    points += [replace(point(i, 50 + i), plan="", duration_minutes=300) for i in range(3)]
    points += [replace(point(i, 60 + i), plan="", limit_id="other") for i in range(3)]
    windows = segment_windows(points)
    assert [(w.identity_plan, len(w.points)) for w in windows] == [("pro", 3), ("pro", 3), ("", 3)]
    assert windows[0].points[1].slot == "secondary"


def test_same_timestamp_unknown_metadata_does_not_hide_conflict():
    points = [point(0, 20), replace(point(0, 70), plan=""), point(1, 80)]
    windows = segment_windows(points)
    assert len(windows) == 1 and windows[0].ambiguous
    assert windows[0].points == [points[0], points[2]]
    changed = segment_windows([point(0, 20), replace(point(0, 20), plan="plus"), point(1, 30)])
    assert [w.identity_plan for w in changed] == ["pro", "plus", "pro"]


def test_derived_plan_does_not_promote_missing_metadata_confidence():
    points = [replace(point(i, i * 5), plan="" if i == 3 else "pro") for i in range(13)]
    window = segment_windows(points)[0]
    window.closure = "scheduled-compatible"
    assert window.identity_plan == "pro"
    assert estimate_window(window, [p.used_percent * 12 for p in points],
                           fully_priced=True).confidence == "Low/provisional"


def test_alternating_plan_metadata_at_subsecond_cadence_is_one_cycle():
    points = [replace(point(0, 35), timestamp=(BASE + timedelta(milliseconds=offset)).isoformat(),
                      plan=plan, duration_minutes=10080)
              for offset, plan in [(407, "pro"), (1029, ""), (2135, "pro")]]
    windows = segment_windows(points)
    assert len(windows) == 1 and windows[0].points == points
    assert windows[0].identity_plan == "pro" and windows[0].closure == "ongoing"
