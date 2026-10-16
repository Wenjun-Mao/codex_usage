"""Reset evidence cannot cross plan identity or discard simultaneous conflicts."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_pace_evidence import prepare_pace_evidence
from codex_usage.allowance_queries import _build_from_costs
from codex_usage.allowance_report_codec import decode_report, encode_report

AT = datetime(2026, 10, 1, tzinfo=UTC)


def point(hour, used, deadline=6, plan="pro"):
    reset = None if deadline is None else int((AT+timedelta(hours=deadline)).timestamp())
    return QuotaObservation((AT+timedelta(hours=hour)).isoformat(), "codex", "primary",
                            plan, used, 10080, reset, 2)


def report(live, tasks=(), events=()):
    points = [*live, *tasks]
    provenance = {p: {"Live probe" if p in live else "Task snapshot"} for p in points}
    preparation = SimpleNamespace(raw=(points, provenance, set(live)),
        pace=lambda keys: prepare_pace_evidence(points, set(live), series_keys=keys))
    costs = [(AT.timestamp()+hour*3600, cost, 0) for hour, cost in events]
    with patch("codex_usage.allowance_queries.credit_history", return_value=[]):
        return _build_from_costs(None, costs, status={"active_buckets": [live[-1].to_dict()]},
                                 preparation=preparation)


def test_missing_clock_at_plan_change_cannot_retroactively_overlap_periods():
    result = report([point(0, 80), point(7, 10, None, "plus"), point(8, 20, 14, "plus")],
                    events=[(6.5, 10)])
    current, previous = result["reset_history"]["periods"]
    assert current["start"] == previous["end"] == AT.timestamp()+7*3600
    assert current["identity_opening"]["kind"] == "plan change"
    assert current["reset_opening"] is None
    assert current["deadlines"] == [point(8, 20, 14).resets_at]
    assert [p["usage_usd"] for p in (current, previous)] == [0, 10]
    assert decode_report(encode_report(result)) == result


def test_credit_reset_clears_old_clock_before_delayed_deadline_metadata():
    live = [point(0, 80), replace(point(7, 0, None), reset_credits=1),
            replace(point(8, 20, 14), reset_credits=1)]
    result = report(live, events=[(6.5, 10)])
    current, previous = result["reset_history"]["periods"]
    assert current["start"] == previous["end"] == AT.timestamp()+7*3600
    assert current["reset_opening"]["kind"] == "early reset"
    assert current["deadlines"] == [live[-1].resets_at]
    assert sum(p["usage_usd"] for p in (current, previous)) == 10
    assert decode_report(encode_report(result)) == result


def test_reset_cannot_reuse_previous_period_credit_restart_baseline():
    live = [point(0, 80), replace(point(1, 0, 8), reset_credits=None),
            replace(point(2, 10, 8), reset_credits=1)]
    result = report(live)
    assert len(result["reset_history"]["periods"]) == 2
    assert result["reset_history"]["periods"][0]["allowance_used"] == 10
    assert decode_report(encode_report(result)) == result


def test_conflicting_task_deadlines_cannot_narrow_reset_or_usage_bounds():
    live = [point(0, 80), point(1, 0, 8), point(2, 20, 8)]
    events = [(.25, 10), (.75, 20), (2, 30)]
    baseline = report(live, events=events)["reset_history"]["periods"][0]
    conflicted = report(live, [point(.5, 0, 8), point(.5, 80)], events)
    current = conflicted["reset_history"]["periods"][0]
    assert current["reset_opening"] == baseline["reset_opening"]
    assert [current[k] for k in ("usage_usd_min", "usage_usd_max")] == [30, 60]
    assert decode_report(encode_report(conflicted)) == conflicted


def test_initial_unknown_plan_resolves_without_hiding_later_plan_change():
    live = [point(0, 0, plan=""), point(1, 10)]
    live += [point(i, i*10, plan="plus") for i in range(2, 8)]
    result = report(live, events=[(i, 10) for i in range(8)])
    current, previous = result["reset_history"]["periods"]
    assert (current["plan"], previous["plan"]) == ("plus", "pro")
    assert current["identity_opening"]["kind"] == "plan change"
    assert current["allowance_value"] == 100
    assert previous["allowance_value"] is None
    assert sum(p["usage_usd"] for p in (current, previous)) == 80
    assert decode_report(encode_report(result)) == result


@pytest.mark.parametrize("decode", [False, True])
def test_codec_rejects_overlapping_reset_periods(decode):
    import json

    result = report([point(0, 80), point(1, 0, 8), point(2, 20, 8)])
    encoded = json.loads(encode_report(result)) if decode else None
    damaged = encoded["report"] if decode else deepcopy(result)
    current, previous = damaged["reset_history"]["periods"]
    current["start"] = previous["end"]-1
    with pytest.raises(ValueError, match="[Oo]verlapping reset"):
        decode_report(json.dumps(encoded)) if decode else encode_report(damaged)
