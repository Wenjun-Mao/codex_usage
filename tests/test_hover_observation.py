"""Late visible results, corrective focus and lingering triggers cannot pass."""
from types import SimpleNamespace
import inspect

import pytest

from release_tooling_support import load_tool

observation = load_tool("verification.hover_observation")
HIDDEN = {"visible": False, "hidden": True, "active": False, "focusVisible": False, "hover": False}


@pytest.mark.parametrize("delay,passes", ((.1, True), (.249, True), (.25, False), (.273, False)))
def test_input_and_style_read_share_strict_absolute_budget(monkeypatch, delay, passes):
    now = [0.0]
    monkeypatch.setattr(observation, "perf_counter", lambda: now[0])
    calls = []
    state = {"visible": True, "hidden": False, "active": True, "focusVisible": True, "hover": False}

    def sample(_):
        calls.append("style")
        now[0] += delay / 2
        if len(calls) == 1:
            return HIDDEN
        return state

    def action():
        calls.append("real input")
        now[0] += delay / 2

    args = (SimpleNamespace(wait_for_timeout=lambda _: None), SimpleNamespace(evaluate=sample), action)
    if passes:
        assert observation.observe_input(*args, visible=True, keyboard=True, phase="keyboard") == pytest.approx(delay)
    else:
        with pytest.raises(AssertionError):
            observation.observe_input(*args, visible=True, keyboard=True, phase="keyboard")
    assert calls == ["style", "real input", "style"]


@pytest.mark.parametrize("fault", ("active", "focusVisible", "hover"))
def test_keyboard_observation_requires_real_target_modality_without_hover_masking(monkeypatch, fault):
    now = [0.0]
    monkeypatch.setattr(observation, "perf_counter", lambda: now[0])
    state = {"visible": True, "hidden": False, "active": True, "focusVisible": True, "hover": False}
    state[fault] = fault == "hover"
    first = [True]

    def sample(_):
        now[0] += .1
        if first[0]:
            first[0] = False
            return HIDDEN
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
        assert kwargs == {"visible": True, "keyboard": True, "phase": "keyboard", "record": None}
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
    assert "observe_keyboard(page, handle, targets, index, record=record)" in source
    assert "target.focus()" not in source


def test_pointer_preparation_resets_trial_hover_then_requires_hidden_baseline_and_exact_hit():
    calls = []
    state = [HIDDEN]

    def trial(**kwargs):
        calls.append(("readiness", kwargs))
        state[0] = {**HIDDEN, "visible": True, "hidden": False, "hover": True}

    def reset(x, y):
        calls.append(("reset pointer", x, y))
        state[0] = HIDDEN

    hit = SimpleNamespace(hover=trial,
        bounding_box=lambda: {"x": 10, "y": 20, "width": 30, "height": 40},
        evaluate=lambda expression, point: (calls.append(("hit", point)), True)[1])
    page = SimpleNamespace(mouse=SimpleNamespace(move=reset),
        evaluate=lambda _: calls.append("blur"))
    tooltip = SimpleNamespace(evaluate=lambda _: (calls.append("baseline"), state[0])[1])
    assert observation.prepare_pointer(page, hit, tooltip) == {"x": 12, "y": 22}
    assert calls == [("readiness", {"position": {"x": 2, "y": 2}, "timeout": 1000, "trial": True}),
        ("reset pointer", 0, 0), "blur", "baseline",
        ("hit", {"x": 12, "y": 22})]
    hit.evaluate = lambda *_: False
    with pytest.raises(AssertionError):
        observation.prepare_pointer(page, hit, tooltip)
    page.mouse.move = lambda *_: None
    with pytest.raises(AssertionError, match="input baseline"):
        observation.prepare_pointer(page, hit, tooltip)


@pytest.mark.parametrize("fault", ("hidden", "active", "hover"))
def test_primed_tooltip_cannot_pass_as_a_fresh_input(monkeypatch, fault):
    state = {**HIDDEN, fault: fault != "hidden"}
    tooltip = SimpleNamespace(evaluate=lambda _: state)
    def action():
        pytest.fail("Primed input must be rejected before timed action")

    with pytest.raises(AssertionError, match="input baseline"):
        observation.observe_input(None, tooltip, action, visible=True, phase="hover")


def test_pointer_budget_starts_before_real_motion_not_locator_readiness():
    source = inspect.getsource(load_tool("check_breakdown_hover_ui").main)
    assert source.index("point = prepare_pointer(page, hit, handle)") < source.index("durations.append(observe_input(")
    assert 'lambda: page.mouse.move(point["x"], point["y"])' in source


@pytest.mark.parametrize("phase", ("hover", "hide", "keyboard"))
def test_recorder_retains_actual_states_and_does_not_add_style_reads(monkeypatch, phase):
    measurements = load_tool("verification.hover_measurements")
    ticks = iter((0., .01, .02))
    monkeypatch.setattr(observation, "perf_counter", lambda: next(ticks))
    visible = phase != "hide"
    states = iter(([HIDDEN] if visible else []) + [measurements.MATCHED[phase]])
    calls, records = [], []
    def sample(_):
        calls.append("style")
        return next(states)
    result = observation.observe_input(None, SimpleNamespace(evaluate=sample),
        lambda: calls.append("real input"), visible=visible, keyboard=phase == "keyboard",
        phase=phase, record=records.append)
    assert result == .02
    assert calls == (["style"] if visible else []) + ["real input", "style"]
    assert records == [{"phase": phase, "seconds": .02,
        "baseline": HIDDEN if visible else None, "matched": measurements.MATCHED[phase]}]


@pytest.mark.parametrize("ticks", ((0., .3), (0., .1, .3)))
def test_late_action_or_style_result_cannot_emit_a_success_observation(monkeypatch, ticks):
    times = iter(ticks)
    monkeypatch.setattr(observation, "perf_counter", lambda: next(times))
    records = []
    states = iter((HIDDEN, {**HIDDEN, "visible": True, "hidden": False, "hover": True}))
    with pytest.raises(AssertionError):
        observation.observe_input(None, SimpleNamespace(evaluate=lambda _: next(states)),
            lambda: None, visible=True, phase="hover", record=records.append)
    assert records == []
