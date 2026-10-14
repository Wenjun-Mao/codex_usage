"""External sampling never attaches to unrelated or unverified local processes."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from release_tooling_support import load_tool

sampler = load_tool("probes.webkit_process_sample")


@pytest.mark.parametrize("fault", (None, "local", "repository", "job", "ref"))
def test_sampler_requires_ephemeral_main_diagnostic(monkeypatch, fault):
    monkeypatch.setattr(sampler.platform, "system", lambda: "Darwin")
    env = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_REPOSITORY": "Wenjun-Mao/codex_usage", "GITHUB_JOB": "diagnostic",
        "GITHUB_REF": "refs/heads/main"}
    fields = {"local": "RUNNER_ENVIRONMENT", "repository": "GITHUB_REPOSITORY",
        "job": "GITHUB_JOB", "ref": "GITHUB_REF"}
    if fault:
        env[fields[fault]] = "foreign"
        with pytest.raises(ValueError, match="ephemeral"):
            sampler.require_ephemeral_host(env)
    else:
        sampler.require_ephemeral_host(env)


def test_only_owned_driver_and_verified_browser_root_affinity_are_selected():
    rows = sampler.process_table("""100 1 /repo/python
101 100 /sdk/driver/node
102 101 /cache/webkit-2336/Playwright.app/Contents/MacOS/Playwright
103 1 /cache/webkit-2336/WebKit.framework/XPCServices/com.apple.WebKit.WebContent.xpc/Contents/MacOS/com.apple.WebKit.WebContent.Development
104 1 /unrelated/webkit-2336/WebKit.framework/XPCServices/com.apple.WebKit.WebContent.xpc/Contents/MacOS/com.apple.WebKit.WebContent.Development
105 1 /sdk/driver/node
106 101 /cache/chromium/Chrome
107 1 /cache/webkit-2336/Playwright.app/Contents/MacOS/Playwright
invalid line
""")
    selected = sampler.selected_processes(rows, 100, Path("/sdk/driver/node"))
    assert set(selected) == {101, 102}
    assert sampler.selected_processes({k: v for k, v in rows.items() if k != 102},
        100, Path("/sdk/driver/node")) == {}


@pytest.mark.parametrize("fails", (False, True))
def test_sampler_failure_cannot_mask_original_observation(monkeypatch, tmp_path, fails):
    events = []
    child = SimpleNamespace(pid=99999, poll=lambda: None, terminate=lambda: events.append("terminate"),
        wait=lambda **kwargs: (events.append("collected"), 2)[1])
    monkeypatch.setattr(sampler, "require_ephemeral_host", lambda: None)
    monkeypatch.setattr(sampler, "require_sampling_contract", lambda: None)
    def launch(command, **kwargs):
        assert command[1:3] == ["-m", "probes.webkit_process_sample"]
        assert kwargs["env"]["PYTHONPATH"] == str(Path(sampler.__file__).resolve().parents[1])
        assert kwargs["start_new_session"] is True
        return child
    monkeypatch.setattr(sampler.subprocess, "Popen", launch)
    monkeypatch.setattr(sampler.os, "killpg", lambda *_: events.append("group killed"))
    expected = "original 250ms failure" if fails else "Diagnostic sampler failed"
    with pytest.raises((AssertionError, RuntimeError), match=expected):
        with sampler.sampling(tmp_path, True):
            if fails:
                raise AssertionError("original 250ms failure")
    assert events == ["terminate", "collected", "group killed", "collected"]
    assert (tmp_path / "sampler-status.json").is_file()


def test_disabled_sampler_has_no_process_or_sdk_side_effect(monkeypatch, tmp_path):
    monkeypatch.setattr(sampler.subprocess, "Popen", lambda *_: pytest.fail("No sampler launch"))
    monkeypatch.setattr(sampler, "require_ephemeral_host", lambda: pytest.fail("No host introspection"))
    with sampler.sampling(tmp_path, False):
        pass
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("kind", ("WebContent", "Networking", "GPU"))
def test_xpc_selection_matches_revision_2336_development_executables(kind):
    bundle = "com.apple.WebKit." + kind
    path = Path(f"/cache/webkit-2336/WebKit.framework/XPCServices/{bundle}.xpc/Contents/MacOS/{bundle}.Development")
    assert sampler.is_xpc(path)
    assert not sampler.is_xpc(path.with_name(bundle))
    assert not sampler.is_xpc(path.with_name("unrelated"))


def test_reused_pid_or_changed_executable_is_never_attached(monkeypatch, tmp_path):
    executable = tmp_path / "WebContent"
    executable.write_bytes(b"synthetic")
    first = {"pid": 101, "parent": 1, "start_seconds": 10, "start_microseconds": 20,
        "executable": str(executable)}
    answers = iter((first, {**first, "start_microseconds": 21}))
    monkeypatch.setattr(sampler, "process_identity", lambda _: next(answers))
    assert sampler.attachment_identity(101, {"parent": 1, "executable": str(executable)}) is None
    monkeypatch.setattr(sampler, "process_identity", lambda _: first)
    hashes = iter(("original", "changed"))
    monkeypatch.setattr(sampler, "file_digest", lambda _: next(hashes))
    assert sampler.attachment_identity(101, {"parent": 1, "executable": str(executable)}) is None


def test_many_hung_children_share_cleanup_deadline(monkeypatch):
    now, events = [0], []
    monkeypatch.setattr(sampler, "monotonic", lambda: now[0])

    class Child:
        def __init__(self, pid):
            self.pid, self.killed = pid, False
        def poll(self):
            return -9 if self.killed else None
        def wait(self, *, timeout):
            events.append((self.pid, "wait", timeout))
            if self.killed:
                return -9
            now[0] += timeout
            raise sampler.subprocess.TimeoutExpired("synthetic", timeout)
        def kill(self):
            self.killed = True
            events.append((self.pid, "kill"))

    assert sampler.finish_samples({pid: Child(pid) for pid in (1, 2, 3)}) == {1: -9, 2: -9, 3: -9}
    assert now[0] == 10
    assert [(pid, action) for pid, action, *_ in events if action == "kill"] == [(1, "kill"), (2, "kill"), (3, "kill")]


@pytest.mark.parametrize("fault", ("terminate", "wait", "status"))
def test_cleanup_errors_are_separate_from_original_failure(monkeypatch, tmp_path, fault):
    def fail():
        raise OSError("synthetic cleanup error")
    child = SimpleNamespace(pid=99999, poll=lambda: None,
        terminate=fail if fault == "terminate" else lambda: None,
        wait=(lambda **_: fail()) if fault == "wait" else lambda **_: 0)
    monkeypatch.setattr(sampler, "require_ephemeral_host", lambda: None)
    monkeypatch.setattr(sampler, "require_sampling_contract", lambda: None)
    monkeypatch.setattr(sampler.subprocess, "Popen", lambda *_, **__: child)
    monkeypatch.setattr(sampler.os, "killpg", lambda *_: None)
    if fault == "status":
        monkeypatch.setattr(Path, "write_text", lambda *_, **__: fail())
    with pytest.raises(AssertionError, match="original deadline failure"):
        with sampler.sampling(tmp_path, True) as status:
            raise AssertionError("original deadline failure")
    assert status["cleanup_error"] == "synthetic cleanup error"


@pytest.mark.parametrize("entrypoint", ("context", "monitor"))
def test_live_sampler_is_held_before_filesystem_sdk_or_attachment(monkeypatch, tmp_path, entrypoint):
    monkeypatch.setattr(sampler, "require_ephemeral_host", lambda: None)
    monkeypatch.setattr(sampler.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("No child launch"))
    monkeypatch.setattr(sampler.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("No process discovery"))
    monkeypatch.setattr(sampler, "process_identity", lambda *_: pytest.fail("No private ABI read"))
    output = tmp_path / "absent"
    with pytest.raises(RuntimeError, match="public process identity and fixture association"):
        if entrypoint == "context":
            with sampler.sampling(output, True):
                pytest.fail("No replay under unsupported sampling")
        else:
            sampler.monitor(output, 100, Path("/sdk/driver/node"))
    assert not output.exists()
