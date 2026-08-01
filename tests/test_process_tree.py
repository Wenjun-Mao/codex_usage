from __future__ import annotations

import ast
import importlib.util
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def load_packaged_smoke() -> ModuleType:
    path = REPOSITORY_ROOT / "scripts/packaged_parallel_cache_smoke.py"
    module_name = "_process_tree_packaged_smoke_test"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


class RecordingStream:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class BlockingStream(RecordingStream):
    def __init__(self, release: threading.Event) -> None:
        super().__init__()
        self.release = release
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        self.release.wait()
        super().close()


class TimedOutProcess:
    pid = 4242
    returncode = -9

    def __init__(
        self,
        *,
        cleanup_communicate_timeouts: int = 0,
        wait_times_out: bool = False,
    ) -> None:
        self.cleanup_communicate_timeouts = cleanup_communicate_timeouts
        self.wait_times_out = wait_times_out
        self.communicate_timeouts: list[float | None] = []
        self.wait_timeouts: list[float | None] = []
        self.kill_calls = 0
        self.stdout = RecordingStream()
        self.stderr = RecordingStream()

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self.communicate_timeouts.append(timeout)
        if len(self.communicate_timeouts) == 1:
            raise subprocess.TimeoutExpired(["codex-usage"], timeout)
        if self.cleanup_communicate_timeouts:
            self.cleanup_communicate_timeouts -= 1
            raise subprocess.TimeoutExpired(["codex-usage"], timeout)
        return "", ""

    def poll(self) -> None:
        return None

    def kill(self) -> None:
        self.kill_calls += 1

    def wait(self, timeout: float | None = None) -> int:
        self.wait_timeouts.append(timeout)
        if self.wait_times_out:
            raise subprocess.TimeoutExpired(["codex-usage"], timeout)
        return self.returncode


class RecordingWindowsJob:
    def __init__(
        self,
        *,
        terminate_error: bool = False,
        close_error: bool = False,
    ) -> None:
        self.terminate_error = terminate_error
        self.close_error = close_error
        self.terminate_calls = 0
        self.close_calls = 0

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self.terminate_error:
            raise OSError("termination failed")

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error:
            raise OSError("close failed")


def assert_cleanup_error(caught: pytest.ExceptionInfo[RuntimeError]) -> None:
    assert type(caught.value).__name__ == "ProcessTreeCleanupError"


def assert_bounded_cleanup_timeouts(process: TimedOutProcess) -> None:
    assert process.communicate_timeouts[0] == 120
    cleanup_timeouts = [
        *process.communicate_timeouts[1:],
        *process.wait_timeouts,
    ]
    assert cleanup_timeouts
    assert all(timeout is not None and 0 < timeout <= 2 for timeout in cleanup_timeouts)


def test_packaged_summary_invokes_120_second_process_tree_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_packaged_smoke()
    call: dict[str, object] = {}

    def run_process_tree(
        command: list[str],
        *,
        environment: dict[str, str],
        cwd: Path,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        call.update(
            command=command,
            environment=environment,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )
        return subprocess.CompletedProcess(command, 0, "{}", "")

    monkeypatch.setattr(module, "run_process_tree", run_process_tree)
    module._run_summary(tmp_path / "codex-usage", tmp_path, tmp_path / "cache")

    assert call["timeout_seconds"] == module.COMMAND_TIMEOUT_SECONDS == 120


def test_posix_process_tree_timeout_uses_session_killpg_and_reaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_usage import process_tree

    process = TimedOutProcess()
    launch: dict[str, object] = {}
    killpg_calls: list[tuple[int, signal.Signals]] = []

    def popen(command: list[str], **kwargs: object) -> TimedOutProcess:
        launch.update(command=command, **kwargs)
        return process

    monkeypatch.setattr(process_tree.subprocess, "Popen", popen)
    monkeypatch.setattr(
        process_tree.os,
        "killpg",
        lambda pid, sig: killpg_calls.append((pid, sig)),
    )

    with pytest.raises(subprocess.TimeoutExpired):
        process_tree.run_process_tree(
            ["codex-usage", "summary"],
            environment={"CODEX_HOME": str(tmp_path)},
            cwd=tmp_path,
            timeout_seconds=120,
            platform_name="posix",
        )

    assert launch["start_new_session"] is True
    assert "creationflags" not in launch
    assert killpg_calls == [(process.pid, signal.SIGKILL)]
    assert_bounded_cleanup_timeouts(process)
    assert process.kill_calls == 0


def test_windows_process_tree_timeout_terminates_owned_job_and_reaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_usage import process_tree

    process = TimedOutProcess()
    job = RecordingWindowsJob()
    monkeypatch.setattr(
        process_tree,
        "_launch_owned_process",
        lambda *args, **kwargs: (process, job),
    )

    with pytest.raises(subprocess.TimeoutExpired):
        process_tree.run_process_tree(
            ["codex-usage.exe", "summary"],
            environment={"CODEX_HOME": str(tmp_path)},
            cwd=tmp_path,
            timeout_seconds=120,
            platform_name="nt",
        )

    assert job.terminate_calls == 1
    assert job.close_calls == 1
    assert_bounded_cleanup_timeouts(process)
    assert process.kill_calls == 0


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("terminate", "Windows Job Object termination failed"),
        ("close", "Windows Job Object handle close failed"),
    ],
)
def test_windows_tree_termination_failure_is_bounded_and_specific(
    failure: str,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_usage import process_tree

    process = TimedOutProcess()
    job = RecordingWindowsJob(
        terminate_error=failure == "terminate",
        close_error=failure == "close",
    )
    monkeypatch.setattr(
        process_tree,
        "_launch_owned_process",
        lambda *args, **kwargs: (process, job),
    )

    with pytest.raises(RuntimeError, match=message) as caught:
        process_tree.run_process_tree(
            ["codex-usage.exe", "summary"],
            environment={"CODEX_HOME": str(tmp_path)},
            cwd=tmp_path,
            timeout_seconds=120,
            platform_name="nt",
        )

    assert_cleanup_error(caught)
    assert job.terminate_calls == 1
    assert job.close_calls == 1
    assert process.kill_calls == 1
    assert_bounded_cleanup_timeouts(process)


def test_posix_killpg_failure_is_bounded_and_specific(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_usage import process_tree

    process = TimedOutProcess()
    killpg_calls: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(
        process_tree.subprocess, "Popen", lambda *args, **kwargs: process
    )

    def failing_killpg(pid: int, sig: signal.Signals) -> None:
        killpg_calls.append((pid, sig))
        raise PermissionError("killpg denied")

    monkeypatch.setattr(process_tree.os, "killpg", failing_killpg)

    with pytest.raises(RuntimeError, match="killpg failed") as caught:
        process_tree.run_process_tree(
            ["codex-usage", "summary"],
            environment={"CODEX_HOME": str(tmp_path)},
            cwd=tmp_path,
            timeout_seconds=120,
            platform_name="posix",
        )

    assert_cleanup_error(caught)
    assert killpg_calls == [(process.pid, signal.SIGKILL)]
    assert process.kill_calls == 1
    assert_bounded_cleanup_timeouts(process)


def test_cleanup_escalates_after_first_bounded_drain_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_usage import process_tree

    process = TimedOutProcess(cleanup_communicate_timeouts=1)
    monkeypatch.setattr(
        process_tree.subprocess, "Popen", lambda *args, **kwargs: process
    )
    monkeypatch.setattr(process_tree.os, "killpg", lambda pid, sig: None)

    with pytest.raises(subprocess.TimeoutExpired):
        process_tree.run_process_tree(
            ["codex-usage", "summary"],
            environment={"CODEX_HOME": str(tmp_path)},
            cwd=tmp_path,
            timeout_seconds=120,
            platform_name="posix",
        )

    assert len(process.communicate_timeouts) == 3
    assert_bounded_cleanup_timeouts(process)
    assert process.kill_calls == 1
    assert process.wait_timeouts == []


def test_second_bounded_drain_timeout_raises_cleanup_failure_and_reaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_usage import process_tree

    process = TimedOutProcess(cleanup_communicate_timeouts=2)
    monkeypatch.setattr(
        process_tree.subprocess, "Popen", lambda *args, **kwargs: process
    )
    monkeypatch.setattr(process_tree.os, "killpg", lambda pid, sig: None)

    with pytest.raises(RuntimeError, match="output drain timed out") as caught:
        process_tree.run_process_tree(
            ["codex-usage", "summary"],
            environment={"CODEX_HOME": str(tmp_path)},
            cwd=tmp_path,
            timeout_seconds=120,
            platform_name="posix",
        )

    assert_cleanup_error(caught)
    assert len(process.communicate_timeouts) == 3
    assert_bounded_cleanup_timeouts(process)
    assert process.kill_calls == 1
    assert process.stdout.closed is True
    assert process.stderr.closed is True


def test_windows_repeated_drain_timeout_never_closes_reader_streams(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_usage import process_tree

    release = threading.Event()
    process = TimedOutProcess(cleanup_communicate_timeouts=2)
    process.stdout = BlockingStream(release)
    process.stderr = BlockingStream(release)
    job = RecordingWindowsJob()
    monkeypatch.setattr(
        process_tree,
        "_launch_owned_process",
        lambda *args, **kwargs: (process, job),
    )
    errors: list[BaseException] = []

    def invoke() -> None:
        try:
            process_tree.run_process_tree(
                ["codex-usage.exe", "summary"],
                environment={"CODEX_HOME": str(tmp_path)},
                cwd=tmp_path,
                timeout_seconds=120,
                platform_name="nt",
            )
        except (RuntimeError, subprocess.SubprocessError, OSError) as error:
            errors.append(error)

    cleanup_thread = threading.Thread(target=invoke, daemon=True)
    started = time.monotonic()
    cleanup_thread.start()
    cleanup_thread.join(timeout=1.0)
    completed_within_outer_deadline = not cleanup_thread.is_alive()
    elapsed = time.monotonic() - started
    release.set()
    cleanup_thread.join(timeout=1.0)

    assert completed_within_outer_deadline
    assert elapsed < 1.5
    assert not cleanup_thread.is_alive()
    assert len(errors) == 1
    assert type(errors[0]).__name__ == "ProcessTreeCleanupError"
    assert "output collection incomplete" in str(errors[0])
    assert process.stdout.close_calls == 0
    assert process.stderr.close_calls == 0
    assert_bounded_cleanup_timeouts(process)


def test_windows_cleanup_stops_at_shared_monotonic_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_usage import process_tree

    process = TimedOutProcess(cleanup_communicate_timeouts=1)
    job = RecordingWindowsJob()
    monotonic_values = iter((100.0, 109.0, 110.0, 110.0))
    monkeypatch.setattr(
        process_tree,
        "_launch_owned_process",
        lambda *args, **kwargs: (process, job),
    )
    monkeypatch.setattr(process_tree.time, "monotonic", lambda: next(monotonic_values))

    with pytest.raises(RuntimeError, match="cleanup deadline expired") as caught:
        process_tree.run_process_tree(
            ["codex-usage.exe", "summary"],
            environment={"CODEX_HOME": str(tmp_path)},
            cwd=tmp_path,
            timeout_seconds=120,
            platform_name="nt",
        )

    assert_cleanup_error(caught)
    assert job.terminate_calls == 1
    assert job.close_calls == 1
    assert process.communicate_timeouts == [120, 1]
    assert process.wait_timeouts == []
    assert process.stdout.closed is False
    assert process.stderr.closed is False
    assert "output collection incomplete" in str(caught.value)
    assert_bounded_cleanup_timeouts(process)


def test_process_tree_source_has_no_unbounded_drain_or_wait_call() -> None:
    path = REPOSITORY_ROOT / "src/codex_usage/process_tree.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bounded_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"communicate", "wait"}
    ]

    assert bounded_calls
    for call in bounded_calls:
        timeout = next(
            (keyword.value for keyword in call.keywords if keyword.arg == "timeout"),
            None,
        )
        assert timeout is not None
        assert not isinstance(timeout, ast.Constant) or timeout.value is not None
