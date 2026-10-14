"""Lookup boundaries preserve the original guard and reject weak realm/sequence evidence."""
from types import SimpleNamespace
import json
import subprocess

import pytest

from release_tooling_support import load_tool

marker = load_tool("probes.eval_lookup_marker")
probe = load_tool("probes.hover_input_latency")


@pytest.mark.parametrize("fault", ("assignment", "replacement"))
def test_actual_js_integrity_fault_restores_owned_accessor_without_clobbering_replacement(fault):
    script = """
import vm from 'node:vm';
import fs from 'node:fs';
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const context = vm.createContext({performance:{now:()=>5,timeOrigin:1000}});
vm.runInContext('(' + data.install + ')({mode:"clock",token:"owned"})', context);
let failed = false;
if (data.fault === 'assignment') {
  try { vm.runInContext('eval = () => 2', context); } catch { failed = true; }
} else {
  vm.runInContext('Object.defineProperty(globalThis,"eval",{value:()=>2,configurable:true,writable:true})', context);
}
const result = vm.runInContext('(' + data.restore + ')("owned")', context);
const value = vm.runInContext('eval("1")', context);
console.log(JSON.stringify({failed,result,value}));
"""
    completed = subprocess.run(["node", "--input-type=module", "--eval", script],
        input=json.dumps({"install": marker.INSTALL, "restore": marker.RESTORE, "fault": fault}),
        capture_output=True, text=True, check=True, timeout=5)
    data = json.loads(completed.stdout)
    assert data["result"]["integrity_error"] is True
    if fault == "assignment":
        assert data["failed"] is True and data["result"]["descriptor_equal"] is True
        assert data["result"]["restoration_attempted"] is True and data["value"] == 1
    else:
        assert data["result"]["descriptor_equal"] is False
        assert data["result"]["restoration_attempted"] is False and data["value"] == 2


@pytest.mark.parametrize("body_fails,cleanup_fails", ((False, False), (True, False), (True, True), (False, True)))
def test_document_cleanup_restores_outside_input_and_retains_original_error(body_fails, cleanup_fails):
    calls, documents = [], []

    def evaluate(expression, arg):
        calls.append(expression)
        if expression == marker.INSTALL:
            assert arg["mode"] == "clock"
            return {**arg, "time_origin": 1000, "clock_domain": arg["token"]}
        assert expression == marker.RESTORE
        if cleanup_fails:
            raise RuntimeError("cleanup failure")
        return {"descriptor_equal": True}

    page = SimpleNamespace(evaluate=evaluate, url="file:///synthetic", main_frame=object())
    tool = marker.EvalLookupMarker("clock", documents)

    def replay():
        with tool.document(page, {"engine": "webkit"}):
            assert "file:///synthetic" == tool.active[id(page)]["url"]
            if body_fails:
                raise AssertionError("original 250ms guard")

    if body_fails or cleanup_fails:
        with pytest.raises(AssertionError if body_fails else RuntimeError,
            match="original 250ms guard" if body_fails else "cleanup failure") as error:
            replay()
        if body_fails and cleanup_fails:
            assert any("Eval marker cleanup failed" in note for note in error.value.__notes__)
    else:
        replay()
    assert calls == [marker.INSTALL, marker.RESTORE] and not tool.active


def test_failed_installation_attempt_is_not_silently_left_without_cleanup():
    calls, documents = [], []

    def evaluate(expression, arg):
        calls.append(expression)
        if expression == marker.INSTALL:
            raise RuntimeError("installation failed")
        raise RuntimeError("no installed state")

    page = SimpleNamespace(evaluate=evaluate, url="file:///synthetic", main_frame=object())
    with pytest.raises(RuntimeError, match="installation failed") as error:
        with marker.EvalLookupMarker("clock", documents).document(page, {"engine": "webkit"}):
            pytest.fail("No input after failed preparation")
    assert calls == [marker.INSTALL, marker.RESTORE]
    assert any("cleanup failed" in note for note in error.value.__notes__)


def test_other_engines_are_not_instrumented():
    tool = marker.EvalLookupMarker("clock", [])
    with tool.document(None, {"engine": "chromium"}):
        assert tool.body_snapshot(None) == "null"
    assert tool.documents == []


@pytest.mark.parametrize("fault", (None, "token", "origin", "sequence", "late", "missing", "overflow"))
def test_only_same_realm_fresh_attributable_lookup_can_be_used(fault):
    page = SimpleNamespace(main_frame=object(), url="file:///synthetic")
    tool = marker.EvalLookupMarker("clock", [])
    tool.active[id(page)] = {"token": "owned", "origin": 1000, "frame": page.main_frame,
        "url": page.url, "last_sequence": 1}
    data = {"token": "owned", "mode": "clock", "time_origin": 1000, "clock_domain": "owned",
        "assignments": 0, "sequence": 2, "dropped": 0,
        "latest": {"sequence": 2, "entry_ms": 5, "time_origin": 1000, "clock_domain": "owned"}}
    if fault == "token":
        data["token"] = "another-document"
    elif fault == "origin":
        data["time_origin"] = 2000
    elif fault == "sequence":
        data["sequence"] = 1
    elif fault == "late":
        data["latest"]["entry_ms"] = 12
    elif fault == "missing":
        data["latest"] = None
    elif fault == "overflow":
        data["dropped"] = 3
    if fault:
        with pytest.raises(RuntimeError):
            tool.validate(page, data, 10, 1000)
    else:
        tool.validate(page, data, 10, 1000)
        assert tool.active[id(page)]["last_sequence"] == 2


def test_actual_js_epoch_bridge_jitter_does_not_change_monotonic_realm_identity():
    script = """
import vm from 'node:vm';
import fs from 'node:fs';
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
let epoch = 1000;
const performance = {now:()=>5, get timeOrigin() { return ++epoch; }};
const context = vm.createContext({performance});
const setup = vm.runInContext('(' + data.install + ')({mode:"clock",token:"owned"})', context);
vm.runInContext('eval("1")', context);
const rawEpoch = vm.runInContext('performance.timeOrigin', context);
const snapshot = vm.runInContext('(' + data.snapshot + ')("owned")', context);
const restore = vm.runInContext('(' + data.restore + ')("owned")', context);
console.log(JSON.stringify({setup,rawEpoch,snapshot,restore}));
"""
    completed = subprocess.run(["node", "--input-type=module", "--eval", script],
        input=json.dumps({"install": marker.INSTALL, "snapshot": marker.SNAPSHOT, "restore": marker.RESTORE}),
        capture_output=True, text=True, check=True, timeout=5)
    data = json.loads(completed.stdout)
    assert data["rawEpoch"] != data["setup"]["time_origin"]
    assert data["snapshot"]["time_origin"] == data["setup"]["time_origin"]
    assert data["snapshot"]["clock_domain"] == data["snapshot"]["latest"]["clock_domain"] == "owned"
    assert data["restore"]["descriptor_equal"] is True and data["restore"]["integrity_error"] is False


def test_raw_epoch_origin_change_is_not_a_monotonic_clock_domain_change():
    page = SimpleNamespace(main_frame=object(), url="file:///synthetic")
    tool = marker.EvalLookupMarker("clock", [])
    tool.active[id(page)] = {"token": "owned", "origin": 1000, "frame": page.main_frame,
        "url": page.url, "last_sequence": 0}
    data = {"token": "owned", "mode": "clock", "time_origin": 1000, "clock_domain": "owned",
        "assignments": 0, "sequence": 1, "dropped": 0,
        "latest": {"sequence": 1, "entry_ms": 5, "time_origin": 1000, "clock_domain": "owned"}}
    tool.validate(page, data, 10, 1001)


@pytest.mark.parametrize("field", ("body", "lookup"))
@pytest.mark.parametrize("value", (True, False, float("nan"), float("inf"), float("-inf"), -1, None, "5"))
def test_nonfinite_negative_or_non_numeric_monotonic_timestamps_fail_closed(field, value):
    page = SimpleNamespace(main_frame=object(), url="file:///synthetic")
    tool = marker.EvalLookupMarker("clock", [])
    tool.active[id(page)] = {"token": "owned", "origin": 1000, "frame": page.main_frame,
        "url": page.url, "last_sequence": 0}
    data = {"token": "owned", "mode": "clock", "time_origin": 1000, "clock_domain": "owned",
        "assignments": 0, "sequence": 1, "dropped": 0,
        "latest": {"sequence": 1, "entry_ms": value if field == "lookup" else 5,
            "time_origin": 1000, "clock_domain": "owned"}}
    with pytest.raises(RuntimeError):
        tool.validate(page, data, value if field == "body" else 10, 1000)
    assert tool.active[id(page)]["last_sequence"] == 0


@pytest.mark.parametrize("guard_fails", (False, True))
def test_invalid_diagnostic_marker_cannot_mask_original_timing_guard(guard_fails):
    rows = []
    tool = SimpleNamespace(body_snapshot=lambda _: "({})",
        validate=lambda *_: (_ for _ in ()).throw(RuntimeError("marker unavailable")))
    tooltip = SimpleNamespace(evaluate=lambda *_a, **_k:
        {"value": "original style", "entry_ms": 5, "time_origin": 1000, "elapsed_ms": 0, "eval_lookup": None})

    def original(page, tip, action, **kwargs):
        action()
        assert tip.evaluate("tip => 'original style'") == "original style"
        if guard_fails:
            raise AssertionError("original 250ms guard")
        return .01

    observation = SimpleNamespace(observe_input=original)
    with probe.observation_trace(observation, rows, renderer_clock=True, eval_lookup=tool):
        with pytest.raises(AssertionError if guard_fails else RuntimeError,
            match="original 250ms guard" if guard_fails else "marker unavailable"):
            observation.observe_input(None, tooltip, lambda: None, phase="hover")
    assert observation.observe_input is original
    assert "marker unavailable" in rows[0]["eval_lookup_failure"]


@pytest.mark.parametrize("args", (("--control", "page-scalar", "--renderer-clock"),
    ("--process-sample", "--renderer-clock"), ()))
def test_confounded_or_unstamped_lookup_arm_refuses_before_file_work(monkeypatch, tmp_path, args):
    import sys
    output = tmp_path / "absent"
    monkeypatch.setattr(sys, "argv", ["probe", "--output", str(output), "--eval-lookup", "clock", *args])
    with pytest.raises(SystemExit) as error:
        probe.main()
    assert error.value.code == 2 and not output.exists()
