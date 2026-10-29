"""Discover official Codex runtimes and close owned app-server processes."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path


def discover_codex_executables() -> tuple[str, ...]:
    candidates: list[str] = []
    override = os.environ.get("CODEX_CLI_PATH", "").strip()
    if override:
        # An explicit executable is authoritative. A broken override must not
        # silently start a different installed runtime/account context.
        return (override,)
    if sys.platform == "darwin":
        candidates.extend(_macos_codex_executables())
    elif os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        if str(local):
            roots = (
                local / "OpenAI/Codex/bin",
                local
                / "Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/OpenAI/Codex/bin",
            )
            for root in roots:
                candidates.append(str(root / "codex.exe"))
                if root.is_dir():
                    candidates.extend(str(path / "codex.exe") for path in root.iterdir())
    discovered = shutil.which("codex")
    if discovered:
        candidates.append(discovered)
    candidates.append("codex.exe" if os.name == "nt" else "codex")
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def _macos_codex_executables() -> tuple[str, ...]:
    applications = _macos_chatgpt_applications()
    current_layout = Path(
        "Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
    )
    legacy_layout = Path("Contents/Resources/codex")
    return tuple(
        str(application / layout)
        for layout in (current_layout, legacy_layout)
        for application in applications
    )


def _macos_chatgpt_applications() -> tuple[Path, ...]:
    return (
        Path("/Applications/ChatGPT.app"),
        Path.home() / "Applications" / "ChatGPT.app",
    )


def stop_app_server_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    except (OSError, ProcessLookupError, subprocess.SubprocessError):
        process.kill()
