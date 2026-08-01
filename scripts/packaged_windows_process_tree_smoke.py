from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from codex_usage.process_tree import run_process_tree

_COMMAND_TIMEOUT_SECONDS: Final[int] = 5
_TOTAL_BOUND_SECONDS: Final[float] = 16.0
_CHILD_SLEEP_SECONDS: Final[int] = 120
_SYNCHRONIZE: Final[int] = 0x00100000
_ERROR_INVALID_PARAMETER: Final[int] = 87
_WAIT_OBJECT_0: Final[int] = 0
_WAIT_TIMEOUT: Final[int] = 258


@dataclass
class _Observation:
    child_handle: int | None = None
    root_exited_at: float | None = None
    descendant_alive_after_root_exit: bool = False
    failed: bool = False


class _WindowsProcesses:
    def __init__(self) -> None:
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32 = kernel32

    def open(self, pid: int) -> int | None:
        handle = self._kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
        if handle:
            return int(handle)
        error_code = ctypes.get_last_error()
        if error_code == _ERROR_INVALID_PARAMETER:
            return None
        raise OSError(error_code, "process handle open failed")

    def is_exited(self, handle: int) -> bool:
        result = self._kernel32.WaitForSingleObject(handle, 0)
        if result == _WAIT_OBJECT_0:
            return True
        if result == _WAIT_TIMEOUT:
            return False
        raise OSError("process wait failed")

    def wait_exited(self, handle: int, timeout_seconds: float) -> bool:
        milliseconds = max(0, int(timeout_seconds * 1000))
        result = self._kernel32.WaitForSingleObject(handle, milliseconds)
        if result == _WAIT_OBJECT_0:
            return True
        if result == _WAIT_TIMEOUT:
            return False
        raise OSError("process wait failed")

    def close(self, handle: int) -> None:
        if not self._kernel32.CloseHandle(handle):
            raise OSError("process handle close failed")


def _read_state(state_path: Path) -> tuple[int, int] | None:
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    root_pid = payload.get("root_pid")
    child_pid = payload.get("child_pid")
    if not isinstance(root_pid, int) or not isinstance(child_pid, int):
        return None
    if root_pid <= 0 or child_pid <= 0:
        return None
    return root_pid, child_pid


def _observe_root_exit(
    state_path: Path,
    processes: _WindowsProcesses,
    deadline: float,
    observation: _Observation,
) -> None:
    root_handle: int | None = None
    try:
        state: tuple[int, int] | None = None
        while time.monotonic() < deadline and state is None:
            state = _read_state(state_path)
            if state is None:
                time.sleep(0.01)
        if state is None:
            observation.failed = True
            return

        root_pid, child_pid = state
        observation.child_handle = processes.open(child_pid)
        if observation.child_handle is None:
            observation.failed = True
            return
        root_handle = processes.open(root_pid)
        while root_handle is not None and time.monotonic() < deadline:
            if processes.is_exited(root_handle):
                break
            time.sleep(0.01)
        if root_handle is not None and not processes.is_exited(root_handle):
            observation.failed = True
            return

        observation.root_exited_at = time.monotonic()
        observation.descendant_alive_after_root_exit = not processes.is_exited(
            observation.child_handle
        )
    except (OSError, ValueError):
        observation.failed = True
    finally:
        if root_handle is not None:
            try:
                processes.close(root_handle)
            except OSError:
                observation.failed = True


def _run_root(state_path: Path) -> int:
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--child"],
        stdin=subprocess.DEVNULL,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    temporary_state = state_path.with_suffix(".tmp")
    temporary_state.write_text(
        json.dumps({"root_pid": os.getpid(), "child_pid": child.pid}),
        encoding="utf-8",
    )
    os.replace(temporary_state, state_path)
    return 0


def _run_native_smoke(executable: Path) -> dict[str, bool]:
    if os.name != "nt" or not executable.is_file():
        raise RuntimeError("Windows packaged executable is unavailable")
    processes = _WindowsProcesses()
    observation = _Observation()
    with tempfile.TemporaryDirectory(prefix="codex-usage-process-tree-") as directory:
        working_directory = Path(directory)
        state_path = working_directory / "state.json"
        started_at = time.monotonic()
        observer = threading.Thread(
            target=_observe_root_exit,
            args=(
                state_path,
                processes,
                started_at + _COMMAND_TIMEOUT_SECONDS,
                observation,
            ),
            daemon=True,
        )
        observer.start()
        timed_out = False
        try:
            run_process_tree(
                [sys.executable, str(Path(__file__).resolve()), "--root", str(state_path)],
                environment=os.environ.copy(),
                cwd=working_directory,
                timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
        finished_at = time.monotonic()
        observer.join(timeout=1.0)

        observer_finished = not observer.is_alive()
        observer_ok = observer_finished and not observation.failed
        descendant_exited = False
        if observer_finished and observation.child_handle is not None:
            try:
                descendant_exited = processes.wait_exited(
                    observation.child_handle,
                    timeout_seconds=1.0,
                )
            finally:
                processes.close(observation.child_handle)
        root_exited_before_timeout = (
            observation.root_exited_at is not None
            and observation.root_exited_at < started_at + _COMMAND_TIMEOUT_SECONDS
        )
        return {
            "descendant_alive_after_root_exit": (
                observation.descendant_alive_after_root_exit
            ),
            "descendant_exited": descendant_exited,
            "root_exited_before_timeout": root_exited_before_timeout,
            "timed_out": timed_out,
            "within_bound": finished_at - started_at <= _TOTAL_BOUND_SECONDS,
            "observer_ok": observer_ok,
        }


def _parse_executable(argv: list[str]) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", required=True, type=Path)
    return parser.parse_args(argv).executable.resolve()


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ["--child"]:
        time.sleep(_CHILD_SLEEP_SECONDS)
        return 0
    if len(arguments) == 2 and arguments[0] == "--root":
        try:
            return _run_root(Path(arguments[1]))
        except (OSError, ValueError):
            return 125
    try:
        result = _run_native_smoke(_parse_executable(arguments))
    except (OSError, RuntimeError, ValueError):
        print('{"error":true}')
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if all(result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
