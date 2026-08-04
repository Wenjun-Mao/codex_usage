import json
import os
import sqlite3
from pathlib import Path

import pytest

import codex_usage.parallel.usage as usage_module
import codex_usage.session_cache_refresh as cache_refresh_module
import codex_usage.session_cache_schema as cache_schema_module
from codex_usage.session_cache import (
    CACHE_DB_NAME,
    CACHE_SCHEMA_VERSION,
    load_cached_session_data,
    resolve_cache_dir,
)


def test_first_cache_build_parses_and_stores_records(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/demo", 100, cache_write=25)
    cache_dir = tmp_path / "cache"

    data = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    assert data.files == [session_path]
    assert data.stats.files_parsed == 1
    assert data.file_summaries[session_path].estimated_sync_bytes == session_path.stat().st_size + 4096
    assert data.stats.files_reused == 0
    assert data.records[0].session_id == "thread-1"
    assert data.records[0].usage.total_tokens == 100
    assert data.records[0].usage.cache_write_input_tokens == 25
    assert (cache_dir / CACHE_DB_NAME).is_file()


def test_legacy_cache_files_are_removed_after_schema_opens(tmp_path: Path) -> None:
    assert CACHE_DB_NAME == "usage-cache-v4.sqlite3"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    legacy_paths = tuple(
        cache_dir / f"usage-cache.sqlite3{suffix}" for suffix in ("", "-wal", "-shm")
    )
    for path in legacy_paths:
        path.write_text("legacy", encoding="utf-8")

    data = load_cached_session_data([], cache_dir=cache_dir, auto_transitions=False)

    assert data.stats.legacy_cleanup_errors == 0
    assert not any(path.exists() for path in legacy_paths)
    assert (cache_dir / CACHE_DB_NAME).is_file()


def test_legacy_cleanup_failure_is_counted_without_removing_new_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert CACHE_DB_NAME == "usage-cache-v4.sqlite3"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    legacy_path = cache_dir / "usage-cache.sqlite3"
    legacy_path.write_text("legacy", encoding="utf-8")
    attempts = 0
    original_unlink = Path.unlink

    def fail_legacy_unlink(path: Path, *args, **kwargs) -> None:
        nonlocal attempts
        if path == legacy_path:
            attempts += 1
            raise OSError("legacy cache is busy")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_legacy_unlink)

    data = load_cached_session_data([], cache_dir=cache_dir, auto_transitions=False)

    assert attempts == 3
    assert data.stats.legacy_cleanup_errors == 1
    assert legacy_path.is_file()
    assert (cache_dir / CACHE_DB_NAME).is_file()


def test_unchanged_file_is_reused_without_reparse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "thread-1", "/repo/demo", 100, cache_write=25)
    cache_dir = tmp_path / "cache"
    load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )

    def fail_parse(_path: Path):
        raise AssertionError("unchanged file should be loaded from cache")

    monkeypatch.setattr(usage_module, "parse_session_generation", fail_parse)
    data = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )

    assert data.stats.files_reused == 1
    assert data.records[0].usage.total_tokens == 100
    assert data.records[0].usage.cache_write_input_tokens == 25


def test_changed_file_reparses_when_size_or_mtime_changes(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/demo", 100)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    _append_token_count(session_path, "2026-04-29T10:05:00Z", 150)
    os.utime(session_path, None)

    data = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    assert data.stats.files_parsed == 1
    assert [record.usage.total_tokens for record in data.records] == [100, 50]


def test_removed_file_retains_cached_usage_as_missing(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    first = _write_session(sessions, "thread-1", "/repo/one", 100)
    _write_session(sessions, "thread-2", "/repo/two", 75)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    first.unlink()

    data = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    assert data.stats.files_missing_retained == 1
    assert sorted(record.session_id for record in data.records) == ["thread-1", "thread-2"]
    assert sum(record.usage.total_tokens for record in data.records) == 175


def test_archived_move_does_not_double_count_cached_usage(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    active = _write_session(sessions, "thread-1", "/repo/one", 100)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions, archived], cache_dir=cache_dir, auto_transitions=False)

    archived_path = archived / "2026" / "04" / "29" / active.name
    archived_path.parent.mkdir(parents=True)
    active.replace(archived_path)

    data = load_cached_session_data([sessions, archived], cache_dir=cache_dir, auto_transitions=False)

    assert data.stats.files_total == 1
    assert data.stats.files_missing_retained == 0
    assert [record.session_id for record in data.records] == ["thread-1"]
    assert [record.usage.total_tokens for record in data.records] == [100]


def test_active_and_archived_duplicate_prefers_active_file(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    active = _write_session(sessions, "thread-1", "/repo/active", 100)
    _write_session(archived, "thread-1", "/repo/archived", 100)
    cache_dir = tmp_path / "cache"

    data = load_cached_session_data([sessions, archived], cache_dir=cache_dir, auto_transitions=False)

    assert data.files == [active]
    assert [record.cwd for record in data.records] == ["/repo/active"]


def test_schema_version_mismatch_rebuilds_cache(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "thread-1", "/repo/demo", 100, cache_write=25)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    db_path = cache_dir / CACHE_DB_NAME

    with sqlite3.connect(db_path) as connection:
        connection.execute("update schema_meta set value = ? where key = 'schema_version'", ("old",))

    data = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    assert data.stats.rebuilt is True
    assert data.records[0].usage.total_tokens == 100
    assert data.records[0].usage.cache_write_input_tokens == 25
    assert data.stats.files_parsed == 1
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("select value from schema_meta where key = 'schema_version'").fetchone()
    assert row == (str(CACHE_SCHEMA_VERSION),)


def test_schema_creation_failure_rolls_back_entire_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "thread-1", "/repo/demo", 100)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    db_path = cache_dir / CACHE_DB_NAME

    with sqlite3.connect(db_path) as connection:
        connection.execute("update schema_meta set value = ? where key = 'schema_version'", ("old",))

    original_create = cache_schema_module._create_cache_schema

    def fail_after_schema_creation(connection: sqlite3.Connection) -> None:
        original_create(connection)
        raise sqlite3.DatabaseError("schema creation interrupted")

    monkeypatch.setattr(
        cache_schema_module, "_create_cache_schema", fail_after_schema_creation
    )

    with pytest.raises(sqlite3.DatabaseError, match="schema creation interrupted"):
        load_cached_session_data(
            [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
        )

    with sqlite3.connect(db_path) as connection:
        schema_version = connection.execute(
            "select value from schema_meta where key = 'schema_version'"
        ).fetchone()
        usage_rows = connection.execute(
            "select session_id, total_tokens from usage_records order by file_key, record_index"
        ).fetchall()

    assert schema_version == ("old",)
    assert usage_rows == [("thread-1", 100)]


def test_interrupted_schema_rebuild_reparses_active_file_on_next_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/demo", 100, cache_write=25)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    db_path = cache_dir / CACHE_DB_NAME

    with sqlite3.connect(db_path) as connection:
        connection.execute("update usage_records set cache_write_input_tokens = 0")
        connection.execute("update schema_meta set value = ? where key = 'schema_version'", ("old",))

    original_refresh = cache_refresh_module.refresh_files

    def interrupt_refresh(*_args, **_kwargs):
        raise RuntimeError("interrupted after schema reset")

    monkeypatch.setattr(cache_refresh_module, "refresh_files", interrupt_refresh)
    with pytest.raises(RuntimeError, match="interrupted after schema reset"):
        load_cached_session_data(
            [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
        )

    monkeypatch.setattr(cache_refresh_module, "refresh_files", original_refresh)
    recovered = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )

    assert recovered.files == [session_path]
    assert recovered.stats.files_parsed == 1
    assert recovered.stats.files_reused == 0
    assert recovered.file_errors == {}
    assert recovered.records[0].usage.cache_write_input_tokens == 25


def test_parse_error_without_prior_success_retries_unchanged_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "thread-1", "/repo/demo", 100)
    cache_dir = tmp_path / "cache"
    original_parser = usage_module.parse_session_generation

    def fail_parse(_path: Path):
        raise OSError("transient first-read failure")

    monkeypatch.setattr(usage_module, "parse_session_generation", fail_parse)
    failed = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert failed.stats.file_errors == 1
    assert failed.records == []

    monkeypatch.setattr(usage_module, "parse_session_generation", original_parser)
    recovered = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )

    assert recovered.stats.files_parsed == 1
    assert recovered.stats.files_reused == 0
    assert recovered.file_errors == {}
    assert [record.usage.total_tokens for record in recovered.records] == [100]


def test_corrupt_file_records_error_and_keeps_other_files(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "thread-1", "/repo/good", 100)
    bad = sessions / "2026" / "04" / "29" / "bad.jsonl"
    bad.write_bytes(b'{"type": "session_meta", "payload": {"id": "bad"}}\n\xff\xfe\n')
    cache_dir = tmp_path / "cache"

    data = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    assert [record.session_id for record in data.records] == ["thread-1"]
    assert data.stats.file_errors == 1
    assert data.file_errors[str(bad)]


def test_parse_failure_keeps_previous_cached_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/demo", 100)
    cache_dir = tmp_path / "cache"
    load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    _append_token_count(session_path, "2026-04-29T10:05:00Z", 150)
    os.utime(session_path, None)

    def fail_parse(_path: Path):
        raise OSError("transient read failure")

    monkeypatch.setattr(usage_module, "parse_session_generation", fail_parse)

    data = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )

    assert data.stats.file_errors == 1
    assert data.file_errors[str(session_path)] == "OSError: transient read failure"
    assert [record.usage.total_tokens for record in data.records] == [100]


def test_resolve_cache_dir_prefers_internal_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_cache = tmp_path / "env-cache"
    monkeypatch.setenv("CODEX_USAGE_CACHE_DIR", str(env_cache))

    assert resolve_cache_dir([tmp_path / "codex" / "sessions"]) == env_cache


def _write_session(sessions: Path, session_id: str, cwd: str, total: int, cache_write: int = 0) -> Path:
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"{session_id}.jsonl"
    rows = [
        {
            "timestamp": "2026-04-29T10:00:00Z",
            "type": "session_meta",
            "payload": {"id": session_id, "timestamp": "2026-04-29T10:00:00Z", "cwd": cwd},
        },
        {"timestamp": "2026-04-29T10:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.5"}},
        _token_count("2026-04-29T10:00:02Z", total, cache_write=cache_write),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _append_token_count(path: Path, timestamp: str, total: int, cache_write: int = 0) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps(_token_count(timestamp, total, cache_write=cache_write)))


def _token_count(timestamp: str, total: int, cache_write: int = 0) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total,
                    "cached_input_tokens": 0,
                    "cache_write_input_tokens": cache_write,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "total_tokens": total,
                }
            },
        },
    }
