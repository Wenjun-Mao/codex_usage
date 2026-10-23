"""Only issued allowance scope hashes may differ in codec benchmarks."""
import json
from pathlib import Path
from urllib.parse import quote

import pytest

from codex_usage.allowance_history_navigation import DEFAULT_STATE


def example(scope, state=None):
    action = dict(scope=scope, state=dict(DEFAULT_STATE if state is None else state))
    uri = 'command:codexUsage.navigateAllowanceHistory?' + quote(json.dumps([action], separators=(',', ':')), safe='')
    return '<a href="'+uri+'">Details $1.23</a>', dict(scope=scope, actions=[action])


def test_only_validated_scope_can_be_normalized(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    from benchmark_collector import allowance_scope_html
    first, a = example('a'*64)
    second, b = example('b'*64)
    assert allowance_scope_html(first, a) == allowance_scope_html(second, b)
    assert allowance_scope_html(first, a) != allowance_scope_html(second.replace('$1.23', '$1.24'), b)
    changed, c = example('b'*64, dict(DEFAULT_STATE, period_page=1))
    assert allowance_scope_html(first, a) != allowance_scope_html(changed, c)
    with pytest.raises(ValueError, match='not issued'):
        allowance_scope_html(first, b)
    with pytest.raises(ValueError, match='not issued'):
        allowance_scope_html(first, dict(a, actions=[]))
