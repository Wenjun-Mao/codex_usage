"""Canonical companion transport reuses accounting, while direct themes remain exact."""
from contextlib import ExitStack
from datetime import timedelta
import json
from pathlib import Path
from runpy import run_path
from unittest.mock import patch

import pytest

import codex_usage.agent_reports as base
import codex_usage.breakdown_reports as breakdown
from codex_usage.ledger_schema import increment_ledger_revision, open_ledger

fixture = run_path(str(Path(__file__).resolve().parents[1] / 'scripts/usage_breakdown_fixture.py'))
AT, home_fixture = fixture['AT'], fixture['breakdown_home']


def render(home, theme='auto', **kwargs):
    return base.render_ledger_report(home, range_name='30d', project_keys=[],
        theme=theme, timezone_name='UTC', now=kwargs.pop('now', AT), **kwargs)


def normalized(report, theme):
    html = report.html.replace(f'data-codex-theme="{theme}"', 'data-codex-theme="auto"', 1)
    for name in ('speed_navigation', 'breakdown_navigation', 'allowance_navigation'):
        navigation = getattr(report, name)
        if navigation:
            html = html.replace(navigation['scope'], name)
    return html


@pytest.mark.parametrize('theme', ['day', 'night', 'auto'])
def test_direct_theme_numeric_membership_and_all_issued_states_match_canonical(tmp_path, theme):
    home_fixture(tmp_path, extended=True)
    canonical = render(tmp_path)
    direct = render(tmp_path, theme)
    assert normalized(canonical, 'auto') == normalized(direct, theme)
    assert canonical.status == direct.status
    for name in ('speed_navigation', 'breakdown_navigation', 'allowance_navigation'):
        first, second = getattr(canonical, name), getattr(direct, name)
        assert first is not None and second is not None
        assert {k: v for k, v in first.items() if k != 'scope' and k != 'actions'} == {
            k: v for k, v in second.items() if k != 'scope' and k != 'actions'}
        if 'actions' in first:
            assert [a['state'] for a in first['actions']] == [a['state'] for a in second['actions']]


def test_warm_canonical_theme_requests_do_no_accounting_or_capture_and_keep_actions(tmp_path):
    home_fixture(tmp_path, extended=True)
    origin = render(tmp_path)
    with ExitStack() as stack:
        for module, name in [(base, 'materialize_ledger'), (base, 'indexed_allowance_report'),
                (breakdown, 'prepare_evidence'), (breakdown, 'query_ledger_records')]:
            stack.enter_context(patch.object(module, name, side_effect=AssertionError(name+' on warm theme')))
        stack.enter_context(patch('codex_usage.agent_capture.capture_once', side_effect=AssertionError('capture')))
        for _display in ('day', 'auto', 'night'):
            warm = render(tmp_path)
            assert warm.cache_hit
            assert warm.html == origin.html
            assert warm.breakdown_navigation == origin.breakdown_navigation
            assert warm.allowance_navigation == origin.allowance_navigation
    for report_theme in ('auto', 'day', 'night'):
        report = render(tmp_path, report_theme)
        action = next(a for a in report.breakdown_navigation['actions'] if a['state']['metric'] == 'tokens')
        navigated = render(tmp_path, report_theme, breakdown_action=json.dumps(action))
        assert navigated.breakdown_navigation['state']['metric'] == 'tokens'
        history = navigated.allowance_navigation['actions'][0]
        assert render(tmp_path, report_theme, allowance_action=json.dumps(history)).allowance_navigation['state'] == history['state']


@pytest.mark.parametrize('change', ['revision', 'midnight'])
def test_canonical_transport_does_not_bypass_real_invalidation(tmp_path, change):
    path = home_fixture(tmp_path, extended=True)
    origin = render(tmp_path)
    if change == 'revision':
        with open_ledger(path) as connection:
            increment_ledger_revision(connection)
            connection.commit()
    with patch.object(base, 'materialize_ledger', wraps=base.materialize_ledger) as materialize:
        result = render(tmp_path, now=AT+timedelta(days=1) if change == 'midnight' else AT)
    assert not result.cache_hit
    assert materialize.call_count > 0
    assert result.ledger_revision >= origin.ledger_revision
