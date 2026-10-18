"""Tooltip timings include both real input and the observed style response."""
import importlib
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('seconds,limit,passes', [
    (.024, .25, True), (.25, .25, False), (.30, .25, False),
    (.60, 2.0, True), (2.0, 2.0, False),
])
def test_speed_tooltip_response_retains_finite_input_through_style_budget(monkeypatch, seconds, limit, passes):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    harness = importlib.import_module('verification.speed_tooltips')
    calls = []

    def state(tooltip):
        calls.append('style')
        return {'visible': len(calls) > 1, 'hidden': len(calls) == 1}

    ticks = iter([0, seconds/2, seconds])
    monkeypatch.setattr(harness, 'perf_counter', lambda: next(ticks))
    monkeypatch.setattr(harness, 'state', state)
    def action():
        calls.append('input')
    if passes:
        assert harness.observe(None, action, visible=True, limit=limit) == seconds
    else:
        with pytest.raises(AssertionError, match='seconds') as error:
            harness.observe(None, action, visible=True, limit=limit)
        assert error.value.args[0]['input_seconds'] == seconds/2
        assert error.value.args[0]['style_seconds'] == seconds/2
        assert error.value.args[0]['state'] == {'visible': True, 'hidden': False}
    assert calls == ['style', 'input', 'style']


@pytest.mark.parametrize('failure', [False, True])
def test_speed_observation_pins_one_handle_and_disposes_it_on_failure(monkeypatch, failure):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    harness = importlib.import_module('verification.speed_tooltips')
    calls = []
    handle = SimpleNamespace(dispose=lambda: calls.append('dispose'))
    def pin():
        calls.append('pin')
        return handle
    scope = SimpleNamespace(locator=lambda selector: SimpleNamespace(element_handle=pin))
    point = SimpleNamespace(get_attribute=lambda name: 'point-0')
    def inspect(page, parent, target, pinned, **kwargs):
        assert pinned is handle and calls == ['pin']
        calls.append('observe')
        if failure:
            raise AssertionError('preserved failure')
        return {'hover': .01}
    monkeypatch.setattr(harness, '_check_point', inspect)
    if failure:
        with pytest.raises(AssertionError, match='preserved failure'):
            harness.check_point(None, scope, point)
    else:
        assert harness.check_point(None, scope, point) == {'hover': .01}
    assert calls == ['pin', 'observe', 'dispose']
