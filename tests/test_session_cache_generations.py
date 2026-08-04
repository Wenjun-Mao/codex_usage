from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

import codex_usage.session_cache_generations as generations
from codex_usage.parser import parse_session_generation
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data
from codex_usage.session_cache_schema import _ensure_schema
from codex_usage.session_inventory import collect_session_file_inventory


@dataclass(frozen=True, slots=True)
class GenerationCorpus:
    sessions: Path
    cache: Path
    changed_file: Path
    thread_id: str


def test_changed_file_replaces_usage_metadata_and_candidates_atomically(
    tmp_path: Path,
) -> None:
    corpus = write_generation_corpus(tmp_path)
    load_cached_session_data(
        [corpus.sessions], cache_dir=corpus.cache, auto_transitions=False
    )
    append_usage_and_new_workdir(corpus.changed_file)

    second = load_cached_session_data(
        [corpus.sessions], cache_dir=corpus.cache, auto_transitions=False
    )

    assert second.stats.files_parsed == 1
    with sqlite3.connect(corpus.cache / CACHE_DB_NAME) as connection:
        assert connection.execute(
            "select count(*) from transition_candidates"
        ).fetchone() == (2,)
        assert connection.execute(
            "select count(*) from usage_records where file_key = ?",
            (corpus.thread_id,),
        ).fetchone() == (2,)
        assert connection.execute(
            "select session_id, cwd, memory_mode, has_base_instructions "
            "from session_metadata where file_key = ?",
            (corpus.thread_id,),
        ).fetchone() == (corpus.thread_id, "/repo/first", "persistent", 1)
        assert connection.execute(
            "select thread_id from dirty_transition_tasks"
        ).fetchall() == [(corpus.thread_id,)]


def test_candidate_insert_failure_rolls_back_complete_generation_and_dirty_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = write_generation_corpus(tmp_path)
    load_cached_session_data(
        [corpus.sessions], cache_dir=corpus.cache, auto_transitions=False
    )
    before = generation_snapshot(corpus.cache)
    append_usage_and_new_workdir(corpus.changed_file)

    def fail_candidate_insert(*_args: object, **_kwargs: object) -> None:
        raise sqlite3.IntegrityError("injected candidate insert failure")

    monkeypatch.setattr(
        generations, "insert_transition_candidates", fail_candidate_insert
    )
    with pytest.raises(
        sqlite3.IntegrityError, match="injected candidate insert failure"
    ):
        load_cached_session_data(
            [corpus.sessions], cache_dir=corpus.cache, auto_transitions=False
        )

    assert generation_snapshot(corpus.cache) == before


def test_generation_persistence_uses_worker_metadata_without_reopening_jsonl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = write_generation_corpus(tmp_path)
    (entry,) = collect_session_file_inventory([corpus.sessions])
    generation = parse_session_generation(corpus.changed_file)
    original_open = Path.open

    def reject_session_reopen(self: Path, *args: object, **kwargs: object):
        if self == corpus.changed_file:
            raise AssertionError("parent reopened JSONL while storing generation")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_session_reopen)
    corpus.cache.mkdir()
    with sqlite3.connect(corpus.cache / CACHE_DB_NAME) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_schema(connection)
        generations.replace_file_generation(
            connection, [corpus.sessions], entry, generation
        )
        connection.commit()

    with sqlite3.connect(corpus.cache / CACHE_DB_NAME) as connection:
        assert connection.execute(
            "select session_id, cwd, memory_mode, has_base_instructions "
            "from session_metadata"
        ).fetchone() == (corpus.thread_id, "/repo/first", "persistent", 1)


def write_generation_corpus(root: Path) -> GenerationCorpus:
    sessions = root / "sessions"
    changed_file = sessions / "2026" / "08" / "03" / "atomic.jsonl"
    changed_file.parent.mkdir(parents=True)
    thread_id = "atomic-thread"
    changed_file.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                session_metadata(thread_id),
                function_call("2026-08-03T10:00:01Z", "/repo/first"),
                turn_context(),
                token_count("2026-08-03T10:00:02Z", 100),
            )
        ),
        encoding="utf-8",
    )
    return GenerationCorpus(
        sessions=sessions,
        cache=root / "cache",
        changed_file=changed_file,
        thread_id=thread_id,
    )


def append_usage_and_new_workdir(path: Path) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in (
            function_call("2026-08-03T10:00:03Z", "/repo/second"),
            token_count("2026-08-03T10:00:04Z", 160),
        ):
            handle.write("\n" + json.dumps(row))


def generation_snapshot(cache_dir: Path) -> dict[str, tuple[tuple[object, ...], ...]]:
    queries = {
        "usage": "select * from usage_records order by file_key, record_index",
        "metadata": "select * from session_metadata order by file_key",
        "candidates": "select * from transition_candidates order by file_key, candidate_index",
        "fingerprints": "select * from files order by file_key",
        "dirty_tasks": "select * from dirty_transition_tasks order by thread_id",
    }
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        return {
            name: tuple(connection.execute(query))
            for name, query in queries.items()
        }


def session_metadata(thread_id: str) -> dict[str, object]:
    return {
        "timestamp": "2026-08-03T10:00:00Z",
        "type": "session_meta",
        "payload": {
            "id": thread_id,
            "cwd": "/repo/first",
            "memory_mode": "persistent",
            "base_instructions": "configured",
        },
    }


def function_call(timestamp: str, workdir: str) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "arguments": json.dumps({"workdir": workdir}),
        },
    }


def turn_context() -> dict[str, object]:
    return {
        "timestamp": "2026-08-03T10:00:01Z",
        "type": "turn_context",
        "payload": {"model": "gpt-5.6"},
    }


def token_count(timestamp: str, total_tokens: int) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total_tokens,
                    "cached_input_tokens": 0,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "total_tokens": total_tokens,
                }
            },
        },
    }
