from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from codex_usage.parser import CHECKPOINT_DIGEST_BYTES
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data


def test_large_file_append_reads_only_tail_and_guard_windows(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/demo", 100)
    with session_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n"
            + json.dumps(
                {
                    "type": "response_item",
                    "payload": {"type": "message", "text": "x" * 2_000_000},
                }
            )
        )
    cache_dir = tmp_path / "cache"
    _load(sessions, cache_dir)
    old_size = session_path.stat().st_size
    _append_token_count(session_path, "2026-04-29T10:05:00Z", 150)
    tail_size = session_path.stat().st_size - old_size

    data = _load(sessions, cache_dir)

    assert data.stats.files_appended == 1
    assert data.stats.files_full_parsed == 0
    assert data.stats.source_bytes_read <= tail_size + 4 * CHECKPOINT_DIGEST_BYTES
    assert data.stats.source_bytes_read < old_size // 2
    assert [record.usage.total_tokens for record in data.records] == [100, 50]


def test_same_size_modification_forces_full_parse(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/demo", 100)
    cache_dir = tmp_path / "cache"
    _load(sessions, cache_dir)
    original_stat = session_path.stat()
    changed = session_path.read_text(encoding="utf-8").replace(
        "/repo/demo", "/repo/dema"
    )
    session_path.write_text(changed, encoding="utf-8")
    os.utime(
        session_path,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 1_000_000),
    )

    data = _load(sessions, cache_dir)

    assert data.stats.files_full_parsed == 1
    assert data.stats.files_appended == 0
    assert data.stats.append_fallbacks == 0
    assert [record.cwd for record in data.records] == ["/repo/dema"]


def test_truncation_forces_full_parse_and_removes_appended_rows(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/demo", 100)
    original_bytes = session_path.read_bytes()
    cache_dir = tmp_path / "cache"
    _load(sessions, cache_dir)
    _append_token_count(session_path, "2026-04-29T10:05:00Z", 150)
    appended = _load(sessions, cache_dir)
    assert [record.usage.total_tokens for record in appended.records] == [100, 50]
    session_path.write_bytes(original_bytes)

    truncated = _load(sessions, cache_dir)

    assert truncated.stats.files_full_parsed == 1
    assert truncated.stats.files_appended == 0
    assert [record.usage.total_tokens for record in truncated.records] == [100]


def test_atomic_replacement_forces_full_parse(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/demo", 100)
    cache_dir = tmp_path / "cache"
    _load(sessions, cache_dir)
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_bytes(session_path.read_bytes())
    _append_token_count(replacement, "2026-04-29T10:05:00Z", 175)
    os.replace(replacement, session_path)

    data = _load(sessions, cache_dir)

    assert data.stats.files_full_parsed == 1
    assert data.stats.files_appended == 0
    assert [record.usage.total_tokens for record in data.records] == [100, 75]


def test_boundary_modification_falls_back_from_append_to_full_parse(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/demo", 100)
    with session_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n"
            + json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "text": "x" * (CHECKPOINT_DIGEST_BYTES * 3),
                    },
                }
            )
        )
    cache_dir = tmp_path / "cache"
    _load(sessions, cache_dir)
    old_size = session_path.stat().st_size
    _append_token_count(session_path, "2026-04-29T10:05:00Z", 150)
    with session_path.open("r+b") as handle:
        handle.seek(old_size - 20)
        handle.write(b"y")

    data = _load(sessions, cache_dir)

    assert data.stats.files_full_parsed == 1
    assert data.stats.files_appended == 0
    assert data.stats.append_fallbacks == 1
    assert [record.usage.total_tokens for record in data.records] == [100, 50]


def test_invalid_checkpoint_state_forces_full_parse(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/demo", 100)
    cache_dir = tmp_path / "cache"
    _load(sessions, cache_dir)
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        connection.execute(
            "update parser_checkpoints set state_json = '[]' where file_key = 'thread-1'"
        )
    _append_token_count(session_path, "2026-04-29T10:05:00Z", 150)

    data = _load(sessions, cache_dir)

    assert data.stats.files_full_parsed == 1
    assert data.stats.files_appended == 0
    assert [record.usage.total_tokens for record in data.records] == [100, 50]


def test_incomplete_cached_tail_is_completed_by_append_parse(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/demo", 100)
    row = json.dumps(_token_count("2026-04-29T10:05:00Z", 175)).encode()
    split_at = len(row) // 2
    with session_path.open("ab") as handle:
        handle.write(b"\n" + row[:split_at])
    cache_dir = tmp_path / "cache"

    first = _load(sessions, cache_dir)
    with session_path.open("ab") as handle:
        handle.write(row[split_at:])
    completed = _load(sessions, cache_dir)

    assert [record.usage.total_tokens for record in first.records] == [100]
    assert completed.stats.files_appended == 1
    assert [record.usage.total_tokens for record in completed.records] == [100, 75]


def test_changed_archived_file_never_uses_append_checkpoint(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/demo", 100)
    cache_dir = tmp_path / "cache"
    load_cached_session_data(
        [sessions, archived],
        cache_dir=cache_dir,
        auto_transitions=False,
        max_workers=1,
    )
    archived_path = archived / "2026" / "04" / "29" / session_path.name
    archived_path.parent.mkdir(parents=True)
    session_path.replace(archived_path)
    load_cached_session_data(
        [sessions, archived],
        cache_dir=cache_dir,
        auto_transitions=False,
        max_workers=1,
    )
    _append_token_count(archived_path, "2026-04-29T10:05:00Z", 150)

    data = load_cached_session_data(
        [sessions, archived],
        cache_dir=cache_dir,
        auto_transitions=False,
        max_workers=1,
    )

    assert data.stats.files_full_parsed == 1
    assert data.stats.files_appended == 0
    assert data.stats.append_fallbacks == 0
    assert [record.usage.total_tokens for record in data.records] == [100, 50]


def _load(sessions: Path, cache_dir: Path):
    return load_cached_session_data(
        [sessions],
        cache_dir=cache_dir,
        auto_transitions=False,
        max_workers=1,
    )


def _write_session(sessions: Path, session_id: str, cwd: str, total: int) -> Path:
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"{session_id}.jsonl"
    rows = [
        {
            "timestamp": "2026-04-29T10:00:00Z",
            "type": "session_meta",
            "payload": {"id": session_id, "cwd": cwd},
        },
        {
            "timestamp": "2026-04-29T10:00:01Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.5"},
        },
        _token_count("2026-04-29T10:00:02Z", total),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _append_token_count(path: Path, timestamp: str, total: int) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps(_token_count(timestamp, total)))


def _token_count(timestamp: str, total: int) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total,
                    "total_tokens": total,
                }
            },
        },
    }
