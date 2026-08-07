from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from codex_usage.session_cache import CACHE_DB_NAME


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


def _write_mixed_session(
    path: Path,
    source_repo: Path,
    target_repo: Path,
    *,
    child_session_id: str,
    initial_total: int,
    child_total: int,
    final_total: int,
) -> None:
    rows = (
        _session_meta(source_repo, "handoff"),
        _turn_context("2026-08-03T12:00:01Z", "root-turn-1"),
        _token_count("2026-08-03T12:00:02Z", initial_total),
        _session_meta(
            source_repo,
            child_session_id,
            parent_thread_id="handoff",
        ),
        _turn_context("2026-08-03T12:05:00Z", "child-turn"),
        _token_count("2026-08-03T12:05:00Z", child_total),
        _function_call("2026-08-03T12:05:01Z", target_repo),
        _session_meta(source_repo, "handoff"),
        _turn_context("2026-08-03T12:10:01Z", "root-turn-2"),
        _token_count("2026-08-03T12:10:02Z", final_total),
    )
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def _session_meta(
    source_repo: Path,
    session_id: str,
    parent_thread_id: str = "",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": session_id,
        "cwd": str(source_repo),
        "git": {"repository_url": f"{_repo_key(source_repo)}.git"},
    }
    if parent_thread_id:
        payload["source"] = {
            "subagent": {"thread_spawn": {"parent_thread_id": parent_thread_id}}
        }
    return {
        "timestamp": "2026-08-03T12:00:00Z",
        "type": "session_meta",
        "payload": payload,
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


def _ownership_snapshot(
    cache_dir: Path,
) -> dict[str, tuple[tuple[object, ...], ...]]:
    queries = {
        "fingerprints": "select * from files order by file_key",
        "usage": "select * from usage_records order by file_key, record_index",
        "metadata": "select * from session_metadata order by file_key",
        "checkpoints": "select * from parser_checkpoints order by file_key",
        "candidates": "select * from transition_candidates order by file_key, candidate_index",
        "dirty": "select * from dirty_transition_tasks order by thread_id",
        "transitions": "select * from project_transitions order by owner_thread_id, source_key, target_key",
    }
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        return _ownership_snapshot_for_connection(connection, queries)


def _ownership_snapshot_for_connection(
    connection: sqlite3.Connection,
    queries: dict[str, str] | None = None,
) -> dict[str, tuple[tuple[object, ...], ...]]:
    if queries is None:
        queries = {
            "fingerprints": "select * from files order by file_key",
            "usage": "select * from usage_records order by file_key, record_index",
            "metadata": "select * from session_metadata order by file_key",
            "checkpoints": "select * from parser_checkpoints order by file_key",
            "candidates": "select * from transition_candidates order by file_key, candidate_index",
            "dirty": "select * from dirty_transition_tasks order by thread_id",
            "transitions": "select * from project_transitions order by owner_thread_id, source_key, target_key",
        }
    return {
        name: tuple(tuple(row) for row in connection.execute(query))
        for name, query in queries.items()
    }
