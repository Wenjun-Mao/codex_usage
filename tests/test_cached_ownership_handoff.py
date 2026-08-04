from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

import codex_usage.parallel.usage as usage_module
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
    assert {record.cwd for record in ranged.records} == {str(corpus.archive_source)}
    assert {record.cwd for record in unbounded.records} == {str(corpus.archive_source)}
    assert [record.usage.total_tokens for record in unbounded.records] == [50, 120]
    assert _dirty_task_ids(corpus.cache_dir) == {"handoff"}
    with sqlite3.connect(corpus.cache_dir / CACHE_DB_NAME) as connection:
        assert connection.execute(
            "select file_key, path, is_missing from files order by file_key"
        ).fetchall() == [("handoff", str(corpus.archived_path), 0)]
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


@dataclass(frozen=True)
class _HandoffCorpus:
    session_dirs: list[Path]
    cache_dir: Path
    active_path: Path
    archived_path: Path
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
        active_path=active_path,
        archived_path=archived_path,
        archive_source=archive_source,
        archive_target=archive_target,
    )


def _write_session(
    path: Path,
    source_repo: Path,
    target_repo: Path,
    initial_total: int,
    final_total: int,
) -> None:
    rows = (
        _session_meta(source_repo),
        _turn_context("2026-08-03T12:00:01Z", "turn-1"),
        _token_count("2026-08-03T12:00:02Z", initial_total),
        _function_call("2026-08-03T12:05:00Z", target_repo),
        _turn_context("2026-08-03T12:10:01Z", "turn-2"),
        _token_count("2026-08-03T12:10:02Z", final_total),
    )
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def _session_meta(source_repo: Path) -> dict[str, object]:
    return {
        "timestamp": "2026-08-03T12:00:00Z",
        "type": "session_meta",
        "payload": {
            "id": "handoff",
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
