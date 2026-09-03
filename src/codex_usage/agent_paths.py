from __future__ import annotations

import os
import sys
from pathlib import Path


AGENT_DATA_DIR_NAME = ".codex-usage"
AGENT_DESCRIPTOR_NAME = "agent.json"
AGENT_SETTINGS_NAME = "settings.json"
LEDGER_DATABASE_NAME = "usage-ledger.sqlite3"
STORAGE_DATABASE_NAME = "storage-diagnostics.sqlite3"


def default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    user_profile = os.environ.get("USERPROFILE", "").strip()
    if user_profile:
        return (Path(user_profile).expanduser() / ".codex").resolve()
    return (Path.home() / ".codex").resolve()


def agent_data_dir(codex_home: Path) -> Path:
    return codex_home.expanduser().resolve() / AGENT_DATA_DIR_NAME


def ledger_database_path(codex_home: Path) -> Path:
    return agent_data_dir(codex_home) / LEDGER_DATABASE_NAME


def storage_database_path(codex_home: Path) -> Path:
    return agent_data_dir(codex_home) / STORAGE_DATABASE_NAME


def agent_descriptor_path(codex_home: Path) -> Path:
    return agent_data_dir(codex_home) / AGENT_DESCRIPTOR_NAME


def agent_lock_path(codex_home: Path) -> Path:
    return agent_data_dir(codex_home) / "agent.lock"


def settings_path() -> Path:
    override = os.environ.get("CODEX_USAGE_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve() / AGENT_SETTINGS_NAME
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "Codex Usage"
    elif os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        root = (
            Path(local_app_data)
            if local_app_data
            else Path.home() / "AppData" / "Local"
        ) / "Codex Usage"
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME", "").strip()
        root = Path(xdg_config) if xdg_config else Path.home() / ".config"
        root /= "codex-usage"
    return root / AGENT_SETTINGS_NAME


def validate_codex_home(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"Codex home does not exist: {resolved}")
    if not any((resolved / name).is_dir() for name in ("sessions", "archived_sessions")):
        raise ValueError(
            f"Codex home has no sessions or archived_sessions directory: {resolved}"
        )
    return resolved
