"""Human reset periods reconcile against usage, not raw fit fragments."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from copy import deepcopy

import pytest

from codex_usage.allowance_cost_pace import CostPrefix
from codex_usage.allowance_display_history import display_history
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_report_codec import decode_report, encode_report
from codex_usage.allowance_reset_economics import reset_history
from codex_usage.allowance_reset_periods import reset_periods

AT = datetime(2026, 10, 1, tzinfo=UTC)


def point(hour, used, deadline=6, **kwargs):
    return replace(QuotaObservation((AT+timedelta(hours=hour)).isoformat(), "codex", "primary", "pro",
        used, 10080, int((AT+timedelta(hours=deadline)).timestamp()), 2), **kwargs)


def prefix(events):
    times, costs, unknown = [], [0.], [0]
    for hour, cost, unpriced in events:
        times.append(AT.timestamp()+hour*3600)
        costs.append(costs[-1]+cost)
        unknown.append(unknown[-1]+unpriced)
    return CostPrefix(times, costs, unknown)


def build(live, tasks=(), events=(), windows=(), *, complete=True):
    points = list(live)+list(tasks)
    provenance = {p: {"Live probe" if p in live else "Task snapshot"} for p in points}
    history = display_history(points, provenance, windows, [live[-1]], live_points=set(live))
    return history, reset_history(history, set(live), [live[-1]], windows, prefix(events), coverage_complete=complete)


def test_unchanged_reset_credits_still_produce_actual_early_reset_periods():
    live = [point(0, 80), point(.9, 90), point(1, 0, 8), point(2, 20, 8),
            point(3, 40, 8), point(4, 0, 10), point(5, 25, 10)]
    tasks = [point(.95, 0, 8), point(3.95, 0, 10), point(4.1, 95, 8)]
    events = [(h, cost, 0) for h, cost in ((.94, 1), (.95, 2), (1, 3), (3.94, 5), (3.95, 7), (4, 11), (5, 13))]
    raw, result = build(live, tasks, events)
    current, closed, initial = result["periods"]
    assert len(result["periods"]) == 3
    assert current["start"] == closed["end"] == AT.timestamp()+3.95*3600
    assert closed["start"] == initial["end"] == AT.timestamp()+.95*3600
    assert current["next_reset"] == live[-1].resets_at
    assert [p["allowance_used"] for p in result["periods"]] == [25, 40, 90]
    assert [p["usage_usd"] for p in result["periods"]] == [31, 10, 1]
    assert sum(p["usage_usd"] for p in result["periods"]) == sum(c for _, c, _ in events)
    assert closed["usage_usd_min"] == 5 and closed["usage_usd_max"] == 11
    stale = next(i for i, p in enumerate(raw["captures"]) if p["timestamp"] == tasks[-1].timestamp)
    assert not any(stale in p["capture_indices"] for p in result["periods"])
    assert any(stale in p["capture_indices"] for p in result["uncertain"])


def test_weekly_meter_does_not_reset_when_shared_reset_credits_decrease_alone():
    live = [point(0, 20), point(1, 25, reset_credits=1), point(2, 30, reset_credits=1)]
    _, history = build(live)
    assert len(history["periods"]) == 1 and history["periods"][0]["allowance_used"] == 30


def test_deadline_rebase_without_restart_and_clock_jitter_are_not_new_periods():
    live = [point(0, 20), point(1, 21, 7), point(2, 22, 7, resets_at=point(2, 22, 7).resets_at+59)]
    _, history = build(live)
    assert len(history["periods"]) == 1


def test_small_restart_with_changed_deadline_is_still_an_early_reset():
    live = [point(0, 3), point(1, 0, 8), point(2, 1, 8)]
    _, history = build(live)
    assert len(history["periods"]) == 2
    assert history["periods"][0]["boundary"] == "early reset"


def test_one_transient_official_deadline_does_not_create_a_reset():
    live = [point(0, 80), point(1, 0, 8), point(2, 85), point(3, 90)]
    _, history = build(live)
    assert len(history["periods"]) == 1


def test_missing_clock_metadata_does_not_erase_previous_reset_evidence():
    live = [point(0, 80), point(.5, 85, resets_at=None), point(1, 0, 8), point(2, 10, 8)]
    _, history = build(live)
    assert len(history["periods"]) == 2


def test_scheduled_reset_survives_missing_clock_across_the_deadline():
    live = [point(0, 80), point(7, 10, resets_at=None), point(8, 20, 14)]
    _, history = build(live)
    assert len(history["periods"]) == 2
    assert history["periods"][0]["reset_opening"]["earliest"] == AT.timestamp()+6*3600
    assert history["periods"][0]["reset_opening"]["latest"] == AT.timestamp()+6*3600
    assert history["periods"][0]["observed_start"] == AT.timestamp()+7*3600
    assert [p["meter_end"] for p in history["periods"]] == [20, 80]


def test_delayed_early_reset_clock_preserves_the_baseline_time_and_cost_uncertainty():
    live = [point(0, 80), point(1, 0, resets_at=None), point(2, 20, 8)]
    _, history = build(live, events=[(.5, 10, 7), (2, 20, 0)])
    current, previous = history["periods"]
    assert current["reset_opening"]["earliest"] == AT.timestamp()
    assert current["reset_opening"]["latest"] == AT.timestamp()+2*3600
    assert current["usage_usd_min"] == 20 and current["usage_usd_max"] == 30
    assert current["unpriced_tokens_max"] == 7
    assert previous["meter_end"] == 80


def test_consecutive_early_resets_do_not_require_repeated_intermediate_deadline():
    live = [point(0, 80), point(1, 30, 8), point(2, 0, 10)]
    _, history = build(live)
    assert len(history["periods"]) == 3


def test_clock_only_rebase_after_reset_does_not_discard_that_reset():
    live = [point(0, 80), point(1, 0, 8), point(2, 10, 9)]
    _, history = build(live)
    assert len(history["periods"]) == 2


def test_multiple_active_limits_do_not_duplicate_account_dollars():
    live = [point(0, 20), point(1, 30)]
    other = [point(0, 10, limit_id="review"), point(1, 20, limit_id="review")]
    raw, _ = build(live, other)
    history = reset_history(raw, set(live+other), [other[-1], live[-1]], [],
                            prefix([(0, 10, 0), (1, 20, 0)]), coverage_complete=True)
    assert len(history["periods"]) == 1
    assert history["periods"][0]["limit_id"] == "codex"
    assert history["periods"][0]["usage_usd"] == 30


def test_plan_change_is_not_reported_as_an_actual_reset():
    live = [point(0, 20), point(1, 30, plan="plus"), point(2, 40, plan="plus")]
    raw, history = build(live, events=[(0, 10, 0), (1, 20, 0), (2, 30, 0)])
    current, previous = history["periods"]
    assert current["reset_opening"] is None and previous["reset_closure"] is None
    assert current["identity_opening"]["kind"] == "plan change"
    assert previous["identity_closure"]["kind"] == "plan change"
    assert [p["usage_usd"] for p in history["periods"]] == [50, 10]
    report = dict(display_history=raw, reset_history=history, windows=[], qualified=[], history=[], headline=None)
    assert decode_report(encode_report(report)) == report


def test_possible_boundary_usage_retains_unknown_price_coverage():
    live = [point(0, 80), point(1, 0, 8), point(2, 20, 8)]
    _, history = build(live, events=[(.5, 0, 7)])
    current = history["periods"][0]
    assert current["unpriced_tokens"] == 0
    assert current["unpriced_tokens_max"] == 7


def test_conflicting_task_candidates_do_not_choose_a_precise_reset_time():
    live = [point(0, 80), point(1, 0, 8), point(2, 20, 8)]
    tasks = [point(.5, 0, 8), point(.5, 70, 8)]
    _, history = build(live, tasks)
    assert history["periods"][0]["start"] == AT.timestamp()+3600
    assert history["periods"][0]["reset_opening"]["earliest"] == AT.timestamp()


def test_only_active_weekly_series_is_primary_not_five_hour_or_other_limit():
    live = [point(0, 20), point(1, 30)]
    other = [point(0, 10, duration_minutes=300), point(1, 20, limit_id="review")]
    raw, _ = build(live, other)
    periods, _ = reset_periods(raw["captures"], set(live+other), [live[-1], other[0]])
    assert len(periods) == 1 and periods[0]["duration_minutes"] == 10080
    assert periods[0]["limit_id"] == "codex"


def test_conflicting_simultaneous_official_readings_do_not_choose_a_plan():
    live = [point(0, 20), point(1, 30), point(1, 40, plan="plus"), point(2, 50)]
    raw, history = build(live)
    assert len(history["periods"]) == 1
    assert history["periods"][0]["allowance_used"] == 50
    disputed = {i for i, p in enumerate(raw["captures"]) if p["timestamp"] == live[1].timestamp}
    assert not disputed & set(history["periods"][0]["capture_indices"])


def test_period_value_selects_one_contained_fit_never_sums_or_averages():
    live = [point(0, 80), point(1, 0, 8), point(2, 20, 8), point(3, 40, 8)]
    def window(points, value, span, priced=True):
        return dict(points=[dict(p.to_dict(), provenance="Live probe") for p in points],
            limit_id="codex", duration_minutes=10080, plan="pro", start=points[0].timestamp, end=points[-1].timestamp,
            estimate=dict(value=value, confidence="Low/provisional", span=span), fully_priced=priced)
    windows = [window(live[1:], 50, 40), window(live[2:], 500, 20), window(live, 999, 80),
               window(live[1:], 900, 60, priced=False)]
    raw, history = build(live, windows=windows)
    current = history["periods"][0]
    assert current["allowance_value"] == 50 and current["allowance_fit_index"] == 0
    report = dict(display_history=raw, reset_history=history, windows=windows, qualified=[], history=[], headline=None)
    restored = decode_report(encode_report(report))
    assert restored == report
    assert restored["reset_history"]["captures"] is restored["display_history"]["captures"]


def test_total_usage_keeps_credit_funded_tail_and_unknown_coverage():
    live = [point(0, 0), point(1, 50), point(2, 100), point(3, 100)]
    _, history = build(live, events=[(0, 10, 0), (1, 20, 0), (2, 30, 0), (3, 40, 7)], complete=False)
    period = history["periods"][0]
    assert period["usage_usd"] == 100 and period["allowance_used"] == 100
    assert period["unpriced_tokens"] == 7 and not period["coverage_complete"]
    assert period["allowance_value"] is None


def test_fits_after_first_full_meter_cannot_calibrate_the_same_period():
    live = [point(0, 100), point(1, 10), point(2, 20), point(3, 30), point(4, 40), point(5, 50)]
    window = dict(points=[dict(p.to_dict(), provenance="Live probe") for p in live[1:]],
        limit_id="codex", duration_minutes=10080, plan="pro", start=live[1].timestamp,
        end=live[-1].timestamp, estimate=dict(value=10, confidence="Low/provisional", span=40), fully_priced=True)
    _, history = build(live, windows=[window])
    assert history["periods"][0]["allowance_value"] is None


def test_valid_pre_full_fit_is_retained_when_raw_window_has_a_credit_tail(tmp_path):
    from release_tooling_support import load_tool
    report = load_tool("allowance_period_fixture").reset_economics_fixture(tmp_path)
    original = report["reset_history"]["periods"][0]["allowance_value"]
    current = [point(0, i*10) for i in range(6)]
    current = [replace(p, timestamp=(AT+timedelta(hours=i)).isoformat()) for i, p in enumerate(current)]
    current += [point(6, 100), point(7, 100)]
    window = dict(points=[dict(p.to_dict(), provenance="Live probe") for p in current],
        limit_id="codex", duration_minutes=10080, plan="pro", start=current[0].timestamp,
        end=current[-1].timestamp, fit_end=current[5].timestamp,
        estimate=dict(value=original, confidence="Low/provisional", span=50), fully_priced=True)
    _, history = build(current, windows=[window])
    assert original is not None and history["periods"][0]["allowance_value"] == original


@pytest.mark.parametrize("damage", [{"usage_usd": float("nan")}, {"allowance_used": 120},
    {"usage_usd_min": 1e30}, {"unpriced_tokens": True}, {"allowance_value": 999}])
def test_reset_codec_rejects_invalid_summary_totals(damage):
    raw, history = build([point(0, 20), point(1, 30)], events=[(1, 5, 0)])
    history = deepcopy(history)
    history["periods"][0].update(damage)
    with pytest.raises(ValueError, match="reset|Reset"):
        encode_report(dict(display_history=raw, reset_history=history,
                           windows=[], history=[], qualified=[], headline=None))
