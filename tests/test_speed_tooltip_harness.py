"""Tooltip timings include both real input and the observed style response."""
import importlib

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

    ticks = iter([0, seconds])
    monkeypatch.setattr(harness, 'perf_counter', lambda: next(ticks))
    monkeypatch.setattr(harness, 'state', state)
    def action():
        calls.append('input')
    if passes:
        assert harness.observe(None, action, visible=True, limit=limit) == seconds
    else:
        with pytest.raises(AssertionError, match='seconds'):
            harness.observe(None, action, visible=True, limit=limit)
    assert calls == ['style', 'input', 'style']
