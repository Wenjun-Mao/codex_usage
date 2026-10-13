"""Late visible results, corrective focus and lingering triggers cannot pass."""
from types import SimpleNamespace
import inspect

import pytest

from release_tooling_support import load_tool

observation = load_tool("verification.hover_observation")


@pytest.mark.parametrize("delay,passes", ((.1, True), (.249, True), (.25, False), (.273, False)))
def test_input_and_style_read_share_strict_absolute_budget(monkeypatch, delay, passes):
    now = [0.0]
    monkeypatch.setattr(observation, "perf_counter", lambda: now[0])
    calls = []
    state = {"visible": True, "hidden": False, "active": True, "focusVisible": True, "hover": False}

    def sample(_):
        calls.append("style")
        now[0] += delay / 2
        return state

    def action():
        calls.append("real input")
        now[0] += delay / 2

    args = (SimpleNamespace(wait_for_timeout=lambda _: None), SimpleNamespace(evaluate=sample), action)
    if passes:
        assert observation.observe_input(*args, visible=True, keyboard=True, phase="keyboard") == delay
    else:
        with pytest.raises(AssertionError):
            observation.observe_input(*args, visible=True, keyboard=True, phase="keyboard")
    assert calls == ["real input", "style"]


@pytest.mark.parametrize("fault", ("active", "focusVisible", "hover"))
def test_keyboard_observation_requires_real_target_modality_without_hover_masking(monkeypatch, fault):
    now = [0.0]
    monkeypatch.setattr(observation, "perf_counter", lambda: now[0])
    state = {"visible": True, "hidden": False, "active": True, "focusVisible": True, "hover": False}
    state[fault] = fault == "hover"

    def sample(_):
        now[0] += .1
        return state

    with pytest.raises(AssertionError):
        observation.observe_input(SimpleNamespace(wait_for_timeout=lambda _: None),
            SimpleNamespace(evaluate=sample), lambda: None, visible=True, keyboard=True, phase="keyboard")


@pytest.mark.parametrize("fault", ("active", "hover"))
def test_hidden_observation_requires_both_input_triggers_absent(monkeypatch, fault):
    now = [0.0]
    monkeypatch.setattr(observation, "perf_counter", lambda: now[0])
    state = {"visible": False, "hidden": True, "active": False, "focusVisible": False, "hover": False}
    state[fault] = True

    def sample(_):
        now[0] += .1
        return state

    with pytest.raises(AssertionError):
        observation.observe_input(SimpleNamespace(wait_for_timeout=lambda _: None),
            SimpleNamespace(evaluate=sample), lambda: None, visible=False, phase="hide")


@pytest.mark.parametrize("index", (0, 1, 2))
def test_keyboard_origin_is_unique_and_real_tab_has_no_corrective_focus(monkeypatch, index):
    calls = []
    origin = SimpleNamespace(count=lambda: 1, focus=lambda: calls.append("setup focus"),
        evaluate=lambda _: True)
    page = SimpleNamespace(locator=lambda selector: (calls.append(selector), origin)[1],
        keyboard=SimpleNamespace(press=lambda key: calls.append("real " + key)))
    targets = SimpleNamespace(nth=lambda position: (calls.append(("preceding", position)), origin)[1])

    def observe(page, tooltip, action, **kwargs):
        assert kwargs == {"visible": True, "keyboard": True, "phase": "keyboard"}
        calls.append("budget starts")
        action()
        return .01

    monkeypatch.setattr(observation, "observe_input", observe)
    assert observation.observe_keyboard(page, object(), targets, index) == .01
    assert calls == [('.ub-meter-legend span[tabindex="0"]' if index == 0 else ("preceding", index-1)),
        "setup focus", "budget starts", "real Tab"]
    origin.count = lambda: 2
    with pytest.raises(AssertionError):
        observation.observe_keyboard(page, object(), targets, index)


def test_hover_harness_uses_guarded_keyboard_sequence_not_corrective_focus():
    source = inspect.getsource(load_tool("check_breakdown_hover_ui").main)
    assert "observe_keyboard(page, handle, targets, index)" in source
    assert "target.focus()" not in source
