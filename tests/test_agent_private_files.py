from __future__ import annotations

import os
from pathlib import Path

import pytest

from codex_usage.agent_private_files import (
    ensure_private_directory,
    ensure_private_file,
    windows_acl_command,
)
from codex_usage.ledger_schema import open_ledger


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode test")
def test_private_state_uses_owner_only_posix_modes(tmp_path: Path) -> None:
    directory = tmp_path / "state"
    directory.mkdir(mode=0o755)
    target = directory / "agent.json"
    target.write_text("secret", encoding="utf-8")
    target.chmod(0o644)

    ensure_private_directory(directory)
    ensure_private_file(target)

    assert directory.stat().st_mode & 0o777 == 0o700
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode test")
def test_ledger_and_parent_directory_are_private(tmp_path: Path) -> None:
    ledger = tmp_path / "state" / "usage-ledger.sqlite3"

    with open_ledger(ledger):
        pass

    assert ledger.parent.stat().st_mode & 0o777 == 0o700
    assert ledger.stat().st_mode & 0o777 == 0o600


def test_windows_acl_command_disables_inheritance_and_grants_current_user() -> None:
    command = windows_acl_command(
        Path(r"C:\Users\demo\.codex\.codex-usage"),
        account=r"desktop\demo",
        directory=True,
    )

    assert command == (
        "icacls.exe",
        r"C:\Users\demo\.codex\.codex-usage",
        "/inheritance:r",
        "/grant:r",
        r"desktop\demo:(OI)(CI)F",
        "/Q",
    )
