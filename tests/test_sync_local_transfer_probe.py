from __future__ import annotations

import json
from pathlib import Path

import pytest

import codex_usage.parser as parser_module
import codex_usage.sync.io as sync_io
from codex_usage.sync import load_local_transfer_probe


def _write_meta(
    path: Path,
    thread_id: str,
    *,
    cwd: str = "/repo/demo",
    source: object = "cli",
    timestamp: str = "2026-07-31T12:00:00Z",
    repo: str = "",
    trailing_bytes: int = 0,
) -> None:
    payload: dict[str, object] = {
        "id": thread_id,
        "timestamp": timestamp,
        "cwd": cwd,
        "source": source,
    }
    if repo:
        payload["git"] = {"repository_url": repo}
    event = {"timestamp": timestamp, "type": "session_meta", "payload": payload}
    path.write_text(
        json.dumps(event) + "\n" + ("x" * trailing_bytes),
        encoding="utf-8",
    )


def test_local_probe_lists_only_active_root_tasks(tmp_path: Path) -> None:
    active = tmp_path / ".codex" / "sessions"
    archived = tmp_path / ".codex" / "archived_sessions"
    active.mkdir(parents=True)
    archived.mkdir(parents=True)
    _write_meta(active / "root.jsonl", "root", source="cli")
    _write_meta(
        active / "spawned.jsonl",
        "spawned",
        source={"subagent": {"thread_spawn": {"parent_thread_id": "root"}}},
    )
    _write_meta(
        active / "guardian.jsonl",
        "guardian",
        source={"subagent": {"other": "guardian"}},
    )
    _write_meta(archived / "archived.jsonl", "archived", source="cli")

    probe = load_local_transfer_probe([active, archived])

    assert list(probe.inventory.threads) == ["root"]
    assert probe.inventory.discovered_count == 1
    assert probe.issues == ()


def test_local_probe_does_not_require_session_index(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(sessions / "root.jsonl", "root", cwd="/repo/demo", source="cli")
    thread = load_local_transfer_probe([sessions]).inventory.threads["root"]
    assert thread.title == "demo"
    assert thread.total_tokens == 0


def test_local_probe_never_calls_usage_parser_or_hasher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(
        sessions / "root.jsonl",
        "root",
        source="cli",
        trailing_bytes=2_000_000,
    )
    monkeypatch.setattr(
        parser_module,
        "parse_session_file",
        lambda path: pytest.fail("usage parser called"),
    )
    monkeypatch.setattr(
        sync_io,
        "snapshot_file",
        lambda path: pytest.fail("full hash called"),
    )
    assert list(load_local_transfer_probe([sessions]).inventory.threads) == ["root"]


def _sessions_with_root(tmp_path: Path, thread_id: str, *, cwd: str) -> Path:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(sessions / f"{thread_id}.jsonl", thread_id, cwd=cwd, source="cli")
    return sessions


def _write_index(path: Path, thread_id: str, title: str, updated_at: str) -> None:
    path.write_text(
        json.dumps({"id": thread_id, "thread_name": title, "updated_at": updated_at}) + "\n",
        encoding="utf-8",
    )


def test_local_probe_prefers_index_display_metadata(tmp_path: Path) -> None:
    sessions = _sessions_with_root(tmp_path, "root", cwd="/repo/demo")
    _write_index(
        tmp_path / ".codex" / "session_index.jsonl",
        "root",
        "Indexed title",
        "2026-07-31T13:00:00Z",
    )
    thread = load_local_transfer_probe([sessions]).inventory.threads["root"]
    assert (thread.title, thread.updated_at) == (
        "Indexed title",
        "2026-07-31T13:00:00Z",
    )


def test_local_probe_reports_malformed_metadata(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "broken.jsonl").write_text("not-json\n", encoding="utf-8")
    probe = load_local_transfer_probe([sessions])
    assert probe.inventory.threads == {}
    assert [issue.code for issue in probe.issues] == [
        "local_session_metadata_unreadable"
    ]


def test_local_probe_keeps_newest_duplicate_active_identity(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(
        sessions / "old.jsonl",
        "root",
        timestamp="2026-07-30T12:00:00Z",
        source="cli",
    )
    _write_meta(
        sessions / "new.jsonl",
        "root",
        timestamp="2026-07-31T12:00:00Z",
        source="cli",
    )
    assert (
        load_local_transfer_probe([sessions])
        .inventory.threads["root"]
        .session_path.name
        == "new.jsonl"
    )


def test_local_probe_uses_portable_git_identity_for_windows_cwd(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(
        sessions / "root.jsonl",
        "root",
        cwd=r"D:\Projects\Demo",
        repo="https://github.com/Example/Demo.git",
    )
    thread = load_local_transfer_probe([sessions]).inventory.threads["root"]
    assert thread.project_key == "https://github.com/example/demo"
    assert thread.project_label == "demo"
    assert "d:/projects/demo" in thread.project_aliases
