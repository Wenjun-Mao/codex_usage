from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Final

WINDOWS_CREATE_NEW_PROCESS_GROUP: Final[int] = 0x00000200
_TREE_KILL_TIMEOUT_SECONDS: Final[int] = 30


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
    except subprocess.TimeoutExpired:
        try:
            _terminate_process_tree(process, platform_name=target_platform)
        finally:
            process.communicate()
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


def _terminate_process_tree(
    process: subprocess.Popen[str],
    *,
    platform_name: str,
) -> None:
    if platform_name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return

    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=_TREE_KILL_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        if process.poll() is None:
            process.kill()
        raise
    if result.returncode != 0 and process.poll() is None:
        process.kill()
