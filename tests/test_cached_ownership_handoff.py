from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

import codex_usage.parallel.usage as usage_module
import codex_usage.session_cache_ownership as ownership_module
from codex_usage import aggregation
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data


def test_removed_active_duplicate_promotes_unchanged_archive_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = _write_handoff_corpus(tmp_path)
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
    assert {record.cwd for record in ranged.records} == {str(corpus.archive_source)}
    assert {record.cwd for record in unbounded.records} == {str(corpus.archive_source)}
    assert [record.usage.total_tokens for record in unbounded.records] == [50, 120]
    assert _dirty_task_ids(corpus.cache_dir) == {"handoff"}
    with sqlite3.connect(corpus.cache_dir / CACHE_DB_NAME) as connection:
        archived_stat = corpus.archived_path.stat()
        assert connection.execute(
            """
            select file_key, path, session_dir, storage_state, size_bytes, mtime_ns,
                is_missing, session_id, error
            from files
            order by file_key
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
            from session_metadata
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
            "select distinct file_key, raw_path from transition_candidates"
        ).fetchall() == [("handoff", str(corpus.archive_target))]

    rebuilt = load_cached_session_data(
        corpus.session_dirs, cache_dir=corpus.cache_dir, max_workers=1
    )

    assert [transition.target_key for transition in rebuilt.project_transitions] == [
        _repo_key(corpus.archive_target)
    ]
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

    def fail_active_parse(path: Path):
        if path == corpus.active_path:
            raise OSError("active parse failure")
        raise AssertionError("unchanged archive should not be reparsed")

    monkeypatch.setattr(usage_module, "parse_session_generation", fail_active_parse)
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

    def fail_rekey(*_args: object, **_kwargs: object) -> set[str]:
        raise sqlite3.OperationalError("promotion interrupted")

    monkeypatch.setattr(ownership_module, "rekey_file_generation", fail_rekey)
    with pytest.raises(sqlite3.OperationalError, match="promotion interrupted"):
        load_cached_session_data(
            corpus.session_dirs,
            cache_dir=corpus.cache_dir,
            auto_transitions=False,
            max_workers=1,
        )

    assert _ownership_snapshot(corpus.cache_dir) == before


@dataclass(frozen=True)
class _HandoffCorpus:
    session_dirs: list[Path]
    cache_dir: Path
    sessions: Path
    archive: Path
    active_path: Path
    archived_path: Path
    active_source: Path
    active_target: Path
    archive_source: Path
    archive_target: Path


def _write_handoff_corpus(root: Path) -> _HandoffCorpus:
    codex_home = root / "codex"
    sessions = codex_home / "sessions"
    archive = codex_home / "archived_sessions"
    active_path = sessions / "2026" / "08" / "03" / "handoff.jsonl"
    archived_path = archive / "2026" / "08" / "03" / "handoff.jsonl"
    active_source = root / "active-source"
    active_target = root / "active-target"
    archive_source = root / "archive-source"
    archive_target = root / "archive-target"
    for repo in (active_source, active_target, archive_source, archive_target):
        _write_git_config(repo)
    active_path.parent.mkdir(parents=True)
    archived_path.parent.mkdir(parents=True)
    _write_session(active_path, active_source, active_target, 100, 300)
    _write_session(archived_path, archive_source, archive_target, 50, 170)
    return _HandoffCorpus(
        session_dirs=[sessions, archive],
        cache_dir=root / "cache",
        sessions=sessions,
        archive=archive,
        active_path=active_path,
        archived_path=archived_path,
        active_source=active_source,
        active_target=active_target,
        archive_source=archive_source,
        archive_target=archive_target,
    )


def _write_session(
    path: Path,
    source_repo: Path,
    target_repo: Path,
    initial_total: int,
    final_total: int,
    session_id: str = "handoff",
) -> None:
    rows = (
        _session_meta(source_repo, session_id),
        _turn_context("2026-08-03T12:00:01Z", "turn-1"),
        _token_count("2026-08-03T12:00:02Z", initial_total),
        _function_call("2026-08-03T12:05:00Z", target_repo),
        _turn_context("2026-08-03T12:10:01Z", "turn-2"),
        _token_count("2026-08-03T12:10:02Z", final_total),
    )
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def _session_meta(source_repo: Path, session_id: str) -> dict[str, object]:
    return {
        "timestamp": "2026-08-03T12:00:00Z",
        "type": "session_meta",
        "payload": {
            "id": session_id,
            "cwd": str(source_repo),
            "git": {"repository_url": f"{_repo_key(source_repo)}.git"},
        },
    }


def _turn_context(timestamp: str, turn_id: str) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "turn_context",
        "payload": {"turn_id": turn_id, "model": "gpt-5.5"},
    }


def _token_count(timestamp: str, total_tokens: int) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total_tokens,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "total_tokens": total_tokens,
                }
            },
        },
    }


def _function_call(timestamp: str, repo: Path) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "arguments": json.dumps({"workdir": str(repo), "command": "pwd"}),
        },
    }


def _append_ignored_event(path: Path) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps({"type": "event_msg", "payload": {"type": "ignored"}}))


def _append_token_count(path: Path, total_tokens: int) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps(_token_count("2026-08-03T12:15:00Z", total_tokens)))


def _write_git_config(repo: Path) -> None:
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = {_repo_key(repo)}.git\n', encoding="utf-8"
    )


def _repo_key(repo: Path) -> str:
    return f"https://github.com/example/{repo.name}"


def _dirty_task_ids(cache_dir: Path) -> set[str]:
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        return {
            str(row[0])
            for row in connection.execute(
                "select thread_id from dirty_transition_tasks order by thread_id"
            )
        }


def _transition_targets(data) -> dict[str, str]:
    return {
        transition.thread_ids[0]: transition.target_key
        for transition in data.project_transitions
    }


def _ownership_snapshot(cache_dir: Path) -> dict[str, list[tuple[object, ...]]]:
    queries = {
        "files": "select * from files order by file_key",
        "usage": "select * from usage_records order by file_key, record_index",
        "metadata": "select * from session_metadata order by file_key",
        "candidates": "select * from transition_candidates order by file_key, candidate_index",
        "dirty": "select * from dirty_transition_tasks order by thread_id",
    }
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        return {
            name: list(connection.execute(query)) for name, query in queries.items()
        }
