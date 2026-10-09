import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def harness(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("speed_webview_harness", scripts / "check_speed_webview.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_endpoint_readiness_is_bounded_and_separate_from_attachment(harness, monkeypatch):
    ticks = iter([0, 0, 1, 2])
    monkeypatch.setattr(harness.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(harness.time, "sleep", lambda delay: None)
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(kwargs["timeout"])
        raise TimeoutError("not ready")

    monkeypatch.setattr(harness, "build_opener", lambda *args: SimpleNamespace(open=unavailable))
    diagnostics = {"endpoint_attempts": 0}
    with pytest.raises(TimeoutError, match="before attachment"):
        harness.wait_cdp_endpoint(1234, 2, diagnostics)
    assert diagnostics == {"endpoint_attempts": 3, "last_endpoint_error": "TimeoutError"}
    assert calls == [2, 2, 2]


def test_disposable_launch_always_uses_in_memory_credentials(harness, tmp_path):
    root = tmp_path / "speed-native-synthetic"
    command = harness.disposable_command(Path("/synthetic/Code"), root, root / "extension", 1234)
    assert command.count("--use-inmemory-secretstorage") == 1
    assert f"--user-data-dir={root / 'user-data'}" in command
    assert f"--extensions-dir={root / 'extensions'}" in command
    assert not any("password-store" in arg for arg in command)
    with pytest.raises(AssertionError):
        harness.disposable_command(Path("Code"), tmp_path, tmp_path / "extension", 1234)


def test_rendered_state_requires_exact_navigation_and_visible_window(harness):
    args = {"scope": "synthetic", "granularity": "hourly", "windowStart": "2026-10-02"}
    state = {"scope": args["scope"], "granularity": "hourly", "window_start": args["windowStart"],
             "window_label": "2026-10-02 to 2026-10-08"}
    assert harness.matches_navigation(state, args)
    assert not harness.matches_navigation(dict(state, granularity="daily"), args)
    assert not harness.matches_navigation(dict(state, scope="stale"), args)
    assert not harness.matches_navigation(dict(state, window_label=None), args)


@pytest.mark.parametrize("covered", [False, True])
def test_explicit_native_target_click_uses_rendered_dom_and_input_not_scripts(harness, covered):
    from speed_native_target import NativeSpeedTarget
    from urllib.parse import quote
    import json
    args = {"scope": "synthetic", "granularity": "hourly", "windowStart": "2026-10-02"}
    uri = "command:codexUsage.navigateSpeed?" + quote(json.dumps([args]))
    chart = {"nodeId": 1, "attributes": ["class", "observed-speed"], "children": [{"nodeId": 2, "backendNodeId": 2, "nodeName": "A", "attributes": ["href", uri],
        "children": [{"nodeType": 3, "nodeValue": "Hourly"}]}]}
    toolbar = {"nodeId": 4, "attributes": ["class", "companion-actions"]}
    target = object.__new__(NativeSpeedTarget)
    target.chart = lambda: chart
    documents = []
    def document():
        documents.append(True)
        return {"children": [chart, toolbar]}
    target.document = document
    target.page = SimpleNamespace(wait_for_timeout=lambda delay: None)
    calls = []
    scrolled = False
    def send(method, params):
        nonlocal scrolled
        calls.append((method, params))
        if method == "DOM.getContentQuads":
            if params["nodeId"] == 4:
                bottom = 40 if covered else 10
                return {"quads": [[0, 0, 100, 0, 100, bottom, 0, bottom]]}
            top = 50 if scrolled else 20
            return {"quads": [[10, top, 30, top, 30, top + 20, 10, top + 20]]}
        if method == "Input.dispatchMouseEvent" and params["type"] == "mouseWheel":
            scrolled = True
        return {"backendNodeId": 2} if method == "DOM.getNodeForLocation" else {}
    target.send = send
    assert target.click("Hourly", harness.navigation_args) == args
    assert len(documents) == 1, "DOM frontend IDs must come from one coherent document"
    assert scrolled == covered
    assert calls[-4][0] == "DOM.getNodeForLocation"
    assert calls[-1][1] == {"type": "mouseReleased", "x": 20, "y": 60 if covered else 30, "button": "left", "clickCount": 1}
    assert not any(method.startswith("Runtime.") for method, _ in calls)
    def obstructed(method, params):
        return {"backendNodeId": 4} if method == "DOM.getNodeForLocation" else send(method, params)
    target.send = obstructed
    pressed = sum(params.get("type") == "mousePressed" for _, params in calls)
    with pytest.raises(AssertionError, match="Occluded native link"):
        target.click("Hourly", harness.navigation_args)
    assert sum(params.get("type") == "mousePressed" for _, params in calls) == pressed


def test_cleanup_tolerates_only_an_already_retired_owned_group(harness, monkeypatch):
    calls = []
    process = SimpleNamespace(pid=123, poll=lambda: 0, wait=lambda **kwargs: calls.append("wait"))
    def retired(*args):
        raise PermissionError("group retired")
    monkeypatch.setattr(harness.os, "name", "posix")
    monkeypatch.setattr(harness.os, "killpg", retired)
    def group_retired(group):
        assert calls == ["wait"], "reap the parent before checking group retirement"
        return True
    monkeypatch.setattr(harness, "wait_owned_group_exit", group_retired)
    harness.stop_owned_host(process)
    assert calls == ["wait"]
    monkeypatch.setattr(harness, "wait_owned_group_exit", lambda group: False)
    with pytest.raises(PermissionError):
        harness.stop_owned_host(process)


def test_group_teardown_wait_is_bounded_and_requires_actual_retirement(harness, monkeypatch):
    membership = iter([True, True, False])
    monkeypatch.setattr(harness, "owned_group_exists", lambda group: next(membership))
    monkeypatch.setattr(harness.time, "sleep", lambda delay: None)
    assert harness.wait_owned_group_exit(123)
    ticks = iter([0, 6])
    monkeypatch.setattr(harness.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(harness, "owned_group_exists", lambda group: True)
    assert not harness.wait_owned_group_exit(123)
