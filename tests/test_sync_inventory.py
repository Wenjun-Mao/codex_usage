from __future__ import annotations

import json
from pathlib import Path

import codex_usage.sync.inventory as inventory
from codex_usage.session_cache import load_cached_session_data
from codex_usage.sync.inventory import (
    build_local_inventory,
    normalize_selected_thread_ids,
)


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
