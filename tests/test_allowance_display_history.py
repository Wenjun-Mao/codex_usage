"""Presentation evidence must not strengthen or alter monetary estimation."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json

import pytest

from codex_usage.allowance_display_history import display_history
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_report_codec import decode_report, encode_report


AT = datetime(2026, 11, 1, 3, 30, tzinfo=UTC)


def point(hour=0, used=10, **changes):
    return replace(QuotaObservation((AT + timedelta(hours=hour)).isoformat(), "codex", "primary",
                                   "pro", used, 300, int((AT + timedelta(hours=5)).timestamp())), **changes)


def grouped(points, windows=(), anchors=()):
    return display_history(points, {p: {"Task snapshot", "Live probe"} for p in points}, windows, anchors)


def test_compatible_metadata_slot_moves_and_reset_jitter_are_one_observed_period():
    points = [point(), point(1, 20, plan="", slot="secondary", resets_at=None),
              point(2, 30, resets_at=point().resets_at + 30)]
    result = grouped(points, anchors=[points[-1]])
    assert len(result["periods"]) == 1 and not result["uncertain"]
    period = result["periods"][0]
    assert period["plan"] == "pro" and period["current"]
    assert period["boundary"] == "left censored"
    assert period["capture_indices"] == [0, 1, 2]
    assert result["captures"][1]["plan"] == ""


@pytest.mark.parametrize("boundary", ["drop", "rebase", "conflict"])
def test_unsupported_boundary_stays_uncertain_until_supported_reset(boundary):
    points = [point(0, 60)]
    if boundary == "drop":
        points += [point(1, 10), point(2, 15)]
    elif boundary == "rebase":
        points += [point(1, 65, resets_at=point().resets_at + 7200),
                   point(2, 70, resets_at=point().resets_at + 7200)]
    else:
        points += [point(1, 65), point(1, 70), point(2, 75)]
    points += [point(3, 5, reset_credits=1), point(4, 10, reset_credits=0)]
    result = grouped(points, anchors=[points[-1]])
    assert len(result["periods"]) == 2
    assert result["periods"][0]["boundary"] == "reset credit decrease"
    assert result["periods"][0]["current"]
    assert sum(len(f["capture_indices"]) for f in result["uncertain"]) >= 3
    assert not any(f["current"] for f in result["uncertain"])


def test_scheduled_and_early_banked_reset_are_separate_without_inferred_starts():
    points = [point(0, 60, reset_credits=2), point(1, 10, reset_credits=1),
              point(6, 20, resets_at=point().resets_at + 18000, reset_credits=1)]
    result = grouped(points, anchors=[points[-1]])
    assert [f["boundary"] for f in result["periods"]] == [
        "scheduled reset", "reset credit decrease", "left censored"]
    assert not result["uncertain"]
    assert [f["current"] for f in result["periods"]] == [True, False, False]
    assert "start" not in result["periods"][0]


def test_missing_clocks_and_credits_keep_supported_prior_evidence_not_inferred_start():
    points = [point(0, 60, reset_credits=2), point(1, 65, resets_at=None, reset_credits=None),
              point(6, 10, resets_at=point().resets_at + 18000, reset_credits=2)]
    result = grouped(points)
    assert len(result["periods"]) == 2 and not result["uncertain"]
    assert result["periods"][0]["boundary"] == "scheduled reset"
    assert result["captures"][1]["resets_at"] is None
    assert result["captures"][1]["reset_credits"] is None


@pytest.mark.parametrize("changes", [{"resets_at": point().resets_at + 120}, {"reset_credits": 2}])
def test_same_time_metadata_conflicts_are_not_silently_skipped(changes):
    points = [point(0, reset_credits=1), point(1, 20, reset_credits=1),
              point(1, 20, **changes), point(2, 30, reset_credits=1)]
    result = grouped(points)
    assert len(result["captures"]) == 4
    assert len(result["periods"]) == 1
    assert sum(len(f["capture_indices"]) for f in result["uncertain"]) == 3


def test_unknown_plan_does_not_bridge_different_known_plans_or_duration_changes():
    points = [point(0), point(1, 20, plan=""), point(2, 30, plan="team", duration_minutes=10080),
              point(3, 40, plan="pro")]
    result = grouped(points, anchors=[points[-1]])
    assert len(result["periods"]) == 3
    assert len(result["uncertain"]) == 1
    assert result["uncertain"][0]["plan"] == ""
    assert result["uncertain"][0]["capture_indices"] == [1]
    assert sum(f["current"] for f in result["periods"]) == 1


def test_conflicting_plan_metadata_cannot_restore_certainty_on_same_plan():
    points = [point(0), point(1, 20), point(1, 20, plan="team"), point(2, 30)]
    result = grouped(points, anchors=[points[-1]])
    assert len(result["periods"]) == 2
    current = next(f for f in result["periods"] if f["current"])
    assert current["uncertain"] and current["capture_indices"] == [3]
    assert sum(len(f["capture_indices"]) for f in result["uncertain"]) == 2


def test_multiple_buckets_current_requires_exact_anchor_not_ongoing_fit():
    points = [point(0), point(1, 20, duration_minutes=10080), point(2, 30, limit_id="other")]
    result = grouped(points, anchors=[points[1]])
    assert len(result["periods"]) == 3
    assert [f["duration_minutes"] for f in result["periods"] if f["current"]] == [10080]
    assert not any(f["current"] for f in grouped(points, anchors=[replace(points[1], used_percent=21)])["periods"])


def test_same_time_conflicts_retained_and_cross_boundary_fit_owned_once():
    points = [point(0), point(1, 20), point(1, 25), point(2, 30)]
    windows = [{"points": [dict(p.to_dict(), provenance="Live probe, Task snapshot")
                           for p in (points[0], points[1], points[-1])],
                "estimate": {"value": 123.456}}]
    original = deepcopy(windows)
    result = grouped(points, windows)
    assert len(result["captures"]) == 4
    assert all(p["provenance"] == "Live probe, Task snapshot" for p in result["captures"])
    assert result["cross_boundary_fit_indices"] == [0]
    assert not any(f["fit_indices"] for f in result["periods"] + result["uncertain"])
    assert windows == original
    report = dict(windows=windows, qualified=[], history=windows, headline=windows[0], display_history=result)
    restored = decode_report(encode_report(report))
    assert restored == report and restored["headline"] is restored["windows"][0]
    damaged = json.loads(encode_report(report))
    damaged["report"]["display_history"]["cross_boundary_fit_indices"] = [True]
    with pytest.raises(ValueError, match="display reference"):
        decode_report(json.dumps(damaged))


@pytest.mark.parametrize("damage", ["duplicate", "missing"])
def test_codec_requires_one_capture_owner(damage):
    result = grouped([point()])
    result["periods"][0]["capture_indices"] = [0, 0] if damage == "duplicate" else []
    with pytest.raises(ValueError, match="exactly one owner"):
        encode_report(dict(windows=[], qualified=[], history=[], headline=None, display_history=result))
