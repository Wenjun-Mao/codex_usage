from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from codex_usage.allowance_calibration_evidence import calibration_points
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_preparation import AllowancePreparation
from codex_usage.allowance_queries import _build_from_costs
from codex_usage.allowance_store import store_observations
from codex_usage.ledger_schema import open_ledger


BASE = datetime(2026, 11, 25, 14, 39, tzinfo=UTC)
RESET = int((BASE + timedelta(days=7)).timestamp())


def point(minutes, used, **changes):
    return replace(QuotaObservation((BASE + timedelta(minutes=minutes)).isoformat(),
                   "codex", "primary", "pro", used, 10080, RESET, 2), **changes)


def test_task_regression_does_not_shorten_current_cost_fit_or_pace(tmp_path):
    live = [point(i * 15, used) for i, used in enumerate([0, 4, 8, 12, 16, 23, 25, 28, 30, 32])]
    stale = point(76, 17, reset_credits=None)
    with open_ledger(tmp_path / "ledger") as connection:
        store_observations(connection, live, source_key="read:test", provenance="live")
        store_observations(connection, (stale,), source_key="task:test", provenance="parsed")
        preparation = AllowancePreparation(connection, reuse_history=False)
        changes = (
            (b.timestamp_seconds, 13.554 * (b.used_percent - a.used_percent), 0)
            for a, b in zip(live, live[1:])
        )
        report = _build_from_costs(connection, changes, preparation=preparation,
                                   coverage_complete=False,
                                   status={"active_buckets": [live[-1].to_dict()]})
        assert stale in preparation.raw[0]
        assert stale not in preparation.calibration_points
    headline = report["headline"]
    assert report["windows"] == [headline]
    assert headline["start"] == live[0].timestamp
    assert headline["estimate"]["value"] == pytest.approx(1355.4)
    assert headline["estimate"]["cost_span"] == pytest.approx(433.728)
    assert headline["estimate"]["confidence"] == "Low/provisional"
    captures = report["display_history"]["captures"]
    assert any(p["timestamp"] == stale.timestamp and p["used_percent"] == 17 for p in captures)
    cycle = next(p for p in report["paces"][0] if p["name"] == "Cycle")
    assert cycle["observed_start"] == live[0].timestamp
    assert cycle["movement"] == 32


@pytest.mark.parametrize(("changes", "at", "source", "live_changes"), [
    ({"resets_at": RESET + 180}, 1, "Task snapshot", {}),
    ({"reset_credits": 1}, 1, "Task snapshot", {}),
    ({"plan": "plus"}, 1, "Task snapshot", {}),
    ({"duration_minutes": 300}, 1, "Task snapshot", {}),
    ({"resets_at": None}, 1, "Task snapshot", {}),
    ({}, 31, "Task snapshot", {}),
    ({}, 0, "Task snapshot", {}),
    ({}, 1, "Unknown source", {}),
    ({}, 1, "Task snapshot", {"reset_credits": None}),
    ({"resets_at": int(BASE.timestamp()) + 30}, 1, "Task snapshot",
     {"resets_at": int(BASE.timestamp()) + 30}),
])
def test_uncertain_or_contradictory_evidence_is_preserved(changes, at, source, live_changes):
    live = point(0, 23, **live_changes)
    lower = point(at, 17, **changes)
    points = (live, lower)
    assert calibration_points(points, {lower: {source}}, {live}) == points


def test_live_drops_and_conflicts_are_retained_and_filter_is_causal():
    earlier = point(0, 23)
    conflicting = point(0, 15, slot="secondary")
    task = point(1, 17)
    later = point(15, 17)
    sources = {task: {"Recovered task snapshot"}}
    assert calibration_points((earlier, task), sources, {earlier}) == (earlier,)
    assert calibration_points((earlier, task, later), sources, {earlier, later}) == (earlier, later)
    assert calibration_points((earlier, conflicting, task), sources,
                              {earlier, conflicting}) == (earlier, conflicting, task)
    assert calibration_points((task, later), sources, {later}) == (task, later)
