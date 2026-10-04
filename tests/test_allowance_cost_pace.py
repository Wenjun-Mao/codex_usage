"""Hand-computable calibrated rates, causal references and fallback contracts."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_cost_pace import CostPrefix, PaceReferences, calibrated_paces
from codex_usage.allowance_pace import fit_paces, pace_state
from codex_usage.allowance_pace_evidence import prepare_pace_evidence
from codex_usage.report_allowance_pace import pace_details, pace_rows

BASE = datetime(2026, 10, 1, tzinfo=UTC)


def point(hour, used=20, **changes):
    return replace(QuotaObservation(
        (BASE + timedelta(hours=hour)).isoformat(), 'codex', 'primary', 'pro', used,
        10080, int((BASE + timedelta(days=7)).timestamp()), 3), **changes)


def reference(start=-24, end=-1, value=1000, **changes):
    result = {'limit_id': 'codex', 'plan': 'pro', 'duration_minutes': 10080,
              'start': point(start).timestamp, 'end': point(end).timestamp,
              'fully_priced': True, 'estimate': {'value': value, 'confidence': 'Low/provisional'}}
    result.update(changes)
    return result


def prefix(events):
    times, costs, unpriced = [], [0.0], [0]
    for hour, cost, missing in events:
        times.append((BASE + timedelta(hours=hour)).timestamp())
        costs.append(costs[-1] + cost)
        unpriced.append(unpriced[-1] + missing)
    return CostPrefix(times, costs, unpriced)


def fit(points, events, refs=None, *, live=True, coverage=True):
    anchor = points[-1]
    prepared = prepare_pace_evidence(points, {anchor} if live else set())
    return calibrated_paces(prepared, anchor, fit_paces(prepared, anchor), prefix(events),
                            PaceReferences(refs or [reference(), reference(0, len(points), value=None)]),
                            coverage_complete=coverage)


def test_flat_meter_positive_cost_and_partial_spans_have_no_regression_gates():
    points = [point(0), point(.25), point(.5)]
    rows = fit(points, [(0, 999, 0), (.25, 2, 0), (.5, 3, 0)])
    for row in rows:
        assert row['rate'] == 1
        assert row['cost'] == 5 and row['span_seconds'] == 1800
        assert row['exhaustion'] == (BASE + timedelta(hours=80.5)).timestamp()
        assert row['reset_balance'] == -87.5
        assert row['method'] == 'calibrated cost'
        assert row['reference']['value'] == 1000
        assert pace_state(row, 'fresh', row['anchor']) == 'ready'
    assert rows[1]['observations'] == 3  # Daily's five-point gate is only a meter gate.
    assert '(estimated)' in pace_rows(rows, 'fresh', timezone=ZoneInfo('UTC'), now=BASE+timedelta(hours=.5))


def test_recent_daily_and_multiday_cycle_share_one_reference_and_actual_endpoints():
    points = [point(h) for h in (0, 12, 24, 47, 47.5, 48)]
    rows = fit(points, [(12, 10, 0), (24, 10, 0), (47, 20, 0), (47.5, 1, 0), (48, 1, 0)])
    assert [r['cost'] for r in rows] == [2, 22, 42]
    assert [r['span_seconds'] for r in rows] == [3600, 86400, 172800]
    assert [r['rate'] for r in rows] == pytest.approx([.2, 22/240, 42/480])
    assert all(r['reference'] == rows[0]['reference'] for r in rows)


def test_current_reference_replaces_previous_for_all_rows_and_future_is_unavailable():
    points = [point(0), point(.5), point(1)]
    earlier, current = reference(), reference(0, 1, 500)
    previous = fit(points, [(1, 10, 0)], [earlier, reference(0, 1, None)])
    current_rows = fit(points, [(1, 10, 0)], [earlier, current, reference(1, 2, 1)])
    assert all(r['reference']['previous'] for r in previous)
    assert all(not r['reference']['previous'] for r in current_rows)
    assert [r['rate'] for r in current_rows] == [2*r['rate'] for r in previous]
    assert all(r['reference']['value'] == 500 for r in current_rows)


@pytest.mark.parametrize('changes', [{'plan': 'plus'}, {'plan': ''}, {'limit_id': 'other'},
    {'duration_minutes': 300}, {'fully_priced': False}, {'estimate': {'value': 0, 'confidence': 'High'}},
    {'estimate': {'value': float('nan'), 'confidence': 'Medium'}}])
def test_incompatible_or_invalid_reference_cannot_be_borrowed(changes):
    rows = fit([point(0), point(.5), point(1)], [(1, 10, 0)], [reference(**changes)])
    assert all(r['rate'] is None and r['calibrated_reason'] == 'no compatible priced reference' for r in rows)


def test_unknown_identity_exact_anchor_and_conflicts_cannot_create_calibrated_rate():
    for points, live in [([point(0, plan=''), point(1, plan='')], True),
                         ([point(0), point(1)], False),
                         ([point(0), point(1, 21), point(1)], True)]:
        assert all(r['rate'] is None for r in fit(points, [(1, 10, 0)], live=live))
    # A missing live plan may use the causally known plan, not a future identity.
    rows = fit([point(0), point(1, plan='')], [(1, 10, 0)])
    assert rows[0]['rate'] == 1


def test_zero_priced_cost_is_observed_zero_but_unpriced_and_incomplete_are_not():
    points = [point(0), point(.5), point(1)]
    rows = fit(points, [(1, 0, 0)])
    assert all(r['rate'] == 0 and r['exhaustion'] is None and r['reset_balance'] == 80 for r in rows)
    assert pace_state(rows[0], 'fresh', rows[0]['anchor']) == 'ready'
    assert '80% would remain' in pace_rows(rows, 'fresh', timezone=ZoneInfo('UTC'), now=BASE+timedelta(hours=1))
    assert all(r['rate'] is None for r in fit(points, [(1, 0, 1)]))
    assert all(r['rate'] is None for r in fit(points, [], coverage=False))
    assert 'unpriced period usage' in pace_details([fit(points, [(1, 0, 1)])], 'fresh', now=BASE+timedelta(hours=1))


@pytest.mark.parametrize('change', [{'reset_credits': 2}, {'resets_at': int((BASE+timedelta(days=8)).timestamp())}, {'plan': 'plus'}])
def test_boundaries_clip_credit_funded_or_preceding_cost(change):
    points = [point(-1, 100), point(0, 99, **change), point(.5, 99, **change), point(1, 99, **change)]
    refs = [reference(plan=change.get('plan', 'pro'))]
    rows = fit(points, [(-.5, 999, 0), (0, 999, 0), (.5, 2, 0), (1, 3, 0)], refs)
    assert all(r['cost'] == 5 and r['rate'] == .5 and r['span_seconds'] == 3600 for r in rows)


def test_raw_full_cutoff_survives_small_correction_and_conflicting_same_time_point():
    points = [point(0, 95), point(.5, 100), point(1, 99), point(1.5, 99.5)]
    assert all(r['method'] == 'direct meter' and r['calibrated_reason'] == 'reported-full cost cutoff'
               for r in fit(points, [(1.5, 1000, 0)]))
    points.insert(1, point(.5, 99))
    assert all(r['method'] == 'direct meter' for r in fit(points, [(1.5, 1000, 0)]))


def test_unpriced_cost_falls_back_to_plain_daily_signed_elapsed_average():
    points = [point(i, used) for i, used in enumerate([10, 13, 12, 13, 14])]
    daily = fit(points, [(4, 1, 1)])[1]
    assert daily['method'] == 'direct meter' and daily['rate'] == 1
    assert daily['calibrated_reason'] == 'unpriced period usage'


def test_reference_indexes_select_each_bucket_independently_and_ignore_slots():
    references = PaceReferences([reference(value=1000), reference(value=200, duration_minutes=300),
                                 reference(value=500, limit_id='other')])
    for changes, value in [({}, 1000), ({'duration_minutes': 300}, 200), ({'limit_id': 'other'}, 500),
                           ({'slot': 'secondary'}, 1000)]:
        assert references.select(point(1, **changes), 'pro')['value'] == value


def test_unrounded_local_reset_comparison_and_zero_expiry():
    reset = int((BASE+timedelta(hours=81)).timestamp())
    rows = fit([point(0, resets_at=reset), point(1, resets_at=reset)], [(1, 10, 0)])
    assert rows[0]['exhaustion'] == rows[0]['reset']
    assert 'near reset' in pace_rows(rows, 'fresh', timezone=ZoneInfo('America/Toronto'), now=BASE+timedelta(hours=1))
    zero = fit([point(0), point(1)], [])
    assert pace_state(zero[0], 'fresh', zero[0]['anchor']+1800) == 'awaiting'
    missing = fit([point(0), point(1, resets_at=None)], [(1, 10, 0)])
    assert missing[0]['rate'] == 1 and missing[0]['reset_balance'] is None
    assert pace_state(missing[0], 'fresh', missing[0]['anchor']) == 'missing reset'


def test_report_causal_reference_fitting_preserves_monetary_windows(tmp_path, monkeypatch):
    from codex_usage.allowance_probe import QuotaRead
    from codex_usage.allowance_queries import _build_from_costs
    from codex_usage.allowance_store import store_read, store_observations
    from codex_usage.ledger_schema import open_ledger
    import codex_usage.allowance_cost_pace as cost_pace

    points = [point(h, 10+5*h) for h in range(5)]
    points += [point(5, 30), point(6, 30)]
    # Future evidence could substantially change the current monetary fit.
    future = [point(h, 30+5*(h-6)) for h in range(7, 12)]
    events = [(h, 50 if h < 5 else 10 if h <= 6 else 500, 0) for h in range(1, 12)]
    priced = [(BASE.timestamp()+h*3600, c, u) for h, c, u in events]
    with open_ledger(tmp_path/'ledger.sqlite3') as connection:
        connection.execute("insert into capture_runs (started_at, completed_at, request_kind, outcome, ledger_revision, stats_json, error) values (?, ?, ?, ?, ?, ?, ?)",
                           (points[-1].timestamp, points[-1].timestamp, 'manual', 'success', 0, '{}', ''))
        run = connection.execute('select max(run_id) from capture_runs').fetchone()[0]
        for p in points:
            store_read(connection, QuotaRead(p.timestamp, 'pro', (p,)), run)
        before = _build_from_costs(connection, priced)
        assert all(r['method'] == 'calibrated cost' and r['rate'] > 0 for r in before['paces'][0])
        store_observations(connection, future, source_key='future', provenance='parsed')
        after = _build_from_costs(connection, priced)
        assert after['paces'] == before['paces']
        assert after['windows'] != before['windows']  # Full dollar history remains retrospective.
        monkeypatch.setattr(cost_pace, 'calibrated_paces', lambda prepared, anchor, direct, *args, **kw: direct)
        monetary_baseline = _build_from_costs(connection, priced)
        for key in ('windows', 'qualified', 'headline', 'headline_previous', 'history', 'credits'):
            assert after[key] == monetary_baseline[key]


def test_conflicting_full_read_then_supported_reset_restores_included_cost():
    points = [point(-1, 98), point(-.5, 99), point(-.5, 100),
              point(0, 99, reset_credits=2), point(.5, 99, reset_credits=2), point(1, 99, reset_credits=2)]
    rows = fit(points, [(0, 1000, 0), (.5, 2, 0), (1, 3, 0)])
    assert all(r['rate'] == .5 and r['cost'] == 5 for r in rows)


def test_missing_live_plan_uses_causal_limit_wide_plan_and_rejects_conflicting_identity():
    points = [point(0), point(.5), point(.75, plan='plus', duration_minutes=300),
              point(1, plan=''), point(1.5, plan=''), point(2, plan='')]
    rows = fit(points, [(1, 1000, 0), (1.5, 2, 0), (2, 3, 0)],
               [reference(value=100), reference(plan='plus', value=1000)])
    assert all(r['reference']['plan'] == 'plus' and r['rate'] == .5 for r in rows)
    # Contradictory known plans across durations at the origin cannot pick an
    # arbitrary alphabetical identity, even when the own bucket names a plan.
    points += [point(2, plan='plus', duration_minutes=300), point(2, plan='pro', duration_minutes=300)]
    points.append(point(2))
    rows = fit(points, [(2, 5, 0)])
    assert all(r['reference'] is None for r in rows)


def test_zero_cost_preserves_fractional_remaining_rounding():
    rows = fit([point(0, 99.8), point(1, 99.8)], [])
    assert all(r['rate'] == 0 and r['exhaustion'] is None for r in rows)
    html = pace_rows(rows, 'fresh', timezone=ZoneInfo('UTC'), now=BASE+timedelta(hours=1))
    assert 'less than 1% would remain at reset' in html
    assert 'About 0%' not in html
