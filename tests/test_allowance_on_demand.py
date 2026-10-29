"""The real initial dashboard must avoid details while retaining current math."""
import json
from contextlib import nullcontext
from unittest.mock import patch

import pytest

from codex_usage.agent_reports import render_ledger_report
from codex_usage.allowance_history_navigation import DEFAULT_STATE
from codex_usage.allowance_index import indexed_allowance_report
from codex_usage.allowance_queries import allowance_status, build_allowance_report
from codex_usage.ledger_schema import ledger_revision, open_ledger
from test_allowance_window_cache import AT, breakdown_home


def render(path, **kwargs):
    return render_ledger_report(path.parent.parent, range_name='today', project_keys=[],
        theme='auto', timezone_name='UTC', now=AT, **kwargs)


def current(report):
    def summary(window):
        return None if window is None else {k: v for k, v in window.items() if k != 'points'}
    result = {key: value for key, value in report.items() if key not in
              {'display_history', 'reset_history', 'history_deferred'}}
    for key in ('windows', 'qualified', 'history'):
        result[key] = [summary(window) for window in report[key]]
    result['headline'] = summary(report['headline'])
    return result


@pytest.mark.parametrize('first', ['deferred', 'eager'])
def test_deferred_initial_avoids_detail_work_and_both_cache_orders_remain_exact(tmp_path, first):
    path = breakdown_home(tmp_path, extended=True)
    with open_ledger(path, read_only=True) as c:
        c.execute('begin')
        status = allowance_status(c, now=AT)
        expected = build_allowance_report(c, status=status)
    for mode in (first, 'eager' if first == 'deferred' else 'deferred', 'eager', 'deferred'):
        with open_ledger(path, read_only=True) as c:
            c.execute('begin')
            with patch('codex_usage.allowance_display_history.display_history',
                       side_effect=AssertionError('constructed detail history')) if mode == 'deferred' else nullcontext():
                actual = indexed_allowance_report(c, path, revision=ledger_revision(c),
                    pricing_revision='p1', coverage_complete=True, status=status,
                    include_history=mode == 'eager')
        if mode == 'eager':
            assert actual == expected
        else:
            assert actual['history_deferred'] is True
            assert current(actual) == current(expected)


def test_actual_dashboard_issues_load_without_history_then_prepares_exact_requested_page(tmp_path):
    path = breakdown_home(tmp_path, extended=True)
    with patch('codex_usage.allowance_display_history.display_history',
               side_effect=AssertionError('display history before user request')), patch(
                   'codex_usage.allowance_reset_economics.reset_history',
                   side_effect=AssertionError('reset history before user request')):
        first = render(path, allowance_history='deferred')
        warm = render(path, allowance_history='deferred')
    assert 'Load allowance history' in first.html
    assert first.allowance_navigation['deferred'] is True
    assert warm.allowance_navigation == first.allowance_navigation
    assert first.allowance_navigation['state'] == DEFAULT_STATE
    action = first.allowance_navigation['actions'][0]
    loaded = render(path, allowance_history='requested', allowance_action=json.dumps(action))
    eager = render(path)
    assert first.status.coverage.complete  # Full-coverage current calibration also remains exact.
    assert 'Load allowance history' not in loaded.html
    assert loaded.allowance_navigation == eager.allowance_navigation
    assert loaded.html.replace('<details class="allowance-history-panel" open>',
                               '<details class="allowance-history-panel">') == eager.html


def test_valid_eager_html_can_serve_initial_invitation_without_repreparing_current_math(tmp_path):
    path = breakdown_home(tmp_path, extended=True)
    eager = render(path)
    with (patch('codex_usage.agent_reports.indexed_allowance_report', side_effect=AssertionError('reprepared')),
          patch('codex_usage.breakdown_reports.indexed_allowance_report', side_effect=AssertionError('reprepared'))):
        deferred = render(path, allowance_history='deferred')
    assert deferred.cache_hit and deferred.status == eager.status
    assert 'Load allowance history' in deferred.html


@pytest.mark.parametrize('mode', ['', 'automatic', 'false'])
def test_unsupported_history_modes_fail_explicitly(tmp_path, mode):
    path = breakdown_home(tmp_path)
    with pytest.raises(ValueError, match='history mode'):
        render(path, allowance_history=mode)


@pytest.mark.parametrize('damage', ['malformed', 'wrong-format', 'full-in-deferred', 'deferred-in-full',
                                   'inner-in-full', 'missing-fields', 'wrong-shape'])
def test_cache_corruption_and_cross_mode_payloads_rebuild_without_poisoning_eager(tmp_path, damage):
    from codex_usage.allowance_index import _revisions
    from codex_usage.allowance_on_demand import DEFERRED_SUFFIX
    path = breakdown_home(tmp_path, extended=True)
    def indexed(include):
        with open_ledger(path, read_only=True) as c:
            c.execute('begin')
            return indexed_allowance_report(c, path, revision=ledger_revision(c), pricing_revision='p1',
                coverage_complete=True, status=allowance_status(c, now=AT), include_history=include)
    expected = indexed(True)
    projected = indexed(False)
    _, key = _revisions('p1')
    with open_ledger(path) as c:
        full = c.execute('select report_json from allowance_report_cache where pricing_revision=?', (key,)).fetchone()[0]
        deferred = c.execute('select report_json from allowance_report_cache where pricing_revision=?',
                             (key+DEFERRED_SUFFIX,)).fetchone()[0]
        target = key if damage in ('deferred-in-full', 'inner-in-full') else key+DEFERRED_SUFFIX
        payload = {'malformed':'{', 'wrong-format':'{"format":"unknown"}',
                   'full-in-deferred':full, 'deferred-in-full':deferred,
                   'inner-in-full':json.dumps(json.loads(deferred)['payload']),
                   'missing-fields':json.dumps(dict(format='allowance-deferred-history-1', payload={})),
                   'wrong-shape':json.dumps(dict(format='allowance-deferred-history-1',
                       payload=dict(format='allowance-window-references-3', report=[])))}[damage]
        c.execute('update allowance_report_cache set report_json=? where pricing_revision=?', (payload, target))
        c.commit()
    assert indexed(False) == projected
    assert indexed(True) == expected


def test_requested_selection_survives_filters_but_rejects_other_evidence_and_home(tmp_path):
    from codex_usage.allowance_history_navigation import AllowanceScopeExpired
    from codex_usage.ledger_schema import increment_ledger_revision
    path = breakdown_home(tmp_path/'first', extended=True)
    initial = render(path, allowance_history='deferred')
    loaded = render(path, allowance_history='requested',
                    allowance_action=json.dumps(initial.allowance_navigation['actions'][0]))
    selected = next(a for a in loaded.allowance_navigation['actions'] if a['state']['kind'] == 'periods')
    detail = render(path, allowance_history='requested', allowance_action=json.dumps(selected))
    retained = next(a for a in detail.allowance_navigation['actions'] if a['state'] == detail.allowance_navigation['state'])
    # An eager API client shares this page/receipt identity; it must not erase
    # the requested panel's valid account/evidence portability binding.
    render(path, allowance_action=json.dumps(retained))
    filtered = render_ledger_report(path.parent.parent, range_name='30d', project_keys=['different'], theme='auto',
        timezone_name='UTC', now=AT, allowance_history='requested', allowance_action=json.dumps(retained))
    assert filtered.allowance_navigation['state'] == detail.allowance_navigation['state']
    assert filtered.allowance_navigation['scope'] != retained['scope']
    with pytest.raises(AllowanceScopeExpired):
        render_ledger_report(path.parent.parent, range_name='30d', project_keys=[], theme='auto',
            timezone_name='America/Toronto', now=AT, allowance_history='requested', allowance_action=json.dumps(retained))
    other = breakdown_home(tmp_path/'other', extended=True)
    with pytest.raises(ValueError, match='Unissued'):
        render(other, allowance_history='requested', allowance_action=json.dumps(retained))
    with open_ledger(path) as c:
        increment_ledger_revision(c)
        c.commit()
    with pytest.raises(AllowanceScopeExpired):
        render(path, allowance_history='requested', allowance_action=json.dumps(retained))
    recovered = render(path, allowance_history='requested')
    assert 'Load allowance history' not in recovered.html
