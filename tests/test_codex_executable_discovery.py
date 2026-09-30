import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import codex_usage.allowance_probe as allowance_probe
import codex_usage.codex_registration as codex_registration
from codex_usage.app_server_rpc import AppServerRpc


CURRENT_MACOS_CLI = Path(
    "Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
)
LEGACY_MACOS_CLI = Path("Contents/Resources/codex")


def test_macos_discovery_keeps_override_current_legacy_and_path_candidates(
    tmp_path, monkeypatch
):
    system_app = Path("/Applications/ChatGPT.app")
    user_app = tmp_path / "Applications" / "ChatGPT.app"
    monkeypatch.setattr(codex_registration.sys, "platform", "darwin")
    monkeypatch.setattr(
        codex_registration,
        "_macos_chatgpt_applications",
        lambda: (system_app, user_app),
    )
    monkeypatch.setattr(codex_registration.shutil, "which", lambda _: "/path/codex")
    monkeypatch.setenv("CODEX_CLI_PATH", "/explicit/codex")

    candidates = codex_registration.discover_codex_executables()

    assert candidates == (
        "/explicit/codex",
        str(system_app / CURRENT_MACOS_CLI),
        str(user_app / CURRENT_MACOS_CLI),
        str(system_app / LEGACY_MACOS_CLI),
        str(user_app / LEGACY_MACOS_CLI),
        "/path/codex",
        "codex",
    )


def test_windows_discovery_keeps_localappdata_and_path_fallbacks(tmp_path, monkeypatch):
    local_app_data = tmp_path / "LocalAppData"
    versioned = local_app_data / "OpenAI" / "Codex" / "bin" / "version-1"
    versioned.mkdir(parents=True)
    environment = {"LOCALAPPDATA": str(local_app_data)}
    monkeypatch.setattr(
        codex_registration,
        "os",
        SimpleNamespace(name="nt", environ=environment),
    )
    monkeypatch.setattr(codex_registration.sys, "platform", "win32")
    monkeypatch.setattr(codex_registration.shutil, "which", lambda _: "C:/path/codex.exe")

    candidates = codex_registration.discover_codex_executables()

    assert str(local_app_data / "OpenAI/Codex/bin/codex.exe") in candidates
    assert str(versioned / "codex.exe") in candidates
    assert "C:/path/codex.exe" in candidates
    assert candidates[-1] == "codex.exe"


@pytest.mark.skipif(os.name == "nt", reason="Uses a POSIX executable in a fake app bundle")
def test_metadata_probe_finds_bundled_cli_without_override_or_path_codex(
    tmp_path, monkeypatch
):
    system_app = tmp_path / "System Applications" / "ChatGPT.app"
    user_app = tmp_path / "home" / "Applications" / "ChatGPT.app"
    executable = user_app / CURRENT_MACOS_CLI
    executable.parent.mkdir(parents=True)
    executable.write_text(
        f'''#!{sys.executable}
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    result = {{
        "initialize": {{}},
        "account/read": {{"account": {{"planType": "pro", "email": "PRIVATE"}}}},
        "account/rateLimits/read": {{"rateLimitsByLimitId": {{"codex": {{
            "limitId": "codex", "planType": "pro",
            "primary": {{"usedPercent": 51, "windowDurationMins": 10080,
                        "resetsAt": 2000000000}}
        }}}}}},
        "account/usage/read": {{"summary": {{"lifetimeTokens": 123}},
                                "secret": "PRIVATE"}},
    }}[method]
    print(json.dumps({{"id": request["id"], "result": result}}), flush=True)
''',
        encoding="utf-8",
    )
    executable.chmod(0o700)

    launched = []

    class RecordingRpc(AppServerRpc):
        def __init__(self, selected, *args, **kwargs):
            launched.append(selected)
            super().__init__(selected, *args, **kwargs)

    monkeypatch.setattr(codex_registration.sys, "platform", "darwin")
    monkeypatch.setattr(
        codex_registration,
        "_macos_chatgpt_applications",
        lambda: (system_app, user_app),
    )
    monkeypatch.setattr(codex_registration.shutil, "which", lambda _: None)
    monkeypatch.setattr(allowance_probe, "AppServerRpc", RecordingRpc)
    monkeypatch.delenv("CODEX_CLI_PATH", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))

    read = allowance_probe.probe_allowance(tmp_path / "codex-home", timeout=4)

    assert str(executable) in launched
    assert read.plan == "pro"
    assert [(item.limit_id, item.used_percent) for item in read.observations] == [
        ("codex", 51)
    ]
    assert read.lifetime_tokens == 123
    assert "PRIVATE" not in repr(read)
