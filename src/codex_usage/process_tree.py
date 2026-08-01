from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Final

from codex_usage.windows_job import WindowsJob, WindowsJobError

_CLEANUP_TIMEOUT_SECONDS: Final[float] = 10.0
_DIRECT_DRAIN_TIMEOUT_SECONDS: Final[float] = 2.0
_DIRECT_REAP_TIMEOUT_SECONDS: Final[float] = 2.0
_WINDOWS_CONTROLLER_MODULE: Final[str] = "codex_usage.windows_job_controller"


class ProcessTreeCleanupError(RuntimeError):
    def __init__(self, failures: list[str]) -> None:
        self.failures = tuple(failures)
        super().__init__("process tree cleanup failed: " + "; ".join(failures))


class ProcessTreeLaunchError(RuntimeError):
    pass


def run_process_tree(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path,
    timeout_seconds: int,
    platform_name: str | None = None,
) -> subprocess.CompletedProcess[str]:
    target_platform = os.name if platform_name is None else platform_name
    process, windows_job = _launch_owned_process(
        command,
        environment=environment,
        cwd=cwd,
        platform_name=target_platform,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as timeout_error:
        try:
            _cleanup_timed_out_process(
                process,
                platform_name=target_platform,
                windows_job=windows_job,
            )
        except ProcessTreeCleanupError as cleanup_error:
            raise cleanup_error from timeout_error
        raise
    except BaseException as error:
        failures = _close_windows_job(windows_job)
        if failures:
            raise ProcessTreeCleanupError(failures) from error
        raise

    failures = _close_windows_job(windows_job)
    if failures:
        raise ProcessTreeCleanupError(failures)
    if process.returncode is None:
        raise RuntimeError("completed process has no return code")
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _launch_owned_process(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path,
    platform_name: str,
) -> tuple[subprocess.Popen[str], WindowsJob | None]:
    if platform_name == "posix":
        return (
            subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=environment,
                cwd=cwd,
                start_new_session=True,
            ),
            None,
        )
    if platform_name == "nt":
        return _launch_windows_controller(
            command,
            environment=environment,
            cwd=cwd,
        )
    raise ValueError(f"unsupported process platform: {platform_name}")


def _launch_windows_controller(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path,
) -> tuple[subprocess.Popen[str], WindowsJob]:
    try:
        job = WindowsJob()
    except Exception as error:
        raise ProcessTreeLaunchError(
            "Windows process ownership setup failed"
        ) from error
    controller_command = [
        sys.executable,
        "-m",
        _WINDOWS_CONTROLLER_MODULE,
        "--",
        *command,
    ]
    try:
        process = subprocess.Popen(
            controller_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
            cwd=cwd,
        )
    except (OSError, ValueError) as error:
        _close_windows_job(job)
        raise ProcessTreeLaunchError(
            "Windows process ownership setup failed"
        ) from error

    assigned = False
    try:
        job.assign(process.pid)
        assigned = True
        _release_windows_controller(process)
    except Exception as error:
        _abort_windows_controller(process, job, assigned=assigned)
        raise ProcessTreeLaunchError(
            "Windows process ownership setup failed"
        ) from error
    return process, job


def _release_windows_controller(process: subprocess.Popen[str]) -> None:
    gate = process.stdin
    if gate is None:
        raise RuntimeError("Windows process controller gate is unavailable")
    gate.write("1")
    gate.flush()
    gate.close()
    process.stdin = None


def _abort_windows_controller(
    process: subprocess.Popen[str],
    job: WindowsJob,
    *,
    assigned: bool,
) -> None:
    if assigned:
        try:
            job.terminate()
        except (OSError, WindowsJobError):
            pass
    gate = process.stdin
    if gate is not None:
        try:
            gate.close()
        except (OSError, ValueError):
            pass
        process.stdin = None
    _kill_direct_process(process)
    try:
        process.communicate(timeout=_DIRECT_DRAIN_TIMEOUT_SECONDS)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    _close_windows_job(job)


def _cleanup_timed_out_process(
    process: subprocess.Popen[str],
    *,
    platform_name: str,
    windows_job: WindowsJob | None,
) -> None:
    deadline = time.monotonic() + _CLEANUP_TIMEOUT_SECONDS
    failures: list[str] = []
    tree_failures = _terminate_process_tree(
        process,
        platform_name=platform_name,
        windows_job=windows_job,
    )
    if tree_failures:
        failures.extend(tree_failures)
        direct_kill_failure = _kill_direct_process(process)
        if direct_kill_failure is not None:
            failures.append(direct_kill_failure)
    failures.extend(
        _drain_and_reap_process(
            process,
            platform_name=platform_name,
            deadline=deadline,
        )
    )
    if failures:
        raise ProcessTreeCleanupError(failures)


def _terminate_process_tree(
    process: subprocess.Popen[str],
    *,
    platform_name: str,
    windows_job: WindowsJob | None,
) -> list[str]:
    if platform_name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return []
        except OSError:
            return ["killpg failed"]
        return []

    if windows_job is None:
        return ["Windows Job Object ownership is missing"]
    failures: list[str] = []
    try:
        windows_job.terminate()
    except (OSError, WindowsJobError):
        failures.append("Windows Job Object termination failed")
    failures.extend(_close_windows_job(windows_job))
    return failures


def _close_windows_job(windows_job: WindowsJob | None) -> list[str]:
    if windows_job is None:
        return []
    try:
        windows_job.close()
    except (OSError, WindowsJobError):
        return ["Windows Job Object handle close failed"]
    return []


def _drain_and_reap_process(
    process: subprocess.Popen[str],
    *,
    platform_name: str,
    deadline: float,
) -> list[str]:
    timeout = _stage_timeout(deadline, _DIRECT_DRAIN_TIMEOUT_SECONDS)
    if timeout is None:
        failures = ["output drain skipped because cleanup deadline expired"]
        direct_kill_failure = _kill_direct_process(process)
        if direct_kill_failure is not None:
            failures.append(direct_kill_failure)
        failures.extend(
            _finish_failed_output_collection(
                process,
                platform_name=platform_name,
                deadline=deadline,
            )
        )
        return failures

    try:
        process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        return _escalate_direct_process(
            process,
            platform_name=platform_name,
            deadline=deadline,
        )
    except (OSError, ValueError):
        return _escalate_direct_process(
            process,
            platform_name=platform_name,
            deadline=deadline,
            initial_failure="output drain failed",
        )
    return []


def _escalate_direct_process(
    process: subprocess.Popen[str],
    *,
    platform_name: str,
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
        failures.extend(
            _finish_failed_output_collection(
                process,
                platform_name=platform_name,
                deadline=deadline,
            )
        )
        return failures
    try:
        process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        failures.append("output drain timed out after direct kill")
        failures.extend(
            _finish_failed_output_collection(
                process,
                platform_name=platform_name,
                deadline=deadline,
            )
        )
    except (OSError, ValueError):
        failures.append("output drain failed after direct kill")
        failures.extend(
            _finish_failed_output_collection(
                process,
                platform_name=platform_name,
                deadline=deadline,
            )
        )
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


def _finish_failed_output_collection(
    process: subprocess.Popen[str],
    *,
    platform_name: str,
    deadline: float,
) -> list[str]:
    failures: list[str] = []
    if platform_name == "nt":
        failures.append("output collection incomplete")
    else:
        for stream in (process.stdout, process.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                failures.append("output stream close failed")

    failures.extend(_reap_direct_process(process, deadline=deadline))
    return failures


def _reap_direct_process(
    process: subprocess.Popen[str],
    *,
    deadline: float,
) -> list[str]:
    failures: list[str] = []
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
