from __future__ import annotations

import json
from pathlib import Path

import codex_usage.sync.inventory as inventory
import pytest
from codex_usage.session_cache import load_cached_session_data
from codex_usage.sync.inventory import (
    build_local_inventory,
    normalize_selected_thread_ids,
)
from codex_usage.sync.runner import push_sync


def test_normalize_selected_thread_ids_is_exact_case_sensitive_and_deduplicated() -> None:
    assert normalize_selected_thread_ids([" Task/A ", "Task/A", "task/a", ""]) == (
        "Task/A",
        "task/a",
    )


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


@pytest.mark.parametrize("thread_id", [" task ", " \t "], ids=["padded", "whitespace-only"])
def test_build_inventory_rejects_noncanonical_local_thread_ids(
    tmp_path: Path,
    thread_id: str,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    source_path = _write_session(
        sessions,
        thread_id,
        "/repo/demo",
        source_filename="noncanonical-thread-id.jsonl",
    )
    assert source_path.name == "noncanonical-thread-id.jsonl"
    assert (
        json.loads(source_path.read_text(encoding="utf-8"))["payload"]["id"]
        == thread_id
    )
    data = load_cached_session_data(
        [sessions],
        cache_dir=tmp_path / "cache",
        auto_transitions=False,
    )

    with pytest.raises(ValueError, match="local sync inventory.*thread_id"):
        build_local_inventory(data)


def test_build_inventory_rejects_padded_and_canonical_local_identity_collision(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "task", "/repo/demo")
    _write_session(sessions, " task ", "/repo/demo")
    data = load_cached_session_data(
        [sessions],
        cache_dir=tmp_path / "cache",
        auto_transitions=False,
    )

    with pytest.raises(ValueError, match="local sync inventory.*thread_id"):
        build_local_inventory(data)


def test_push_sync_rejects_padded_local_identity_before_any_sync_write(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, " task ", "/repo/demo")
    data = load_cached_session_data(
        [sessions],
        cache_dir=tmp_path / "cache",
        auto_transitions=False,
    )
    sync_dir = tmp_path / "sync"

    with pytest.raises(ValueError, match="local sync inventory.*thread_id"):
        push_sync(
            data=data,
            sync_dir=sync_dir,
            thread_ids=["task"],
            machine_id="machine-a",
            project_key="/repo/demo",
        )

    assert not sync_dir.exists()


def _write_session(
    sessions: Path,
    session_id: str,
    cwd: str,
    *,
    source_filename: str | None = None,
) -> Path:
    day = sessions / "2026" / "07" / "13"
    day.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp": "2026-07-13T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": session_id, "timestamp": "2026-07-13T12:00:00Z", "cwd": cwd},
        }
    ]
    source_path = day / (
        source_filename if source_filename is not None else f"{session_id}.jsonl"
    )
    source_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return source_path
