from __future__ import annotations

import ast
import importlib.util
import signal
import subprocess
import sys
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


def assert_cleanup_error(caught: pytest.ExceptionInfo[RuntimeError]) -> None:
    assert type(caught.value).__name__ == "ProcessTreeCleanupError"


def assert_only_bounded_timeouts(timeouts: list[float | None]) -> None:
    assert timeouts
    assert all(timeout is not None and timeout > 0 for timeout in timeouts)


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
    assert process.communicate_timeouts[0] == 120
    assert_only_bounded_timeouts(process.communicate_timeouts)
    assert process.kill_calls == 0


def test_windows_process_tree_timeout_uses_taskkill_and_reaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_usage import process_tree

    process = TimedOutProcess()
    launch: dict[str, object] = {}
    taskkill_calls: list[tuple[list[str], dict[str, object]]] = []

    def popen(command: list[str], **kwargs: object) -> TimedOutProcess:
        launch.update(command=command, **kwargs)
        return process

    def taskkill(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        taskkill_calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(process_tree.subprocess, "Popen", popen)
    monkeypatch.setattr(process_tree.subprocess, "run", taskkill)

    with pytest.raises(subprocess.TimeoutExpired):
        process_tree.run_process_tree(
            ["codex-usage.exe", "summary"],
            environment={"CODEX_HOME": str(tmp_path)},
            cwd=tmp_path,
            timeout_seconds=120,
            platform_name="nt",
        )

    assert launch["creationflags"] == process_tree.WINDOWS_CREATE_NEW_PROCESS_GROUP
    assert "start_new_session" not in launch
    assert taskkill_calls[0][0] == [
        "taskkill",
        "/PID",
        str(process.pid),
        "/T",
        "/F",
    ]
    assert taskkill_calls[0][1]["check"] is False
    assert taskkill_calls[0][1]["timeout"] <= 5
    assert process.communicate_timeouts[0] == 120
    assert_only_bounded_timeouts(process.communicate_timeouts)
    assert process.kill_calls == 0


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        ("nonzero", "taskkill exited with code 1"),
        ("oserror", "taskkill could not start"),
        ("timeout", "taskkill timed out"),
    ],
)
def test_windows_tree_termination_failure_is_bounded_and_specific(
    outcome: str,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_usage import process_tree

    process = TimedOutProcess()
    taskkill_calls: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.setattr(
        process_tree.subprocess, "Popen", lambda *args, **kwargs: process
    )

    def taskkill(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        taskkill_calls.append((command, kwargs))
        if outcome == "oserror":
            raise OSError("taskkill unavailable")
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(process_tree.subprocess, "run", taskkill)

    with pytest.raises(RuntimeError, match=message) as caught:
        process_tree.run_process_tree(
            ["codex-usage.exe", "summary"],
            environment={"CODEX_HOME": str(tmp_path)},
            cwd=tmp_path,
            timeout_seconds=120,
            platform_name="nt",
        )

    assert_cleanup_error(caught)
    assert taskkill_calls[0][1]["timeout"] <= 5
    assert process.kill_calls == 1
    assert process.communicate_timeouts[0] == 120
    assert_only_bounded_timeouts(process.communicate_timeouts)


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
    assert process.communicate_timeouts[0] == 120
    assert_only_bounded_timeouts(process.communicate_timeouts)


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
    assert_only_bounded_timeouts(process.communicate_timeouts)
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
    assert_only_bounded_timeouts(process.communicate_timeouts)
    assert process.kill_calls == 1
    assert process.stdout.closed is True
    assert process.stderr.closed is True
    assert_only_bounded_timeouts(process.wait_timeouts)


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
