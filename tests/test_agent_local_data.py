from __future__ import annotations

from pathlib import Path

from codex_usage.agent_local_data import reset_local_data
from codex_usage.agent_paths import (
    agent_data_dir,
    agent_descriptor_path,
    agent_lock_path,
    ledger_database_path,
    storage_database_path,
)


def test_reset_removes_only_owned_state_and_preserves_settings_by_default(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    session = home / "sessions" / "task.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text("task content", encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    retained = agent_data_dir(home) / "user-note.txt"
    retained.parent.mkdir(parents=True)
    retained.write_text("keep", encoding="utf-8")
    for path in (
        ledger_database_path(home),
        storage_database_path(home),
        agent_descriptor_path(home),
        agent_lock_path(home),
    ):
        path.write_text("owned", encoding="utf-8")
    rebuild = agent_data_dir(home) / "rebuilds" / "staging.sqlite3"
    rebuild.parent.mkdir()
    rebuild.write_text("owned", encoding="utf-8")

    result = reset_local_data(home, settings_file=settings)

    assert result["removed_settings"] is False
    assert session.read_text(encoding="utf-8") == "task content"
    assert settings.is_file()
    assert retained.read_text(encoding="utf-8") == "keep"
    assert not ledger_database_path(home).exists()
    assert not storage_database_path(home).exists()
    assert not agent_descriptor_path(home).exists()
    assert not agent_lock_path(home).exists()
    assert not rebuild.parent.exists()


def test_reset_can_remove_settings_during_uninstall(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    home.mkdir()
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")

    reset_local_data(home, remove_settings=True, settings_file=settings)

    assert not settings.exists()
