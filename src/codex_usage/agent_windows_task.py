from __future__ import annotations

import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


TASK_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def install_windows_task(command: list[str], task_name: str) -> str:
    account = _current_windows_account()
    payload = windows_task_xml(command, account=account)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="codex-usage-task-", suffix=".xml"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        result = subprocess.run(
            [
                "schtasks.exe",
                "/Create",
                "/TN",
                task_name,
                "/XML",
                str(temporary),
                "/F",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        subprocess.run(
            ["schtasks.exe", "/Run", "/TN", task_name],
            capture_output=True,
            check=False,
        )
        return result.stdout.strip()
    finally:
        temporary.unlink(missing_ok=True)


def windows_task_xml(command: list[str], *, account: str) -> bytes:
    if not command or not command[0]:
        raise ValueError("background agent command is empty")
    if not account:
        raise ValueError("Windows account is required")
    ET.register_namespace("", TASK_NAMESPACE)
    task = ET.Element(_tag("Task"), {"version": "1.4"})
    registration = ET.SubElement(task, _tag("RegistrationInfo"))
    ET.SubElement(registration, _tag("Description")).text = (
        "Captures local Codex usage into the Codex Usage ledger."
    )
    triggers = ET.SubElement(task, _tag("Triggers"))
    logon = ET.SubElement(triggers, _tag("LogonTrigger"))
    ET.SubElement(logon, _tag("Enabled")).text = "true"
    ET.SubElement(logon, _tag("UserId")).text = account
    principals = ET.SubElement(task, _tag("Principals"))
    principal = ET.SubElement(principals, _tag("Principal"), {"id": "Author"})
    ET.SubElement(principal, _tag("UserId")).text = account
    ET.SubElement(principal, _tag("LogonType")).text = "InteractiveToken"
    ET.SubElement(principal, _tag("RunLevel")).text = "LeastPrivilege"
    settings = ET.SubElement(task, _tag("Settings"))
    for name, value in (
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"),
        ("AllowHardTerminate", "true"),
        ("StartWhenAvailable", "true"),
        ("RunOnlyIfNetworkAvailable", "false"),
        ("AllowStartOnDemand", "true"),
        ("Enabled", "true"),
        ("Hidden", "false"),
        ("RunOnlyIfIdle", "false"),
        ("WakeToRun", "false"),
        ("ExecutionTimeLimit", "PT0S"),
        ("Priority", "7"),
    ):
        ET.SubElement(settings, _tag(name)).text = value
    restart = ET.SubElement(settings, _tag("RestartOnFailure"))
    ET.SubElement(restart, _tag("Interval")).text = "PT1M"
    ET.SubElement(restart, _tag("Count")).text = "3"
    actions = ET.SubElement(task, _tag("Actions"), {"Context": "Author"})
    execute = ET.SubElement(actions, _tag("Exec"))
    ET.SubElement(execute, _tag("Command")).text = command[0]
    if len(command) > 1:
        ET.SubElement(execute, _tag("Arguments")).text = subprocess.list2cmdline(
            command[1:]
        )
    return ET.tostring(task, encoding="utf-16", xml_declaration=True)


def _current_windows_account() -> str:
    result = subprocess.run(
        ["whoami.exe"],
        capture_output=True,
        text=True,
        check=False,
    )
    account = result.stdout.strip()
    if result.returncode != 0 or not account:
        raise RuntimeError(result.stderr.strip() or "could not identify Windows account")
    return account


def _tag(name: str) -> str:
    return f"{{{TASK_NAMESPACE}}}{name}"
