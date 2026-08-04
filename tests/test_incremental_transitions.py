from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

import codex_usage.project_transition_state as state_module
import codex_usage.project_transitions as transitions_module
import project_transition_serial_oracle as serial_oracle
from codex_usage.project_transitions import (
    apply_project_transitions,
    infer_project_transitions,
)
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data
from codex_usage.session_cache_queries import query_rows_in_chunks


@dataclass(frozen=True)
class TransitionCorpus:
    sessions: Path
    archive: Path
    cache: Path
    paths: tuple[Path, ...]
    source_repos: tuple[Path, ...]
    target_repos: tuple[Path, ...]


def test_one_changed_task_never_scans_unchanged_jsonl_for_transitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = write_multi_task_transition_corpus(tmp_path, count=6)
    load_cached_session_data([corpus.sessions], cache_dir=corpus.cache, max_workers=1)
    append_ignored_event(corpus.paths[2])

    opened: list[Path] = []
    monkeypatch.setattr(Path, "open", recording_open(Path.open, opened))
    refreshed = load_cached_session_data(
        [corpus.sessions], cache_dir=corpus.cache, max_workers=1
    )

    assert refreshed.stats.files_parsed == 1
    assert opened.count(corpus.paths[2]) == 1
    assert not set(corpus.paths[:2] + corpus.paths[3:]).intersection(opened)
    assert refreshed.transition_run.worker_spans == ()


def test_disabled_transition_refresh_retains_dirty_tasks_until_enabled(
    tmp_path: Path,
) -> None:
    corpus = write_multi_task_transition_corpus(tmp_path, count=2)

    disabled = load_cached_session_data(
        [corpus.sessions],
        cache_dir=corpus.cache,
        auto_transitions=False,
        max_workers=1,
    )

    assert disabled.project_transitions == []
    assert dirty_task_ids(corpus.cache) == {"thread-0", "thread-1"}

    enabled = load_cached_session_data(
        [corpus.sessions], cache_dir=corpus.cache, max_workers=1
    )

    assert {transition.thread_ids for transition in enabled.project_transitions} == {
        ("thread-0",),
        ("thread-1",),
    }
    assert dirty_task_ids(corpus.cache) == set()


def test_removed_candidate_replaces_only_its_task_transition(tmp_path: Path) -> None:
    corpus = write_multi_task_transition_corpus(tmp_path, count=2)
    established = load_cached_session_data(
        [corpus.sessions], cache_dir=corpus.cache, max_workers=1
    )
    assert len(established.project_transitions) == 2

    write_task_session(
        corpus.paths[0],
        thread_id="thread-0",
        source_repo=corpus.source_repos[0],
        target_repo=None,
    )
    refreshed = load_cached_session_data(
        [corpus.sessions], cache_dir=corpus.cache, max_workers=1
    )

    assert [transition.thread_ids for transition in refreshed.project_transitions] == [
        ("thread-1",)
    ]
    assert transition_owners(corpus.cache) == [("thread-1", '["thread-1"]')]


def test_changed_state_observation_is_loaded_once_for_the_affected_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = write_multi_task_transition_corpus(
        tmp_path, count=1, include_jsonl_candidates=False
    )
    write_state_observation(corpus.sessions.parent, "thread-0", corpus.target_repos[0])
    session_dirs = [corpus.sessions, corpus.archive]
    established = load_cached_session_data(
        session_dirs, cache_dir=corpus.cache, max_workers=1
    )
    assert [
        transition.target_key for transition in established.project_transitions
    ] == [repo_key(corpus.target_repos[0])]

    replacement = tmp_path / "replacement-target"
    write_git_config(replacement, "https://github.com/example/replacement-target.git")
    write_state_observation(corpus.sessions.parent, "thread-0", replacement)
    append_ignored_event(corpus.paths[0])

    reads = 0
    original_read_rows = state_module._read_thread_rows

    def count_state_read(connection: sqlite3.Connection) -> list[sqlite3.Row]:
        nonlocal reads
        reads += 1
        return original_read_rows(connection)

    monkeypatch.setattr(state_module, "_read_thread_rows", count_state_read)
    refreshed = load_cached_session_data(
        session_dirs, cache_dir=corpus.cache, max_workers=1
    )

    assert reads == 1
    assert [transition.target_key for transition in refreshed.project_transitions] == [
        "https://github.com/example/replacement-target"
    ]


def test_failed_incremental_transition_replacement_retains_dirty_task_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = write_multi_task_transition_corpus(tmp_path, count=2)
    load_cached_session_data(
        [corpus.sessions],
        cache_dir=corpus.cache,
        auto_transitions=False,
        max_workers=1,
    )

    def fail_inference(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("transition inference interrupted")

    monkeypatch.setattr(transitions_module, "infer_project_transitions", fail_inference)
    with pytest.raises(RuntimeError, match="transition inference interrupted"):
        load_cached_session_data(
            [corpus.sessions], cache_dir=corpus.cache, max_workers=1
        )

    assert dirty_task_ids(corpus.cache) == {"thread-0", "thread-1"}


def test_cold_cached_transition_output_equals_frozen_serial_oracle(
    tmp_path: Path,
) -> None:
    corpus = write_multi_task_transition_corpus(tmp_path, count=3)
    expected_observations = serial_oracle.collect_repo_path_observations(
        [corpus.sessions], list(corpus.paths)
    )
    raw = load_cached_session_data(
        [corpus.sessions],
        cache_dir=corpus.cache,
        auto_transitions=False,
        max_workers=1,
    )
    expected_transitions = infer_project_transitions(raw.records, expected_observations)

    cached = load_cached_session_data(
        [corpus.sessions], cache_dir=corpus.cache, max_workers=1
    )

    assert cached.project_transitions == expected_transitions
    assert cached.records == apply_project_transitions(
        raw.records, expected_transitions
    )


def test_dirty_task_replacement_removes_legacy_global_transition_rows(
    tmp_path: Path,
) -> None:
    corpus = write_multi_task_transition_corpus(tmp_path, count=1)
    load_cached_session_data([corpus.sessions], cache_dir=corpus.cache, max_workers=1)

    with sqlite3.connect(corpus.cache / CACHE_DB_NAME) as connection:
        connection.execute("update project_transitions set owner_thread_id = ''")
        connection.execute(
            "insert into dirty_transition_tasks (thread_id) values ('thread-0')"
        )

    refreshed = load_cached_session_data(
        [corpus.sessions], cache_dir=corpus.cache, max_workers=1
    )

    assert len(refreshed.project_transitions) == 1
    assert transition_owners(corpus.cache) == [("thread-0", '["thread-0"]')]


def test_task_id_queries_split_sqlite_in_lists_at_five_hundred_ids() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "create table usage_records (file_key text, record_index integer, session_id text)"
    )
    connection.executemany(
        "insert into usage_records values (?, ?, ?)",
        [(f"file-{index:03d}", 0, f"thread-{index:03d}") for index in range(501)],
    )
    statements: list[str] = []
    connection.set_trace_callback(statements.append)

    rows = query_rows_in_chunks(
        connection,
        "session_id",
        {f"thread-{index:03d}" for index in range(501)},
    )

    task_selects = [
        statement
        for statement in statements
        if statement.startswith("select * from usage_records where session_id in")
    ]
    assert len(rows) == 501
    assert len(task_selects) == 2
    assert all(
        len(statement.split("(", 1)[1].rsplit(")", 1)[0].split(",")) <= 500
        for statement in task_selects
    )


def write_multi_task_transition_corpus(
    tmp_path: Path,
    *,
    count: int,
    include_jsonl_candidates: bool = True,
) -> TransitionCorpus:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archive = codex_home / "archived_sessions"
    day = sessions / "2026" / "08" / "03"
    day.mkdir(parents=True)
    archive.mkdir(parents=True)
    paths: list[Path] = []
    source_repos: list[Path] = []
    target_repos: list[Path] = []
    for index in range(count):
        source_repo = tmp_path / f"source-{index}"
        target_repo = tmp_path / f"target-{index}"
        write_git_config(source_repo, f"https://github.com/example/source-{index}.git")
        write_git_config(target_repo, f"https://github.com/example/target-{index}.git")
        path = day / f"thread-{index}.jsonl"
        write_task_session(
            path,
            thread_id=f"thread-{index}",
            source_repo=source_repo,
            target_repo=target_repo if include_jsonl_candidates else None,
        )
        paths.append(path)
        source_repos.append(source_repo)
        target_repos.append(target_repo)
    return TransitionCorpus(
        sessions=sessions,
        archive=archive,
        cache=tmp_path / "cache",
        paths=tuple(paths),
        source_repos=tuple(source_repos),
        target_repos=tuple(target_repos),
    )


def write_task_session(
    path: Path,
    *,
    thread_id: str,
    source_repo: Path,
    target_repo: Path | None,
) -> None:
    events: list[dict[str, object]] = [
        {
            "timestamp": "2026-08-03T12:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": thread_id,
                "cwd": str(source_repo),
                "git": {"repository_url": f"{repo_key(source_repo)}.git"},
            },
        },
        turn_context_event("2026-08-03T12:00:01Z", "turn-1"),
        token_count_event("2026-08-03T12:00:02Z", 100),
    ]
    if target_repo is not None:
        events.append(function_call_event("2026-08-03T12:05:00Z", target_repo))
    events.extend(
        [
            turn_context_event("2026-08-03T12:10:01Z", "turn-2"),
            token_count_event("2026-08-03T12:10:02Z", 300),
        ]
    )
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")


def write_state_observation(codex_home: Path, thread_id: str, repo: Path) -> None:
    state_path = codex_home / "state_5.sqlite"
    with sqlite3.connect(state_path) as connection:
        connection.execute(
            "create table if not exists threads (id text primary key, cwd text, updated_at integer)"
        )
        connection.execute(
            "insert or replace into threads (id, cwd, updated_at) values (?, ?, ?)",
            (
                thread_id,
                str(repo),
                int(datetime(2026, 8, 3, 12, 5, tzinfo=UTC).timestamp()),
            ),
        )


def append_ignored_event(path: Path) -> None:
    event = {
        "timestamp": "2026-08-03T12:15:00Z",
        "type": "event_msg",
        "payload": {"type": "ignored"},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n{json.dumps(event)}")


def recording_open(original_open, opened: list[Path]):
    def open_path(path: Path, *args: object, **kwargs: object):
        opened.append(path)
        return original_open(path, *args, **kwargs)

    return open_path


def dirty_task_ids(cache_dir: Path) -> set[str]:
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        return {
            str(row[0])
            for row in connection.execute(
                "select thread_id from dirty_transition_tasks order by thread_id"
            )
        }


def transition_owners(cache_dir: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        return [
            (str(owner), str(thread_ids))
            for owner, thread_ids in connection.execute(
                "select owner_thread_id, thread_ids_json from project_transitions order by owner_thread_id"
            )
        ]


def repo_key(repo: Path) -> str:
    return f"https://github.com/example/{repo.name}"


def write_git_config(repo: Path, url: str) -> None:
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = {url}\n', encoding="utf-8"
    )


def turn_context_event(timestamp: str, turn_id: str) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "turn_context",
        "payload": {"turn_id": turn_id, "model": "gpt-5.5"},
    }


def token_count_event(timestamp: str, total: int) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "total_tokens": total,
                }
            },
        },
    }


def function_call_event(timestamp: str, repo: Path) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "arguments": json.dumps({"workdir": str(repo), "command": "pwd"}),
        },
    }
