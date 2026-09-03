from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from codex_usage.agent_paths import settings_path
from codex_usage.agent_private_files import ensure_private_directory
from codex_usage.agent_windows_task import install_windows_task


MACOS_SERVICE_LABEL = "com.wenjunmao.codex-usage-agent"
WINDOWS_TASK_NAME = "Codex Usage Agent"


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    supported: bool
    installed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "supported": self.supported,
            "installed": self.installed,
            "detail": self.detail,
        }


def packaged_agent_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--background"]
    return [sys.executable, "-m", "codex_usage.agent_main", "--background"]


def install_background_agent(command: list[str] | None = None) -> ServiceStatus:
    agent_command = command or packaged_agent_command()
    if sys.platform == "darwin":
        return _install_launch_agent(agent_command)
    if os.name == "nt":
        return _install_scheduled_task(agent_command)
    return ServiceStatus(False, False, "Background capture is not supported here.")


def uninstall_background_agent() -> ServiceStatus:
    if sys.platform == "darwin":
        return _uninstall_launch_agent()
    if os.name == "nt":
        return _uninstall_scheduled_task()
    return ServiceStatus(False, False, "Background capture is not supported here.")


def background_agent_status() -> ServiceStatus:
    if sys.platform == "darwin":
        path = _launch_agent_path()
        return ServiceStatus(True, path.is_file(), str(path))
    if os.name == "nt":
        result = subprocess.run(
            ["schtasks.exe", "/Query", "/TN", WINDOWS_TASK_NAME],
            capture_output=True,
            text=True,
            check=False,
        )
        return ServiceStatus(True, result.returncode == 0, result.stderr.strip())
    return ServiceStatus(False, False, "Background capture is not supported here.")


def _launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MACOS_SERVICE_LABEL}.plist"


def _install_launch_agent(command: list[str]) -> ServiceStatus:
    path = _launch_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    log_dir = settings_path().parent / "logs"
    ensure_private_directory(log_dir)
    payload = {
        "Label": MACOS_SERVICE_LABEL,
        "ProgramArguments": command,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 60,
        "ProcessType": "Background",
        "StandardOutPath": str(log_dir / "agent.log"),
        "StandardErrorPath": str(log_dir / "agent.error.log"),
    }
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(plistlib.dumps(payload, sort_keys=True))
    os.replace(temporary, path)
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", domain, str(path)],
        capture_output=True,
        check=False,
    )
    result = subprocess.run(
        ["launchctl", "bootstrap", domain, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "launchctl bootstrap failed")
    return ServiceStatus(True, True, str(path))


def _uninstall_launch_agent() -> ServiceStatus:
    path = _launch_agent_path()
    if path.exists():
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}", str(path)],
            capture_output=True,
            check=False,
        )
        path.unlink(missing_ok=True)
    return ServiceStatus(True, False, str(path))


def _install_scheduled_task(command: list[str]) -> ServiceStatus:
    detail = install_windows_task(command, WINDOWS_TASK_NAME)
    return ServiceStatus(True, True, detail)


def _uninstall_scheduled_task() -> ServiceStatus:
    subprocess.run(
        ["schtasks.exe", "/End", "/TN", WINDOWS_TASK_NAME],
        capture_output=True,
        text=True,
        check=False,
    )
    result = subprocess.run(
        ["schtasks.exe", "/Delete", "/TN", WINDOWS_TASK_NAME, "/F"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return ServiceStatus(True, False, result.stdout.strip())
