from __future__ import annotations

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


class TimedOutProcess:
    pid = 4242
    returncode = -9

    def __init__(self) -> None:
        self.communicate_timeouts: list[int | None] = []
        self.kill_calls = 0

    def communicate(self, timeout: int | None = None) -> tuple[str, str]:
        self.communicate_timeouts.append(timeout)
        if len(self.communicate_timeouts) == 1:
            raise subprocess.TimeoutExpired(["codex-usage"], timeout)
        return "", ""

    def poll(self) -> None:
        return None

    def kill(self) -> None:
        self.kill_calls += 1


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
    assert process.communicate_timeouts == [120, None]
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
    assert process.communicate_timeouts == [120, None]
    assert process.kill_calls == 0
