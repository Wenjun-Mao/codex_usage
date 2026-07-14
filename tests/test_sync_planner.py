from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from codex_usage.session_cache import load_cached_session_data
import codex_usage.sync.inventory as inventory
from codex_usage.sync.inventory import build_local_inventory, resolve_selected_thread_ids
from codex_usage.sync.models import LocalInventory, RemoteIndex, RemoteInventory, RemoteThreadEntry, SyncFileSnapshot
from codex_usage.threads import ThreadInfo


def _thread(thread_id: str, project_key: str = "repo", aliases: tuple[str, ...] = ()) -> ThreadInfo:
    return ThreadInfo(
        thread_id=thread_id,
        title=thread_id,
        updated_at="2026-07-13T12:00:00Z",
        session_path=Path("fixtures") / f"{thread_id}.jsonl",
        project_key=project_key,
        project_label=project_key,
        project_aliases=aliases,
        total_tokens=0,
        session_bytes=0,
        estimated_sync_bytes=4096,
    )


def _remote_entry(thread_id: str, project_key: str = "repo") -> RemoteThreadEntry:
    return RemoteThreadEntry(
        thread_id=thread_id,
        file=f"conversations/{thread_id}.jsonl",
        source_relative_path=f"synced/{thread_id}.jsonl",
        index_entry={"id": thread_id},
        project_key=project_key,
        project_label=project_key,
        project_aliases=(),
        sha256="",
        size_bytes=0,
        session_updated_at="2026-07-13T12:00:00Z",
        exported_at="2026-07-13T12:00:00Z",
        source_machine_id="machine-a",
    )


def _local_inventory(*threads: ThreadInfo) -> LocalInventory:
    return LocalInventory(
        session_dirs=(Path("sessions"),),
        threads={item.thread_id: item for item in threads},
        index_entries={},
        discovered_count=len(threads),
    )


def _remote_inventory(*entries: RemoteThreadEntry) -> RemoteInventory:
    index = RemoteIndex(format_version=2, updated_at="", threads={item.thread_id: item for item in entries})
    return RemoteInventory(
        persisted_index=index,
        index=index,
        index_snapshot=SyncFileSnapshot(path=None, exists=False),
        files={},
        repaired_thread_ids=(),
        issues=(),
    )


def test_project_selection_unions_local_and_remote_threads() -> None:
    local = _local_inventory(
        _thread("local", project_key="https://github.com/example/demo", aliases=("/repo/demo",))
    )
    remote = _remote_inventory(
        _remote_entry("remote", project_key="https://github.com/example/demo")
    )

    selected = resolve_selected_thread_ids(
        local,
        remote,
        project_keys=["https://github.com/example/demo"],
        thread_ids=[],
    )

    assert selected == ("local", "remote")


def test_explicit_selection_is_exact_even_when_projects_are_available() -> None:
    local = _local_inventory(_thread("chosen"), _thread("not-chosen"))

    assert resolve_selected_thread_ids(local, _remote_inventory(), [], ["chosen"]) == ("chosen",)


def test_explicit_selection_preserves_unknown_case_sensitive_ids_and_ignores_project_matches() -> None:
    local = _local_inventory(_thread("local", project_key="/repo/demo"))
    remote = _remote_inventory(_remote_entry("remote", project_key="/repo/demo"))

    assert resolve_selected_thread_ids(local, remote, ["/repo/demo"], ["Missing", "local", "Missing"]) == (
        "Missing",
        "local",
    )


def test_project_selection_normalizes_aliases_and_orders_deduplicated_union() -> None:
    local = _local_inventory(
        _thread("z-local", aliases=("https://github.com/example/demo.git",)),
        _thread("a-local", aliases=("https://github.com/example/demo",)),
        _thread("shared", aliases=("https://github.com/example/demo",)),
    )
    remote = _remote_inventory(
        replace(_remote_entry("z-remote"), project_aliases=("https://github.com/example/demo",)),
        replace(_remote_entry("a-remote"), project_aliases=("https://github.com/example/demo",)),
        replace(_remote_entry("shared"), project_aliases=("https://github.com/example/demo",)),
    )

    assert resolve_selected_thread_ids(local, remote, ["Example/Demo"], []) == (
        "a-local",
        "shared",
        "z-local",
        "a-remote",
        "z-remote",
    )


def test_rebuilding_inventory_discovers_new_project_threads(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    cache_dir = tmp_path / "cache"
    _write_session(sessions, "original", "/repo/demo")
    first_inventory = build_local_inventory(
        load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    )
    _write_session(sessions, "new", "/repo/demo")
    rebuilt_inventory = build_local_inventory(
        load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    )

    assert resolve_selected_thread_ids(first_inventory, _remote_inventory(), ["/repo/demo"], []) == ("original",)
    assert resolve_selected_thread_ids(rebuilt_inventory, _remote_inventory(), ["/repo/demo"], []) == (
        "new",
        "original",
    )
    assert first_inventory.discovered_count == 1
    assert rebuilt_inventory.discovered_count == 2


def test_build_inventory_lists_cached_threads_once(tmp_path: Path, monkeypatch: object) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "thread-1", "/repo/demo")
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache", auto_transitions=False)
    original = inventory.list_threads_from_cached_data
    calls = 0

    def list_once(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(inventory, "list_threads_from_cached_data", list_once)

    built = build_local_inventory(data)

    assert calls == 1
    assert tuple(built.threads) == ("thread-1",)


def _write_session(sessions: Path, session_id: str, cwd: str) -> None:
    day = sessions / "2026" / "07" / "13"
    day.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp": "2026-07-13T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": session_id, "timestamp": "2026-07-13T12:00:00Z", "cwd": cwd},
        }
    ]
    (day / f"{session_id}.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
