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


def test_frame_selection_reacquires_after_command_replaces_content(harness, monkeypatch):
    args = {"scope": "synthetic", "granularity": "hourly", "windowStart": "2026-10-02"}
    state = {"scope": args["scope"], "granularity": "hourly", "window_start": args["windowStart"],
             "window_label": "2026-10-02 to 2026-10-08"}
    detached = SimpleNamespace(is_detached=lambda: True)
    unrelated = SimpleNamespace(is_detached=lambda: False, locator=lambda selector: SimpleNamespace(count=lambda: 0))
    old = SimpleNamespace(is_detached=lambda: False, locator=lambda selector: SimpleNamespace(count=lambda: 1))
    current = SimpleNamespace(is_detached=lambda: False, locator=lambda selector: SimpleNamespace(count=lambda: 1))
    browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[SimpleNamespace(frames=[unrelated]),
        SimpleNamespace(frames=[detached, old, current])])])
    monkeypatch.setattr(harness, "rendered_state", lambda frame: state if frame is current else dict(state, granularity="daily"))
    frame, actual = harness.wait_speed_frame(browser, harness.time.monotonic() + 1, args)
    assert frame is current and actual == state
    assert not harness.matches_navigation(dict(state, scope="stale"), args)
    assert not harness.matches_navigation(dict(state, window_label=None), args)
