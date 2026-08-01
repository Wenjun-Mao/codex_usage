from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


class FakeJobApi:
    def __init__(self, *, fail_limit: bool = False) -> None:
        self.fail_limit = fail_limit
        self.calls: list[tuple[object, ...]] = []

    def create_job(self) -> int:
        self.calls.append(("create",))
        return 91

    def set_kill_on_close(self, handle: int) -> None:
        self.calls.append(("limit", handle))
        if self.fail_limit:
            raise RuntimeError("injected limit failure")

    def assign_process(self, handle: int, pid: int) -> None:
        self.calls.append(("assign", handle, pid))

    def terminate_job(self, handle: int) -> None:
        self.calls.append(("terminate", handle))

    def close_handle(self, handle: int) -> None:
        self.calls.append(("close", handle))


class RecordingGate:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.closed = False

    def write(self, value: str) -> int:
        self.events.append(f"release:{value}")
        return len(value)

    def flush(self) -> None:
        self.events.append("flush")

    def close(self) -> None:
        self.closed = True
        self.events.append("gate-close")


class ControllerProcess:
    pid = 4242

    def __init__(
        self,
        events: list[str],
        *,
        root_already_exited: bool = False,
    ) -> None:
        self.events = events
        self.stdin = RecordingGate(events)
        self.stdout = None
        self.stderr = None
        self.returncode = 0 if root_already_exited else None
        self.communicate_calls = 0
        self.kill_calls = 0

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self.communicate_calls += 1
        self.events.append(f"communicate:{self.communicate_calls}")
        if self.communicate_calls == 1:
            raise subprocess.TimeoutExpired(["controller"], timeout)
        self.returncode = -9
        return "", ""

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = -9
        return self.returncode


class CompletedController(ControllerProcess):
    def __init__(self, events: list[str]) -> None:
        super().__init__(events, root_already_exited=True)
        self.returncode = 7

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self.events.append("communicate:complete")
        return "stdout", "stderr"


class RecordingJob:
    def __init__(
        self,
        events: list[str],
        *,
        assignment_error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.assignment_error = assignment_error
        self.events.append("job-create")

    def assign(self, pid: int) -> None:
        self.events.append(f"assign:{pid}")
        if self.assignment_error is not None:
            raise self.assignment_error

    def terminate(self) -> None:
        self.events.append("job-terminate")

    def close(self) -> None:
        self.events.append("job-close")


def _windows_job_module():
    spec = importlib.util.find_spec("codex_usage.windows_job")
    assert spec is not None, "Windows Job Object ownership module is missing"
    from codex_usage import windows_job

    return windows_job


def test_windows_job_sets_kill_on_close_before_process_assignment() -> None:
    windows_job = _windows_job_module()
    api = FakeJobApi()

    job = windows_job.WindowsJob(api=api)
    job.assign(4242)
    job.close()

    assert api.calls == [
        ("create",),
        ("limit", 91),
        ("assign", 91, 4242),
        ("close", 91),
    ]


def test_windows_job_configuration_failure_closes_unconfigured_handle() -> None:
    windows_job = _windows_job_module()
    api = FakeJobApi(fail_limit=True)

    with pytest.raises(RuntimeError, match="injected limit failure"):
        windows_job.WindowsJob(api=api)

    assert api.calls == [("create",), ("limit", 91), ("close", 91)]


@pytest.mark.parametrize("root_already_exited", (False, True))
def test_windows_timeout_assigns_before_release_and_terminates_owned_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    root_already_exited: bool,
) -> None:
    from codex_usage import process_tree

    events: list[str] = []
    process = ControllerProcess(events, root_already_exited=root_already_exited)
    job = RecordingJob(events)
    launch: dict[str, object] = {}

    def popen(command: list[str], **kwargs: object) -> ControllerProcess:
        launch.update(command=command, **kwargs)
        events.append("popen")
        return process

    monkeypatch.setattr(process_tree, "WindowsJob", lambda: job, raising=False)
    monkeypatch.setattr(process_tree.subprocess, "Popen", popen)
    taskkill_calls: list[object] = []
    monkeypatch.setattr(
        process_tree.subprocess,
        "run",
        lambda *args, **kwargs: taskkill_calls.append((args, kwargs)),
    )

    with pytest.raises(subprocess.TimeoutExpired):
        process_tree.run_process_tree(
            ["codex-usage.exe", "summary"],
            environment={"CODEX_HOME": str(tmp_path)},
            cwd=tmp_path,
            timeout_seconds=120,
            platform_name="nt",
        )

    assert launch["command"][-3:] == ["--", "codex-usage.exe", "summary"]
    assert launch["stdin"] is subprocess.PIPE
    assert events.index("assign:4242") < events.index("release:1")
    assert events.index("release:1") < events.index("communicate:1")
    assert events.index("communicate:1") < events.index("job-terminate")
    assert events.index("job-terminate") < events.index("job-close")
    assert taskkill_calls == []


def test_windows_assignment_failure_never_releases_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_usage import process_tree

    events: list[str] = []
    process = ControllerProcess(events)
    assignment_error = RuntimeError("injected assignment failure")
    job = RecordingJob(events, assignment_error=assignment_error)
    monkeypatch.setattr(process_tree, "WindowsJob", lambda: job, raising=False)
    monkeypatch.setattr(
        process_tree.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )
    monkeypatch.setattr(
        process_tree.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
    )

    with pytest.raises(RuntimeError, match="ownership setup failed"):
        process_tree.run_process_tree(
            ["codex-usage.exe", "summary"],
            environment={"CODEX_HOME": str(tmp_path)},
            cwd=tmp_path,
            timeout_seconds=120,
            platform_name="nt",
        )

    assert not any(event.startswith("release:") for event in events)
    assert process.kill_calls == 1
    assert "job-close" in events


def test_windows_normal_completion_preserves_result_and_closes_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_usage import process_tree

    events: list[str] = []
    process = CompletedController(events)
    job = RecordingJob(events)
    monkeypatch.setattr(process_tree, "WindowsJob", lambda: job, raising=False)
    monkeypatch.setattr(
        process_tree.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )

    completed = process_tree.run_process_tree(
        ["codex-usage.exe", "summary"],
        environment={"CODEX_HOME": str(tmp_path)},
        cwd=tmp_path,
        timeout_seconds=120,
        platform_name="nt",
    )

    assert (completed.args, completed.returncode) == (
        ["codex-usage.exe", "summary"],
        7,
    )
    assert (completed.stdout, completed.stderr) == ("stdout", "stderr")
    assert events.index("assign:4242") < events.index("release:1")
    assert events.index("communicate:complete") < events.index("job-close")
    assert "job-terminate" not in events
