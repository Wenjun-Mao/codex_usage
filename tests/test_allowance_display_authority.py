"""Synthetic current membership and official-versus-task display authority."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from codex_usage.allowance_display_history import display_history
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_report_codec import decode_report, encode_report
from codex_usage.report_allowance_history import period_history
from codex_usage.allowance_history_navigation import navigation

AT = datetime(2026, 11, 1, 3, 30, tzinfo=UTC)


def point(hours, used, **fields):
    return replace(QuotaObservation((AT+timedelta(hours=hours)).isoformat(), "codex", "primary", "pro",
                                   used, 10080, int((AT+timedelta(days=5)).timestamp()), 3), **fields)


def build(live, tasks, anchors, windows=()):
    provenance = {p: {"Live probe"} for p in live}
    for p in tasks:
        provenance.setdefault(p, set()).add("Task snapshot")
    return display_history(live+tasks, provenance, windows, anchors, live_points=frozenset(live))


def test_exact_current_anchor_remains_primary_when_boundary_is_uncertain():
    points = [point(0, 80), point(1, 10), point(2, 15)]
    result = build(points, [], [points[-1]])
    current = [f for f in result["periods"] if f["current"]]
    assert len(current) == 1 and current[0]["uncertain"]
    assert current[0]["boundary"] == "unknown boundary"
    assert current[0]["capture_indices"] == [1, 2]
    assert not any(f["current"] for f in result["uncertain"])
    report = dict(windows=[], display_history=result, history=[], qualified=[], headline=None)
    markup = period_history(report, UTC, nav=navigation(report, "synthetic"))
    assert "Current · uncertain boundary" in markup and "Opening unobserved" in markup
    assert "Captured reset" in markup
    assert current[0]["next_reset"] == points[-1].resets_at
    assert "Observed 2026-11-01 to 2026-11-01" in markup
    assert "start" not in current[0]
    restored = decode_report(encode_report(report))
    assert restored == report


def test_current_missing_reset_does_not_borrow_earlier_deadline():
    points = [point(0, 40), point(1, 45, resets_at=None)]
    result = build(points, [], [points[-1]])
    current = next(fragment for fragment in result["periods"] if fragment["current"])
    assert current["next_reset"] is None
    report = dict(windows=[], display_history=result, history=[], qualified=[], headline=None)
    markup = period_history(report, UTC, nav=navigation(report, "synthetic"))
    assert "Captured reset" not in markup and "Next reset" not in markup


def test_conflicting_current_reset_captures_have_no_arbitrary_summary_deadline():
    first = point(0, 10)
    second = replace(first, slot="secondary", resets_at=first.resets_at+3600)
    result = build([first, second], [], [first, second])
    current = next(fragment for fragment in result["periods"] if fragment["current"])
    assert current["uncertain"] and current["next_reset"] is None


def test_coherent_live_range_ignores_interleaved_stale_and_conflicting_tasks():
    live = [point(0, 40), point(2, 50), point(4, 60)]
    stale = point(1, 1)
    conflict = point(2, 99, slot="secondary")
    rebase = point(3, 55, resets_at=live[0].resets_at+3600)
    plan = point(3.5, 58, plan="team")
    corroborated = point(1.5, 45, plan="", slot="secondary")
    tasks = [stale, conflict, rebase, plan, corroborated]
    result = build(live, tasks, [live[-1]])
    assert len(result["periods"]) == 1
    current = result["periods"][0]
    assert current["current"] and not current["uncertain"]
    assert current["next_reset"] == live[-1].resets_at
    assert len(current["capture_indices"]) == 4
    captures = result["captures"]
    assert {captures[i]["timestamp"] for i in current["capture_indices"]} == {p.timestamp for p in live+[corroborated]}
    assert sum(len(f["capture_indices"]) for f in result["uncertain"]) == 4
    assert all(f["evidence_reasons"] for f in result["uncertain"])
    assert {p["used_percent"] for p in captures} == {p.used_percent for p in live+tasks}
    assert sum(len(f["capture_indices"]) for f in result["periods"]+result["uncertain"]) == len(captures) == 8


def test_task_conflicts_cannot_consume_official_banked_or_scheduled_resets():
    live = [point(0, 80), point(1, 10, reset_credits=2),
            point(130, 20, reset_credits=2, resets_at=point(0, 1).resets_at+604800)]
    tasks = [point(.5, 2, reset_credits=0), point(129, 90, reset_credits=1)]
    result = build(live, tasks, [live[-1]])
    assert [f["boundary"] for f in result["periods"]] == ["scheduled reset", "reset credit decrease", "left censored"]
    assert sum(f["current"] for f in result["periods"]) == 1
    assert sum(len(f["capture_indices"]) for f in result["uncertain"]) == 2


@pytest.mark.parametrize("duration,plan", [(10080, "pro"), (None, "")])
def test_lone_current_anchor_has_only_observed_point_not_inferred_full_period(duration, plan):
    anchor = point(4, 60, duration_minutes=duration, plan=plan, resets_at=None)
    task = point(0, 10, duration_minutes=duration, plan=plan, resets_at=None)
    result = build([anchor], [task], [anchor])
    current = next(f for f in result["periods"] if f["current"])
    assert len(current["capture_indices"]) == 1
    captured = result["captures"][current["capture_indices"][0]]
    assert captured["timestamp"] == anchor.timestamp
    assert current["boundary"] == "left censored" and current["next_reset"] is None
    assert not any("start" in f for f in result["periods"])


def test_fits_remain_separate_and_cross_authority_barriers_are_not_duplicated():
    live = [point(0, 40), point(2, 50)]
    task = point(1, 1)
    provenance = {p: {"Live probe"} for p in live} | {task: {"Task snapshot"}}
    def capture(p):
        return dict(p.to_dict(), provenance=", ".join(sorted(provenance[p])))
    windows = [dict(points=[capture(p) for p in live], estimate={"value": 12.345, "confidence": "High"}),
               dict(points=[capture(task)], estimate={"value": None, "confidence": "insufficient"}),
               dict(points=[capture(live[0]), capture(task)], estimate={"value": 67.89, "confidence": "Low/provisional"})]
    before = deepcopy(windows)
    result = display_history(live+[task], provenance, windows, [live[-1]], live_points=live)
    assert result["periods"][0]["fit_indices"] == [0]
    assert result["uncertain"][0]["fit_indices"] == [1]
    assert result["cross_boundary_fit_indices"] == [2]
    assert windows == before
    report = dict(windows=windows, display_history=result, history=windows[:1], qualified=windows[:1], headline=windows[0])
    restored = decode_report(encode_report(report))
    assert restored == report and restored["headline"] is restored["windows"][0]


def test_explicit_loaded_live_membership_is_authority_not_a_forged_display_label():
    live = [point(0, 40), point(2, 50)]
    task = point(1, 1)
    result = display_history(live+[task], {p: {"Live probe"} for p in live+[task]}, [], [live[-1]], live_points=live)
    assert len(result["periods"]) == 1 and len(result["periods"][0]["capture_indices"]) == 2
    assert len(result["uncertain"]) == 1


def test_task_reset_metadata_cannot_fill_missing_official_boundary_evidence():
    live = [point(0, 40, resets_at=None, reset_credits=None), point(2, 50, resets_at=None, reset_credits=None)]
    task = point(1, 45)
    result = build(live, [task], [live[-1]])
    assert len(result["periods"]) == 1 and len(result["periods"][0]["capture_indices"]) == 2
    assert result["periods"][0]["next_reset"] is None
    assert len(result["uncertain"]) == 1
