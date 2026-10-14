"""Diagnostic markers preserve the original input, reads, guard and failures."""
from types import SimpleNamespace

import pytest

from release_tooling_support import load_tool

probe = load_tool("probes.hover_input_latency")


@pytest.mark.parametrize("fails", (False, True))
def test_observation_trace_retains_each_original_call_and_restores_guard(fails):
    calls = []
    tooltip = SimpleNamespace(evaluate=lambda *args, **kwargs: (calls.append(("style", args, kwargs)), "original")[1])
    def input_action():
        calls.append("real Tab")

    def original(page, handle, action, **kwargs):
        assert page == "page" and kwargs == {"visible": True, "keyboard": True, "phase": "keyboard"}
        assert handle.evaluate("baseline") == "original"
        action()
        if fails:
            raise AssertionError("original 250ms guard")
        assert handle.evaluate("style", argument=7) == "original"
        return .02

    module, rows = SimpleNamespace(observe_input=original), []
    with probe.observation_trace(module, rows):
        args = ("page", tooltip, input_action)
        kwargs = {"visible": True, "keyboard": True, "phase": "keyboard"}
        if fails:
            with pytest.raises(AssertionError, match="original 250ms guard"):
                module.observe_input(*args, **kwargs)
        else:
            assert module.observe_input(*args, **kwargs) == .02
    assert module.observe_input is original
    assert calls == [("style", ("baseline",), {}), "real Tab"] + (
        [] if fails else [("style", ("style",), {"argument": 7})])
    assert len(rows) == 1
    stages = [entry["stage"] for entry in rows[0]["calls"]]
    assert stages == ["baseline-entry", "real-baseline-entry", "baseline-return", "input-entry", "input-return"] + (
        [] if fails else ["style-entry", "real-style-entry", "style-return"]) + ["observation-return"]
    if fails:
        assert rows[0]["failure"] == "AssertionError: original 250ms guard"
    assert rows[0]["phase"] == "keyboard"
    timings = [entry["ms"] for entry in rows[0]["calls"]]
    assert timings == sorted(timings)


@pytest.mark.parametrize("delay", (.25, .472))
def test_real_observer_rejects_action_only_overrun_before_timed_style(monkeypatch, delay):
    observation = load_tool("verification.hover_observation")
    now, calls, rows = [0.0], [], []
    monkeypatch.setattr(observation, "perf_counter", lambda: now[0])
    tooltip = SimpleNamespace(evaluate=lambda _: (calls.append("baseline"),
        {"hidden": True, "active": False, "hover": False})[1])

    def action():
        calls.append("real Tab")
        now[0] += delay

    with probe.observation_trace(observation, rows):
        with pytest.raises(AssertionError, match="'state': None"):
            observation.observe_input(None, tooltip, action, visible=True, keyboard=True, phase="keyboard")
    assert calls == ["baseline", "real Tab"]
    assert [entry["stage"] for entry in rows[0]["calls"]] == [
        "baseline-entry", "real-baseline-entry", "baseline-return", "input-entry", "input-return", "observation-return"]


def test_renderer_clock_wraps_original_expression_without_extra_read_or_changed_value():
    calls, rows = [], []
    value = {"visible": True, "hover": True}

    def evaluate(expression, *args, **kwargs):
        calls.append((expression, args, kwargs))
        return {"value": value, "elapsed_ms": .02}

    def original(page, tooltip, action, **kwargs):
        action()
        return tooltip.evaluate("tip => ({visible: true, hover: true})", "arg", argument=7)

    module = SimpleNamespace(observe_input=original)
    with probe.observation_trace(module, rows, renderer_clock=True):
        assert module.observe_input(None, SimpleNamespace(evaluate=evaluate),
            lambda: None, phase="hover") is value
    assert len(calls) == 1
    expression, args, kwargs = calls[0]
    assert "(tip => ({visible: true, hover: true}))(tip, arg)" in expression
    assert expression.count("performance.now()") == 2
    assert "document.visibilityState" not in expression
    assert args == ("arg",) and kwargs == {"argument": 7}
    assert rows[0]["renderer_reads"] == [{"stage": "style", "elapsed_ms": .02,
        "entry_ms": None, "time_origin": None}]
    assert module.observe_input is original


@pytest.mark.parametrize("fails", (False, True))
@pytest.mark.parametrize("renderer_clock", (False, True))
def test_main_restores_argv_and_records_original_failure(monkeypatch, tmp_path, fails, renderer_clock):
    import json
    import sys

    args = ["probe", "--output", str(tmp_path)] + (["--renderer-clock"] if renderer_clock else [])
    monkeypatch.setattr(sys, "argv", args)
    observation = load_tool("verification.hover_observation")
    original = observation.observe_input

    def run(path, *, run_name):
        assert path == str(probe.SCRIPTS / "check_breakdown_hover_ui.py")
        assert run_name == "__main__" and sys.argv == [path, "--output", str(tmp_path)]
        if fails:
            raise AssertionError("original failure")

    monkeypatch.setattr(probe.runpy, "run_path", run)
    if fails:
        with pytest.raises(AssertionError, match="original failure"):
            probe.main()
    else:
        probe.main()
    assert sys.argv is args and observation.observe_input is original
    evidence = json.loads((tmp_path / "input-timings.json").read_text())
    assert evidence["diagnostic_only"] is True and evidence["deadline_ms"] == 250
    assert evidence["extra_dom_reads_per_expression"] == 0
    assert evidence["untimed_document_state_reads_per_observation"] == (3 if renderer_clock else 0)
    assert evidence["extra_control_queries_per_timed_read"] == 0
    assert evidence["script_injection"] is renderer_clock
    assert evidence["product_scripts_disabled"] is True
    assert evidence["instrumentation_overhead_calibrated"] is False
    assert evidence["replay_passed"] is not fails
    if fails:
        assert evidence["failure"] == "AssertionError: original failure"


@pytest.mark.parametrize("control", ("scalar", "object", "clock"))
def test_control_queries_do_not_replace_real_style_or_run_during_baseline(control):
    calls, rows = [], []
    state = {"visible": True}

    def evaluate(expression):
        calls.append(expression)
        return "control" if expression == probe.CONTROLS[control] else state

    def original(page, tooltip, action, **kwargs):
        assert tooltip.evaluate("baseline") is state
        action()
        return tooltip.evaluate("real style")

    module = SimpleNamespace(observe_input=original)
    with probe.observation_trace(module, rows, control=control):
        assert module.observe_input(None, SimpleNamespace(evaluate=evaluate), lambda: None, phase="hover") is state
    assert calls == ["baseline", probe.CONTROLS[control], "real style"]
    assert rows[0]["control_value"] == "control"
    assert module.observe_input is original


@pytest.mark.parametrize("control", ("scalar", "object", "clock"))
def test_control_overrun_and_real_state_read_share_the_original_deadline(monkeypatch, control):
    observation = load_tool("verification.hover_observation")
    now, calls, rows = [0.0], [], []
    monkeypatch.setattr(observation, "perf_counter", lambda: now[0])
    state = {"visible": True, "hidden": True, "active": False, "focusVisible": False, "hover": False}

    def evaluate(expression):
        if expression == probe.CONTROLS[control]:
            calls.append("control")
            now[0] += .25
            return 1
        calls.append("real style")
        return {"value": state, "elapsed_ms": 0}

    page = SimpleNamespace(evaluate=lambda expression: calls.append("untimed document"), url="file:///synthetic.html")
    with probe.observation_trace(observation, rows, control=control, renderer_clock=True):
        with pytest.raises(AssertionError, match="seconds.*0.25"):
            observation.observe_input(page, SimpleNamespace(evaluate=evaluate),
                lambda: calls.append("real input"), visible=True, phase="hover")
    assert calls == ["untimed document", "real style", "real input", "control", "real style"]
    assert rows[0]["renderer_reads"][-1] == {"stage": "style", "elapsed_ms": 0,
        "entry_ms": None, "time_origin": None}


def test_renderer_entry_stamps_preserve_results_and_clock_domain():
    rows, state = [], {"visible": True}
    values = iter((100, 103))

    def evaluate(expression):
        assert "performance.timeOrigin" in expression
        return {"value": state, "elapsed_ms": 0, "entry_ms": next(values), "time_origin": 12345}

    def original(page, tooltip, action, **kwargs):
        assert tooltip.evaluate("baseline") is state
        action()
        return tooltip.evaluate("real style")

    module = SimpleNamespace(observe_input=original)
    with probe.observation_trace(module, rows, renderer_clock=True):
        assert module.observe_input(None, SimpleNamespace(evaluate=evaluate), lambda: None, phase="hover") is state
    assert rows[0]["renderer_reads"] == [
        {"stage": "baseline", "elapsed_ms": 0, "entry_ms": 100, "time_origin": 12345},
        {"stage": "style", "elapsed_ms": 0, "entry_ms": 103, "time_origin": 12345}]
