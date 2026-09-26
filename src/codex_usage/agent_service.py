from __future__ import annotations

import ntpath
import os
import plistlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

MACOS_SERVICE_LABEL = "com.wenjunmao.codex-usage-agent"
WINDOWS_TASK_NAME = "Codex Usage Agent"
TASK_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    supported: bool
    installed: bool
    detail: str = ""
    recognized: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "supported": self.supported,
            "installed": self.installed,
            "detail": self.detail,
            "recognized": self.recognized,
        }


def uninstall_background_agent() -> ServiceStatus:
    if sys.platform == "darwin":
        return _uninstall_launch_agent()
    if os.name == "nt":
        return _uninstall_scheduled_task()
    return ServiceStatus(False, False, "Background capture is not supported here.")


def background_agent_status() -> ServiceStatus:
    if sys.platform == "darwin":
        path = _launch_agent_path()
        return ServiceStatus(True, path.is_file(), str(path), _recognized_launch_agent(path))
    if os.name == "nt":
        result = subprocess.run(
            ["schtasks.exe", "/Query", "/TN", WINDOWS_TASK_NAME, "/XML"],
            capture_output=True,
            check=False,
        )
        xml = _decode_task_output(result.stdout)
        error = _decode_task_output(result.stderr).strip()
        return ServiceStatus(
            True, result.returncode == 0, error,
            result.returncode == 0 and _recognized_windows_task(xml),
        )
    return ServiceStatus(False, False, "Background capture is not supported here.")


def _launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MACOS_SERVICE_LABEL}.plist"


def _uninstall_launch_agent() -> ServiceStatus:
    path = _launch_agent_path()
    if path.exists():
        if not _recognized_launch_agent(path):
            raise RuntimeError(f"Refusing to remove an unrecognized LaunchAgent: {path}")
        result = subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            loaded = subprocess.run(
                ["launchctl", "print", f"gui/{os.getuid()}/{MACOS_SERVICE_LABEL}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if loaded.returncode == 0:
                raise RuntimeError(result.stderr.strip() or "launchctl bootout failed")
        path.unlink(missing_ok=True)
    return ServiceStatus(True, False, str(path))


def _uninstall_scheduled_task() -> ServiceStatus:
    status = background_agent_status()
    if not status.installed:
        return status
    if not status.recognized:
        raise RuntimeError("Refusing to remove an unrecognized Scheduled Task")
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
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return ServiceStatus(True, False, result.stdout.strip())


def _recognized_agent_command(command: str, arguments: str) -> bool:
    executable = ntpath.basename(command.strip().strip('"')).casefold()
    legacy_binary = bool(re.fullmatch(r"codex-usage-agent(?:-[a-z0-9-]+)?(?:\.exe)?", executable))
    python_module = executable.startswith("python") and "codex_usage.agent_main" in arguments
    return (legacy_binary or python_module) and bool(
        re.search(r"(?:^|\s)--background(?:\s|$)", arguments)
    )


def _recognized_launch_agent(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    try:
        payload = plistlib.loads(path.read_bytes())
        args = payload["ProgramArguments"]
        return (
            payload.get("Label") == MACOS_SERVICE_LABEL
            and isinstance(args, list)
            and len(args) >= 2
            and all(isinstance(arg, str) for arg in args)
            and _recognized_agent_command(args[0], " ".join(args[1:]))
        )
    except (OSError, ValueError, TypeError, KeyError):
        return False


def _recognized_windows_task(payload: str) -> bool:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return False
    ns = {"task": TASK_NAMESPACE}
    command = root.findtext("task:Actions/task:Exec/task:Command", default="", namespaces=ns)
    arguments = root.findtext("task:Actions/task:Exec/task:Arguments", default="", namespaces=ns)
    description = root.findtext("task:RegistrationInfo/task:Description", default="", namespaces=ns)
    return (
        description == "Captures local Codex usage into the Codex Usage ledger."
        and len(root.findall("task:Actions/task:Exec", ns)) == 1
        and _recognized_agent_command(command, arguments)
    )


def _decode_task_output(payload: bytes | str) -> str:
    if isinstance(payload, str):
        return payload
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in payload[:80]:
        return payload.decode("utf-16", errors="replace")
    return payload.decode("utf-8-sig", errors="replace")
