"""Prepared checkpoints retain the full-prefix contract at each historical origin."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import random

import pytest

from allowance_pace_reference import active_evidence as reference_evidence, fit_paces as reference_fit
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_pace import fit_paces
from codex_usage.allowance_pace_evidence import prepare_pace_evidence
from codex_usage.allowance_windows import seconds


def assert_cycle_matches_full_prefix(points, anchor, result):
    sample, boundary, conflicts = reference_evidence(points, anchor, set(points))
    times = [seconds(p) for p in sample]
    span = times[-1] - times[0] if times else 0
    movement = sample[-1].used_percent - sample[0].used_percent if sample else 0
    reason = (boundary if not sample else "too few observations" if len(sample) < 3 else
              "short observed span" if span < 1800 else
              "insufficient signed movement" if movement < 2 else "")
    assert result["boundary"] == boundary and result["conflicts"] == conflicts
    assert result["observed_start"] == (sample[0].timestamp if sample else None)
    assert result["observations"] == len(sample)
    assert result["span_seconds"] == span and result["movement"] == movement
    assert result["gap_seconds"] == max((b-a for a, b in zip(times, times[1:])), default=0)
    assert result["corrections"] == sum(b.used_percent < a.used_percent for a, b in zip(sample, sample[1:]))
    assert result["reason"] == reason
    assert result["rate"] == (movement / (span/3600) if not reason else None)


def test_prepared_origins_equal_full_prefix_with_future_metadata_and_bridges():
    base = datetime(2026, 9, 1, tzinfo=UTC)
    for seed in range(12):
        rng = random.Random(seed)
        points = []
        plan, credits, used = "", 6, 10
        reset = int((base + timedelta(days=7)).timestamp())
        for index in range(180):
            time = base + timedelta(minutes=index * 15)
            if index % 37 == 0:
                plan = rng.choice(["", "pro", "plus"])
            if index % 49 == 0:
                credits -= 1
                reset += 7 * 86400
            used = min(95, max(0, used + rng.choice([-.5, 0, .5, 1])))
            point = QuotaObservation(time.isoformat(), "codex", "primary", plan if rng.random() > .4 else "",
                                     used, 300 if index % 7 else 10080,
                                     reset if rng.random() > .3 else None,
                                     credits if rng.random() > .3 else None)
            points.append(point)
            if index % 43 == 0:
                points.append(replace(point, reset_credits=credits+1))
            if index % 29 == 0:
                points.append(replace(point, used_percent=used+1))
        prepared = prepare_pace_evidence(points, points)
        for anchor in points[::5]:
            results = fit_paces(prepared, anchor)
            assert results[:2] == reference_fit(points, anchor, set(points)), (seed, anchor)
            assert_cycle_matches_full_prefix(points, anchor, results[2])


def test_leading_unknown_plan_resolution_does_not_rewrite_earlier_origins():
    base = datetime(2026, 9, 1, tzinfo=UTC)
    points = [QuotaObservation((base+timedelta(hours=i)).isoformat(), "codex", "primary", "", 10+i,
                               300, None) for i in range(8)]
    points += [replace(points[2], duration_minutes=10080, plan="pro"),
               replace(points[-1], plan="pro")]
    prepared = prepare_pace_evidence(points, points)
    for anchor in points:
        results = fit_paces(prepared, anchor)
        assert results[:2] == reference_fit(points, anchor, set(points))
        assert_cycle_matches_full_prefix(points, anchor, results[2])


def test_selection_and_fit_do_not_iterate_or_prepare_the_historical_prefix(monkeypatch):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    points = [QuotaObservation((base+timedelta(minutes=i*15)).isoformat(), "codex", "primary", "pro",
                               (i % 96)*.8, 1440, int((base+timedelta(days=i//96+1)).timestamp()))
              for i in range(52000)]
    prepared = prepare_pace_evidence(points, points)
    original = prepared.series[("codex", 1440)]

    class BoundedGroups:
        def __len__(self):
            return len(original.groups)

        def __iter__(self):
            raise AssertionError("historical prefix iteration")

        def __getitem__(self, key):
            if isinstance(key, slice):
                assert key.stop - key.start <= 97
            return original.groups[key]

    from codex_usage.allowance_pace_evidence import Series
    prepared.series[("codex", 1440)] = Series(original.times, BoundedGroups(), original.checkpoints, original.cycle_stats)

    def forbidden(*args, **kwargs):
        raise AssertionError("fitting must consume prepared checkpoints")

    monkeypatch.setattr("codex_usage.allowance_pace_evidence.prepare_pace_evidence", forbidden)
    result = fit_paces(prepared, points[-1])
    assert result[0]["rate"] == pytest.approx(3.2)
    assert result[1]["observations"] <= 97
    with pytest.raises(TypeError, match="requires prepared evidence"):
        fit_paces(points, points[-1])


def test_active_series_preparation_keeps_other_duration_plan_events():
    base = datetime(2026, 9, 1, tzinfo=UTC)
    points = [QuotaObservation((base+timedelta(minutes=i*15)).isoformat(), "codex", "primary", "pro", 10+i,
                               300, None) for i in range(5)]
    change = replace(points[3], duration_minutes=10080, plan="plus")
    prepared = prepare_pace_evidence(points+[change], points, series_keys={("codex", 300)})
    assert set(prepared.series) == {("codex", 300)}
    assert fit_paces(prepared, points[-1])[:2] == reference_fit(points+[change], points[-1], set(points))
    assert fit_paces(prepared, points[-1])[0]["boundary"] == "plan change"
