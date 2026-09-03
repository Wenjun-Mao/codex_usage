from __future__ import annotations

import plistlib
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from codex_usage import agent_service
from codex_usage.agent_windows_task import TASK_NAMESPACE, windows_task_xml


def test_windows_background_task_is_persistent_and_least_privilege() -> None:
    payload = windows_task_xml(
        [r"C:\Program Files\Codex Usage\codex-usage-agent.exe", "--background"],
        account=r"desktop\user",
    )
    root = ET.fromstring(payload)
    namespace = {"task": TASK_NAMESPACE}

    assert root.findtext("task:Triggers/task:LogonTrigger/task:UserId", namespaces=namespace) == r"desktop\user"
    assert root.findtext("task:Principals/task:Principal/task:LogonType", namespaces=namespace) == "InteractiveToken"
    assert root.findtext("task:Principals/task:Principal/task:RunLevel", namespaces=namespace) == "LeastPrivilege"
    assert root.findtext("task:Settings/task:StartWhenAvailable", namespaces=namespace) == "true"
    assert root.findtext("task:Settings/task:ExecutionTimeLimit", namespaces=namespace) == "PT0S"
    assert root.findtext("task:Settings/task:RestartOnFailure/task:Interval", namespaces=namespace) == "PT1M"
    assert root.findtext("task:Settings/task:RestartOnFailure/task:Count", namespaces=namespace) == "3"
    assert root.findtext("task:Actions/task:Exec/task:Arguments", namespaces=namespace) == "--background"


def test_macos_background_service_secures_its_log_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    launch_agent = tmp_path / "Library" / "LaunchAgents" / "agent.plist"
    settings = tmp_path / "Application Support" / "Codex Usage" / "settings.json"
    secured: list[Path] = []

    monkeypatch.setattr(agent_service, "_launch_agent_path", lambda: launch_agent)
    monkeypatch.setattr(agent_service, "settings_path", lambda: settings)
    monkeypatch.setattr(agent_service.os, "getuid", lambda: 501, raising=False)

    def secure(path: Path) -> None:
        secured.append(path)
        path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(agent_service, "ensure_private_directory", secure)
    monkeypatch.setattr(
        agent_service.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = agent_service._install_launch_agent(["codex-usage-agent", "--background"])

    assert result.installed is True
    assert secured == [settings.parent / "logs"]
    payload = plistlib.loads(launch_agent.read_bytes())
    assert payload["StandardOutPath"] == str(settings.parent / "logs" / "agent.log")
    assert payload["StandardErrorPath"] == str(settings.parent / "logs" / "agent.error.log")
