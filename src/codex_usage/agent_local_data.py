from __future__ import annotations

import shutil
from pathlib import Path

from codex_usage.agent_paths import (
    agent_data_dir,
    agent_descriptor_path,
    agent_lock_path,
    ledger_database_path,
    settings_path,
    storage_database_path,
)


def reset_local_data(
    codex_home: Path,
    *,
    remove_settings: bool = False,
    settings_file: Path | None = None,
) -> dict[str, object]:
    """Remove only Codex Usage-owned state after the agent has stopped."""
    removed: list[str] = []
    for database in (
        ledger_database_path(codex_home),
        storage_database_path(codex_home),
    ):
        for suffix in ("", "-wal", "-shm"):
            _remove_file(database.with_name(database.name + suffix), removed)
    _remove_file(agent_descriptor_path(codex_home), removed)
    _remove_file(agent_lock_path(codex_home), removed)
    rebuilds = agent_data_dir(codex_home) / "rebuilds"
    if rebuilds.is_dir():
        shutil.rmtree(rebuilds)
        removed.append(str(rebuilds))
    if remove_settings:
        _remove_file(settings_file or settings_path(), removed)
    return {
        "codex_home": str(codex_home),
        "removed_settings": remove_settings,
        "removed": removed,
    }


def _remove_file(path: Path, removed: list[str]) -> None:
    if not path.exists():
        return
    if not path.is_file():
        raise ValueError(f"refusing to remove unexpected non-file state: {path}")
    path.unlink()
    removed.append(str(path))
