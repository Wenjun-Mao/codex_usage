from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cached_ownership_handoff_support import (
    _append_ignored_event,
    _append_token_count,
    _dirty_task_ids,
    _ownership_snapshot,
    _ownership_snapshot_for_connection,
    _repo_key,
    _transition_targets,
    _write_git_config,
    _write_handoff_corpus,
    _write_mixed_session,
    _write_session,
)

import codex_usage.parallel.usage as usage_module
import codex_usage.session_cache_ownership as ownership_module
from codex_usage import aggregation
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data


def test_removed_active_duplicate_promotes_unchanged_archive_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = _write_handoff_corpus(tmp_path)
    _write_mixed_session(
        corpus.active_path,
        corpus.active_source,
        corpus.active_target,
        child_session_id="stale-canonical",
        initial_total=100,
        child_total=150,
        final_total=300,
    )
    _write_mixed_session(
        corpus.archived_path,
        corpus.archive_source,
        corpus.archive_target,
        child_session_id="surviving-fallback",
        initial_total=50,
        child_total=80,
        final_total=170,
    )
    unrelated_source = tmp_path / "unrelated-source"
    unrelated_target = tmp_path / "unrelated-target"
    _write_git_config(unrelated_source)
    _write_git_config(unrelated_target)
    _write_session(
        corpus.sessions / "2026" / "08" / "03" / "unrelated.jsonl",
        unrelated_source,
        unrelated_target,
        40,
        90,
        "unrelated",
    )
    load_cached_session_data(corpus.session_dirs, cache_dir=corpus.cache_dir, max_workers=1)
    corpus.active_path.unlink()

    def fail_parse(_path: Path):
        raise AssertionError("unchanged archived generation should be promoted from cache")

    monkeypatch.setattr(usage_module, "parse_session_generation", fail_parse)
    bounds = aggregation.resolve_range_bounds(
        "today", UTC, datetime(2026, 8, 3, 12, tzinfo=UTC)
    )
    ranged = load_cached_session_data(
        corpus.session_dirs,
        cache_dir=corpus.cache_dir,
        auto_transitions=False,
        max_workers=1,
        range_bounds=bounds,
    )
    unbounded = load_cached_session_data(
        corpus.session_dirs,
        cache_dir=corpus.cache_dir,
        auto_transitions=False,
        max_workers=1,
    )

    assert ranged.stats.files_parsed == 0
    assert unbounded.stats.files_parsed == 0
    assert ranged.records == unbounded.records
    assert {record.cwd for record in ranged.records} == {
        str(corpus.archive_source),
        str(unrelated_source),
    }
    assert [
        (record.session_id, record.usage.total_tokens)
        for record in unbounded.records
        if record.cwd == str(corpus.archive_source)
    ] == [("handoff", 50), ("surviving-fallback", 30), ("handoff", 90)]
    assert [
        record.usage.total_tokens
        for record in unbounded.records
        if record.session_id == "unrelated"
    ] == [40, 50]
    assert _dirty_task_ids(corpus.cache_dir) == {
        "handoff",
        "stale-canonical",
        "surviving-fallback",
    }
    with sqlite3.connect(corpus.cache_dir / CACHE_DB_NAME) as connection:
        archived_stat = corpus.archived_path.stat()
        assert connection.execute(
            """
            select file_key, path, session_dir, storage_state, size_bytes, mtime_ns,
                is_missing, session_id, error
            from files where file_key = 'handoff'
            """
        ).fetchall() == [
            (
                "handoff",
                str(corpus.archived_path),
                str(corpus.archive),
                "archived",
                archived_stat.st_size,
                archived_stat.st_mtime_ns,
                0,
                "handoff",
                "",
            )
        ]
        assert connection.execute(
            """
            select file_key, file_path, session_dir, storage_state, is_missing, session_id
            from session_metadata where file_key = 'handoff'
            """
        ).fetchall() == [
            (
                "handoff",
                str(corpus.archived_path),
                str(corpus.archive),
                "archived",
                0,
                "handoff",
            )
        ]
        assert connection.execute(
            "select distinct file_key, raw_path from transition_candidates where file_key = 'handoff'"
        ).fetchall() == [("handoff", str(corpus.archive_target))]
        assert connection.execute(
            """
            select record_index, session_id, total_tokens
            from usage_records where file_key = 'handoff'
            order by record_index
            """
        ).fetchall() == [
            (0, "handoff", 50),
            (1, "surviving-fallback", 30),
            (2, "handoff", 90),
        ]
        assert connection.execute(
            "select file_key, thread_id, raw_path from transition_candidates where file_key = 'handoff'"
        ).fetchall() == [
            ("handoff", "surviving-fallback", str(corpus.archive_target))
        ]

    rebuilt = load_cached_session_data(
        corpus.session_dirs, cache_dir=corpus.cache_dir, max_workers=1
    )

    assert _transition_targets(rebuilt) == {
        "surviving-fallback": _repo_key(corpus.archive_target),
        "unrelated": _repo_key(unrelated_target),
    }
    assert _dirty_task_ids(corpus.cache_dir) == set()


def test_changed_active_parse_failure_keeps_previous_active_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = _write_handoff_corpus(tmp_path)
    unrelated_source = tmp_path / "unrelated-source"
    unrelated_target = tmp_path / "unrelated-target"
    _write_git_config(unrelated_source)
    _write_git_config(unrelated_target)
    unrelated_path = corpus.sessions / "2026" / "08" / "03" / "unrelated.jsonl"
    _write_session(unrelated_path, unrelated_source, unrelated_target, 40, 90, "unrelated")
    initial = load_cached_session_data(
        corpus.session_dirs, cache_dir=corpus.cache_dir, max_workers=1
    )
    assert _transition_targets(initial) == {
        "handoff": _repo_key(corpus.active_target),
        "unrelated": _repo_key(unrelated_target),
    }
    with sqlite3.connect(corpus.cache_dir / CACHE_DB_NAME) as connection:
        previous_fingerprint = connection.execute(
            """
            select path, session_dir, storage_state, size_bytes, mtime_ns, session_id
            from files where file_key = ?
            """,
            ("handoff",),
        ).fetchone()
        previous_metadata = connection.execute(
            "select * from session_metadata where file_key = ?", ("handoff",)
        ).fetchone()
    _append_ignored_event(corpus.active_path)

    def fail_active_parse(path: Path, *_args: object, **_kwargs: object):
        if path == corpus.active_path:
            raise OSError("active parse failure")
        raise AssertionError("unchanged archive should not be reparsed")

    monkeypatch.setattr(usage_module, "parse_session_append", fail_active_parse)
    failed = load_cached_session_data(
        corpus.session_dirs,
        cache_dir=corpus.cache_dir,
        auto_transitions=False,
        max_workers=1,
    )

    assert failed.stats.files_parsed == 1
    assert failed.file_errors == {str(corpus.active_path): "OSError: active parse failure"}
    handoff_records = [record for record in failed.records if record.session_id == "handoff"]
    assert {record.cwd for record in handoff_records} == {str(corpus.active_source)}
    assert [record.usage.total_tokens for record in handoff_records] == [100, 200]
    assert _dirty_task_ids(corpus.cache_dir) == set()
    with sqlite3.connect(corpus.cache_dir / CACHE_DB_NAME) as connection:
        assert connection.execute(
            """
            select path, session_dir, storage_state, size_bytes, mtime_ns, session_id
            from files where file_key = ?
            """,
            ("handoff",),
        ).fetchone() == previous_fingerprint
        assert connection.execute(
            "select * from session_metadata where file_key = ?", ("handoff",)
        ).fetchone() == previous_metadata
        assert connection.execute(
            "select distinct file_key, raw_path from transition_candidates where file_key = ?",
            ("handoff",),
        ).fetchall() == [("handoff", str(corpus.active_target))]

    restored = load_cached_session_data(
        corpus.session_dirs, cache_dir=corpus.cache_dir, max_workers=1
    )

    assert _transition_targets(restored) == {
        "handoff": _repo_key(corpus.active_target),
        "unrelated": _repo_key(unrelated_target),
    }


def test_changed_active_reparse_keeps_active_generation_canonical(tmp_path: Path) -> None:
    corpus = _write_handoff_corpus(tmp_path)
    load_cached_session_data(corpus.session_dirs, cache_dir=corpus.cache_dir, max_workers=1)
    _append_token_count(corpus.active_path, 450)

    refreshed = load_cached_session_data(
        corpus.session_dirs,
        cache_dir=corpus.cache_dir,
        auto_transitions=False,
        max_workers=1,
    )

    assert refreshed.stats.files_parsed == 1
    assert refreshed.file_errors == {}
    assert {record.cwd for record in refreshed.records} == {str(corpus.active_source)}
    assert [record.usage.total_tokens for record in refreshed.records] == [100, 200, 150]
    with sqlite3.connect(corpus.cache_dir / CACHE_DB_NAME) as connection:
        assert connection.execute(
            "select path, storage_state from files where file_key = ?",
            ("handoff",),
        ).fetchone() == (str(corpus.active_path), "active")
        assert connection.execute(
            "select distinct file_key, raw_path from transition_candidates where file_key = ?",
            ("handoff",),
        ).fetchall() == [("handoff", str(corpus.active_target))]


def test_archive_promotion_rolls_back_when_rekey_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = _write_handoff_corpus(tmp_path)
    load_cached_session_data(
        corpus.session_dirs,
        cache_dir=corpus.cache_dir,
        auto_transitions=False,
        max_workers=1,
    )
    corpus.active_path.unlink()
    before = _ownership_snapshot(corpus.cache_dir)
    after_rekey: dict[str, tuple[tuple[object, ...], ...]] | None = None
    real_rekey = ownership_module.rekey_file_generation

    def rekey_then_fail(
        connection: sqlite3.Connection,
        *args: object,
        **kwargs: object,
    ) -> set[str]:
        nonlocal after_rekey
        real_rekey(connection, *args, **kwargs)
        after_rekey = _ownership_snapshot_for_connection(connection)
        raise sqlite3.OperationalError("promotion interrupted")

    monkeypatch.setattr(ownership_module, "rekey_file_generation", rekey_then_fail)
    with pytest.raises(sqlite3.OperationalError, match="promotion interrupted"):
        load_cached_session_data(
            corpus.session_dirs,
            cache_dir=corpus.cache_dir,
            auto_transitions=False,
            max_workers=1,
        )

    assert after_rekey is not None
    for table in ("fingerprints", "usage", "metadata", "candidates"):
        assert after_rekey[table] != before[table]
    assert _ownership_snapshot(corpus.cache_dir) == before
