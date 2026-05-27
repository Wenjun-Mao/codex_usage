import json
from pathlib import Path

from codex_usage.session_files import load_all_index_entries


def test_load_all_index_entries_keeps_newest_entry_per_thread(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    index = codex_home / "session_index.jsonl"
    rows = [
        {"id": "thread-1", "thread_name": "old", "updated_at": "2026-05-20T10:00:00Z"},
        {"id": "thread-1", "thread_name": "new", "updated_at": "2026-05-21T10:00:00Z"},
        {"id": "thread-2", "thread_name": "other", "updated_at": "2026-05-20T11:00:00Z"},
    ]
    index.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    entries = load_all_index_entries([sessions])

    assert entries["thread-1"]["thread_name"] == "new"
    assert entries["thread-2"]["thread_name"] == "other"
