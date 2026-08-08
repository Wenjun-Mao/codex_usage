import errno
import json
from pathlib import Path

import pytest

from codex_usage.session_files import (
    load_all_index_entries,
    read_session_metadata_bounded,
)


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


def test_session_metadata_retries_transient_filesystem_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "task.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {"id": "task", "cwd": "/repo"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    original_open = Path.open
    calls = 0

    def flaky_open(candidate: Path, *args: object, **kwargs: object):
        nonlocal calls
        if candidate == path and calls < 2:
            calls += 1
            raise OSError(errno.EBUSY, "temporarily busy")
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)

    result = read_session_metadata_bounded(path)

    assert result.metadata is not None
    assert result.metadata.session_id == "task"
    assert calls == 2
