from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Final

WINDOWS_CREATE_NEW_PROCESS_GROUP: Final[int] = 0x00000200
_CLEANUP_TIMEOUT_SECONDS: Final[float] = 10.0
_TREE_TERMINATION_TIMEOUT_SECONDS: Final[float] = 5.0
_DIRECT_DRAIN_TIMEOUT_SECONDS: Final[float] = 2.0
_DIRECT_REAP_TIMEOUT_SECONDS: Final[float] = 2.0


class ProcessTreeCleanupError(RuntimeError):
    def __init__(self, failures: list[str]) -> None:
        self.failures = tuple(failures)
        super().__init__("timed-out process cleanup failed: " + "; ".join(failures))


def run_process_tree(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path,
    timeout_seconds: int,
    platform_name: str | None = None,
) -> subprocess.CompletedProcess[str]:
    target_platform = os.name if platform_name is None else platform_name
    launch_options = _launch_options(target_platform)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment,
        cwd=cwd,
        **launch_options,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as timeout_error:
        try:
            _cleanup_timed_out_process(process, platform_name=target_platform)
        except ProcessTreeCleanupError as cleanup_error:
            raise cleanup_error from timeout_error
        raise

    if process.returncode is None:
        raise RuntimeError("completed process has no return code")
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _launch_options(platform_name: str) -> dict[str, object]:
    if platform_name == "posix":
        return {"start_new_session": True}
    if platform_name == "nt":
        return {"creationflags": WINDOWS_CREATE_NEW_PROCESS_GROUP}
    raise ValueError(f"unsupported process platform: {platform_name}")


def _cleanup_timed_out_process(
    process: subprocess.Popen[str],
    *,
    platform_name: str,
) -> None:
    deadline = time.monotonic() + _CLEANUP_TIMEOUT_SECONDS
    failures: list[str] = []
    tree_failure = _terminate_process_tree(
        process,
        platform_name=platform_name,
        deadline=deadline,
    )
    if tree_failure is not None:
        failures.append(tree_failure)
        direct_kill_failure = _kill_direct_process(process)
        if direct_kill_failure is not None:
            failures.append(direct_kill_failure)
    failures.extend(_drain_and_reap_process(process, deadline=deadline))
    if failures:
        raise ProcessTreeCleanupError(failures)


def _terminate_process_tree(
    process: subprocess.Popen[str],
    *,
    platform_name: str,
    deadline: float,
) -> str | None:
    if platform_name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return None
        except OSError:
            return "killpg failed"
        return None

    timeout = _stage_timeout(deadline, _TREE_TERMINATION_TIMEOUT_SECONDS)
    if timeout is None:
        return "taskkill skipped because cleanup deadline expired"
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "taskkill timed out"
    except OSError:
        return "taskkill could not start"
    if result.returncode != 0:
        return f"taskkill exited with code {result.returncode}"
    return None


def _drain_and_reap_process(
    process: subprocess.Popen[str],
    *,
    deadline: float,
) -> list[str]:
    timeout = _stage_timeout(deadline, _DIRECT_DRAIN_TIMEOUT_SECONDS)
    if timeout is None:
        failures = ["output drain skipped because cleanup deadline expired"]
        direct_kill_failure = _kill_direct_process(process)
        if direct_kill_failure is not None:
            failures.append(direct_kill_failure)
        failures.extend(_close_streams_and_reap(process, deadline=deadline))
        return failures

    try:
        process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        return _escalate_direct_process(process, deadline=deadline)
    except (OSError, ValueError):
        return _escalate_direct_process(
            process,
            deadline=deadline,
            initial_failure="output drain failed",
        )
    return []


def _escalate_direct_process(
    process: subprocess.Popen[str],
    *,
    deadline: float,
    initial_failure: str | None = None,
) -> list[str]:
    failures = [initial_failure] if initial_failure is not None else []
    direct_kill_failure = _kill_direct_process(process)
    if direct_kill_failure is not None:
        failures.append(direct_kill_failure)

    timeout = _stage_timeout(deadline, _DIRECT_DRAIN_TIMEOUT_SECONDS)
    if timeout is None:
        failures.append("second output drain skipped because cleanup deadline expired")
        failures.extend(_close_streams_and_reap(process, deadline=deadline))
        return failures
    try:
        process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        failures.append("output drain timed out after direct kill")
        failures.extend(_close_streams_and_reap(process, deadline=deadline))
    except (OSError, ValueError):
        failures.append("output drain failed after direct kill")
        failures.extend(_close_streams_and_reap(process, deadline=deadline))
    return failures


def _kill_direct_process(process: subprocess.Popen[str]) -> str | None:
    try:
        if process.poll() is None:
            process.kill()
    except ProcessLookupError:
        return None
    except OSError:
        return "direct child kill failed"
    return None


def _close_streams_and_reap(
    process: subprocess.Popen[str],
    *,
    deadline: float,
) -> list[str]:
    failures: list[str] = []
    for stream in (process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            failures.append("output stream close failed")

    timeout = _stage_timeout(deadline, _DIRECT_REAP_TIMEOUT_SECONDS)
    if timeout is None:
        failures.append("direct child reap skipped because cleanup deadline expired")
        return failures
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        failures.append("direct child reap timed out")
    except OSError:
        failures.append("direct child reap failed")
    return failures


def _stage_timeout(deadline: float, maximum_seconds: float) -> float | None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    return min(remaining, maximum_seconds)
