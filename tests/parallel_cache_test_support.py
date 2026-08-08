from __future__ import annotations  # noqa: I001

import json
import os
import random
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import ClassVar, Self

from codex_usage.aggregation import (
    aggregate_records,
    resolve_timezone,
    summarize_records,
)
from codex_usage.parallel.execution import resolve_worker_count
from codex_usage.parallel.usage import UsageParseRequest, UsageParseResult
from codex_usage.report_breakdown import build_report_breakdown
from codex_usage.reporting import render_html_report
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data
from codex_usage.session_cache_models import CachedSessionData
from parallel_cache_schema_expectations import SchemaObject

type GenerationSnapshot = tuple[tuple[object, ...], ...]
_FIXED_TIMESTAMP = "2026-07-31T10:00:00Z"


@dataclass(frozen=True, slots=True)
class UsageCorpus:
    sessions: Path
    ordered_paths: tuple[Path, ...]
    corrupt_path: Path
    malformed_json_path: Path
    missing_path: Path
    recent_old_metadata_path: Path


def write_usage_corpus(root: Path) -> UsageCorpus:
    sessions = root / "sessions"
    day = sessions / "2026" / "07" / "31"
    day.mkdir(parents=True, exist_ok=True)
    paths = tuple(day / name for name in _CORPUS_NAMES)

    _write_jsonl(
        paths[0],
        [
            _session_meta("normal-thread", cwd="/repo/normal"),
            _turn_context(),
            _token_count("2026-07-31T10:00:01Z", 100),
        ],
    )
    _write_jsonl(
        paths[1],
        [
            _session_meta(
                "parent-thread",
                cwd="/repo/parent",
                repository_url="https://github.com/example/parent.git",
            ),
            _turn_context(),
            _token_count("2026-07-31T10:01:01Z", 120),
        ],
    )
    _write_jsonl(
        paths[2],
        [
            _session_meta(
                "subagent-thread",
                cwd="/repo/subagent",
                source={
                    "subagent": {
                        "thread_spawn": {
                            "parent_thread_id": "parent-thread",
                            "depth": 1,
                        }
                    }
                },
            ),
            _turn_context(),
            _token_count("2026-07-31T10:02:01Z", 75),
        ],
    )
    _write_jsonl(
        paths[3],
        [
            _session_meta(
                "fork-thread",
                cwd="/repo/fork",
                forked_from_id="parent-thread",
            ),
            _session_meta("parent-thread", cwd="/repo/parent"),
            _token_count("2026-07-31T10:03:00Z", 1_000),
            _token_count("2026-07-31T10:03:01Z", 1_200),
            _session_meta(
                "fork-thread",
                cwd="/repo/fork",
                forked_from_id="parent-thread",
            ),
            _turn_context(),
            _token_count("2026-07-31T10:03:02Z", 1_300),
            _token_count("2026-07-31T10:03:03Z", 1_450),
        ],
    )
    _write_unicode_escaped_session(paths[4])
    paths[5].write_text("", encoding="utf-8")
    _write_jsonl(
        paths[6],
        [
            _session_meta(
                "future-missing-thread",
                cwd="/repo/future",
                timestamp="2036-01-01T00:00:00Z",
            ),
            _token_count("2036-01-01T00:00:01Z", 90),
        ],
    )
    recent_timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_jsonl(
        paths[7],
        [
            _session_meta(
                "recent-old-metadata-thread",
                cwd="/repo/recent",
                timestamp="2020-01-01T00:00:00Z",
            ),
            _token_count(recent_timestamp, 130),
        ],
    )
    old_mtime = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    os.utime(paths[7], (old_mtime, old_mtime))
    paths[8].write_bytes(b"\xff\xfe")
    paths[9].write_text(
        json.dumps(_session_meta("malformed-thread", cwd="/repo/malformed"))
        + "\n{not-json}\n"
        + json.dumps(_token_count("2026-07-31T10:09:01Z", 211))
        + "\n",
        encoding="utf-8",
    )

    return UsageCorpus(
        sessions=sessions,
        ordered_paths=paths,
        corrupt_path=paths[8],
        malformed_json_path=paths[9],
        missing_path=paths[6],
        recent_old_metadata_path=paths[7],
    )


def load_serial(
    corpus: UsageCorpus,
    cache_dir: Path,
    *,
    auto_transitions: bool,
) -> CachedSessionData:
    return load_cached_session_data(
        [corpus.sessions],
        cache_dir=cache_dir,
        auto_transitions=auto_transitions,
        max_workers=1,
    )


def load_parallel(
    corpus: UsageCorpus,
    cache_dir: Path,
    *,
    auto_transitions: bool,
) -> CachedSessionData:
    return load_cached_session_data(
        [corpus.sessions],
        cache_dir=cache_dir,
        auto_transitions=auto_transitions,
        max_workers=4,
    )


def write_valid_usage_set(root: Path, *, count: int) -> tuple[Path, tuple[Path, ...]]:
    if count < 1:
        raise ValueError("count must be at least one")
    sessions = root / "sessions"
    day = sessions / "2026" / "07" / "31"
    day.mkdir(parents=True, exist_ok=True)
    paths = tuple(day / f"{index:03d}.jsonl" for index in range(count))
    for index, path in enumerate(paths):
        _write_jsonl(
            path,
            [
                _session_meta(path.stem, cwd=f"/repo/{index:03d}"),
                _token_count("2026-07-31T12:00:00Z", 100 + index),
            ],
        )
    return sessions, paths


def append_cumulative_token_total(
    path: Path,
    *,
    total_tokens: int,
    timestamp: str,
) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_token_count(timestamp, total_tokens)) + "\n")


def complete_generation_snapshot(cache_dir: Path) -> GenerationSnapshot:
    database = (cache_dir / CACHE_DB_NAME).resolve()
    with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as connection:
        files = tuple(
            connection.execute(
                "select file_key, path, session_dir, storage_state, size_bytes, mtime_ns, "
                "parsed_at, missing_since, is_missing, session_id, error "
                "from files order by file_key"
            )
        )
        usage_records = tuple(
            connection.execute(
                "select * from usage_records order by file_key, record_index"
            )
        )
        session_metadata = tuple(
            connection.execute("select * from session_metadata order by file_key")
        )
        checkpoints = tuple(
            connection.execute("select * from parser_checkpoints order by file_key")
        )
        content_diagnostics = tuple(
            connection.execute(
                "select * from storage_content_diagnostics order by path"
            )
        )
    return files + usage_records + session_metadata + checkpoints + content_diagnostics


def normalized_sqlite_master(
    connection: sqlite3.Connection,
) -> tuple[SchemaObject, ...]:
    rows = connection.execute(
        "select type, name, tbl_name, coalesce(sql, '') from sqlite_master "
        "order by type, name, tbl_name"
    ).fetchall()
    return tuple(
        (str(object_type), str(name), str(table_name), " ".join(str(sql).split()))
        for object_type, name, table_name, sql in rows
    )


def complete_schema_metadata(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(key), str(value))
        for key, value in connection.execute(
            "select key, value from schema_meta order by key"
        )
    )


def attach_transition_evidence(corpus: UsageCorpus) -> None:
    target_repo = corpus.sessions.parent / "moved-project"
    git_dir = target_repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        '[remote "origin"]\n    url = https://github.com/example/moved-project.git\n',
        encoding="utf-8",
    )
    function_call = {
        "timestamp": "2026-07-31T10:05:00Z",
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "arguments": json.dumps({"workdir": str(target_repo)}),
        },
    }
    with corpus.ordered_paths[0].open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(function_call) + "\n")

    state_path = corpus.sessions.parent / "state_5.sqlite"
    with sqlite3.connect(state_path) as connection:
        connection.execute(
            "create table threads (id text primary key, cwd text, updated_at integer)"
        )
        connection.execute(
            "insert into threads (id, cwd, updated_at) values (?, ?, ?)",
            (
                "normal-thread",
                str(target_repo),
                int(datetime(2026, 7, 31, 10, 6, tzinfo=UTC).timestamp()),
            ),
        )


def render_report_text(
    data: CachedSessionData,
    generated_at: datetime,
    path: Path,
) -> str:
    timezone = resolve_timezone("UTC")
    total = summarize_records(data.records)
    rendered = render_html_report(
        output_path=path,
        generated_at=generated_at,
        range_name="all",
        total=total,
        daily_rows=aggregate_records(data.records, "day", timezone),
        hourly_rows=aggregate_records(data.records, "hour", timezone),
        breakdown=build_report_breakdown(data.records),
        sessions_dirs=data.session_dirs,
        files_scanned=len(data.files),
        storage_roots=[str(item) for item in data.session_dirs],
        files_archived=data.stats.files_archived,
        files_retained_missing=data.stats.files_missing_retained,
        project_keys=[],
        project_transitions=[item.to_dict() for item in data.project_transitions],
    )
    text = rendered.read_text(encoding="utf-8")
    return text.replace(str(path), "<OUTPUT_PATH>")


class SerialUsageTestMapper:
    def __init__(
        self,
        worker: Callable[[UsageParseRequest], UsageParseResult],
        *,
        task_count: int,
        max_workers: int,
    ) -> None:
        self.worker = worker
        self.worker_count = resolve_worker_count(
            task_count, available_cpus=64, max_workers=max_workers
        )
        self.used_serial_fallback = False
        self.infrastructure_error = ""

    def map_batch(
        self,
        requests: Sequence[UsageParseRequest],
    ) -> list[UsageParseResult]:
        return [self.worker(request) for request in requests]

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class ShuffledUsageResultMapper(SerialUsageTestMapper):
    seed: ClassVar[int] = 0
    observed_orders: ClassVar[list[tuple[int, ...]]] = []

    def map_batch(
        self,
        requests: Sequence[UsageParseRequest],
    ) -> list[UsageParseResult]:
        results = super().map_batch(requests)
        random.Random(self.seed + len(self.observed_orders)).shuffle(results)
        self.observed_orders.append(tuple(result.request.ordinal for result in results))
        return results


class InterruptAfterFirstBatchMapper(SerialUsageTestMapper):
    calls = 0

    def map_batch(
        self,
        requests: Sequence[UsageParseRequest],
    ) -> list[UsageParseResult]:
        type(self).calls += 1
        if type(self).calls == 2:
            raise KeyboardInterrupt("after first committed batch")
        return super().map_batch(requests)


_CORPUS_NAMES = (
    "000-normal.jsonl",
    "001-parent.jsonl",
    "002-structured-subagent.jsonl",
    "003-fork-replay.jsonl",
    "004-unicode-escaped.jsonl",
    "005-empty-valid.jsonl",
    "006-future-missing.jsonl",
    "007-recent-old-metadata.jsonl",
    "008-invalid-utf8.jsonl",
    "009-malformed-json.jsonl",
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_unicode_escaped_session(path: Path) -> None:
    rows = [
        _session_meta("unicode-thread", cwd="/repo/unicode"),
        _turn_context(),
        _token_count("2026-07-31T10:04:01Z", 85),
    ]
    encoded = "".join(json.dumps(row) + "\n" for row in rows)
    encoded = encoded.replace("session_meta", r"session_\u006deta")
    encoded = encoded.replace("turn_context", r"turn_\u0063ontext")
    encoded = encoded.replace("event_msg", r"event_\u006dsg")
    encoded = encoded.replace("token_count", r"token_\u0063ount")
    path.write_text(encoded, encoding="utf-8")


def _session_meta(
    session_id: str,
    *,
    cwd: str,
    timestamp: str = _FIXED_TIMESTAMP,
    repository_url: str = "",
    source: object = "cli",
    forked_from_id: str = "",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": session_id,
        "timestamp": timestamp,
        "cwd": cwd,
        "source": source,
    }
    if repository_url:
        payload["git"] = {
            "repository_url": repository_url,
            "branch": "main",
        }
    if forked_from_id:
        payload["forked_from_id"] = forked_from_id
    return {"timestamp": timestamp, "type": "session_meta", "payload": payload}


def _turn_context() -> dict[str, object]:
    return {
        "timestamp": _FIXED_TIMESTAMP,
        "type": "turn_context",
        "payload": {
            "model": "gpt-5.5",
            "turn_id": "turn-1",
            "effort": "medium",
        },
    }


def _token_count(timestamp: str, total_tokens: int) -> dict[str, object]:
    usage = {
        "input_tokens": total_tokens,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": total_tokens,
    }
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {"total_token_usage": usage},
        },
    }
