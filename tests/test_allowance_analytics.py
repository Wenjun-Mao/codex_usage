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
