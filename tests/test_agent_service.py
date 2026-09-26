from __future__ import annotations

import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_usage import agent_service
from codex_usage.agent_main import build_agent_parser


def _legacy_windows_task_xml(command: str) -> str:
    namespace = agent_service.TASK_NAMESPACE
    return (
        f'<Task xmlns="{namespace}">'
        '<RegistrationInfo><Description>Captures local Codex usage into the Codex Usage ledger.</Description></RegistrationInfo>'
        f'<Actions><Exec><Command>{command}</Command><Arguments>--background</Arguments></Exec></Actions>'
        '</Task>'
    )


def test_macos_retirement_rejects_an_unrecognized_registration(
    monkeypatch, tmp_path: Path,
) -> None:
    path = tmp_path / "com.wenjunmao.codex-usage-agent.plist"
    path.write_bytes(plistlib.dumps({
        "Label": agent_service.MACOS_SERVICE_LABEL,
        "ProgramArguments": ["/tmp/unrelated-agent", "--background"],
    }))
    monkeypatch.setattr(agent_service, "_launch_agent_path", lambda: path)
    monkeypatch.setattr(agent_service.subprocess, "run", lambda *_args, **_kwargs: None)

    assert not agent_service._recognized_launch_agent(path)
    try:
        agent_service._uninstall_launch_agent()
    except RuntimeError as exc:
        assert "unrecognized" in str(exc)
    else:
        raise AssertionError("unrecognized service was removed")
    assert path.exists()


def test_macos_retirement_removes_only_recognized_registration(
    monkeypatch, tmp_path: Path,
) -> None:
    path = tmp_path / "com.wenjunmao.codex-usage-agent.plist"
    path.write_bytes(plistlib.dumps({
        "Label": agent_service.MACOS_SERVICE_LABEL,
        "ProgramArguments": ["/missing/codex-usage-agent-aarch64-apple-darwin", "--background"],
    }))
    calls: list[list[str]] = []
    monkeypatch.setattr(agent_service, "_launch_agent_path", lambda: path)
    monkeypatch.setattr(agent_service.os, "getuid", lambda: 501, raising=False)

    def run(args, **_kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(agent_service.subprocess, "run", run)
    result = agent_service._uninstall_launch_agent()
    assert result.installed is False
    assert not path.exists()
    assert calls == [["launchctl", "bootout", "gui/501", str(path)]]


def test_macos_retirement_keeps_registration_if_loaded_service_cannot_stop(
    monkeypatch, tmp_path: Path,
) -> None:
    path = tmp_path / "com.wenjunmao.codex-usage-agent.plist"
    path.write_bytes(plistlib.dumps({
        "Label": agent_service.MACOS_SERVICE_LABEL,
        "ProgramArguments": ["/missing/codex-usage-agent", "--background"],
    }))
    monkeypatch.setattr(agent_service, "_launch_agent_path", lambda: path)
    monkeypatch.setattr(agent_service.os, "getuid", lambda: 501, raising=False)

    def run(args, **_kwargs):
        return SimpleNamespace(
            returncode=1 if "bootout" in args else 0,
            stdout="", stderr="bootout failed",
        )

    monkeypatch.setattr(agent_service.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="bootout failed"):
        agent_service._uninstall_launch_agent()
    assert path.exists()


def test_windows_retirement_identity_is_in_task_xml() -> None:
    payload = _legacy_windows_task_xml(
        r"C:\Program Files\Codex Usage\codex-usage-agent.exe"
    )
    assert agent_service._recognized_windows_task(payload)
    assert agent_service._recognized_windows_task(
        agent_service._decode_task_output(payload.encode("utf-16"))
    )
    assert not agent_service._recognized_windows_task(
        payload.replace("codex-usage-agent.exe", "unrelated.exe")
    )


def test_companion_collector_has_no_service_install_control() -> None:
    with pytest.raises(SystemExit):
        build_agent_parser().parse_args(["--install-service"])


def test_windows_retirement_never_deletes_an_unrecognized_task(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_service, "background_agent_status",
        lambda: agent_service.ServiceStatus(True, True, "existing", False),
    )
    monkeypatch.setattr(
        agent_service.subprocess, "run",
        lambda *_args, **_kwargs: pytest.fail("Scheduled Task was touched"),
    )
    with pytest.raises(RuntimeError, match="unrecognized"):
        agent_service._uninstall_scheduled_task()
