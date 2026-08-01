from __future__ import annotations

import json
import os
import pickle
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from parallel_cache_test_support import (
    InterruptAfterFirstBatchMapper,
    ShuffledUsageResultMapper,
    append_cumulative_token_total,
    complete_generation_snapshot,
    load_parallel,
    load_serial,
    write_usage_corpus,
    write_valid_usage_set,
)

import codex_usage.session_cache_refresh as refresh_module
from codex_usage.models import UsageRecord
from codex_usage.parallel.execution import OrderedProcessMapper
from codex_usage.parallel.usage import (
    UsageParseRequest,
    UsageParseResult,
    parse_usage_request,
)
from codex_usage.session_cache import (
    CACHE_DB_NAME,
    load_cached_session_data,
)
from codex_usage.session_inventory import (
    SessionFileInventoryEntry,
    collect_session_file_inventory,
)


@pytest.fixture(autouse=True)
def reset_usage_mapper_doubles() -> Iterator[None]:
    ShuffledUsageResultMapper.seed = 0
    ShuffledUsageResultMapper.observed_orders.clear()
    InterruptAfterFirstBatchMapper.calls = 0
    yield
    ShuffledUsageResultMapper.seed = 0
    ShuffledUsageResultMapper.observed_orders.clear()
    InterruptAfterFirstBatchMapper.calls = 0


def test_usage_request_and_result_are_pickle_safe(tmp_path: Path) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    path = corpus.ordered_paths[0]
    stat = path.stat()
    request = UsageParseRequest(0, path.stem, path, stat.st_size, stat.st_mtime_ns)
    assert pickle.loads(pickle.dumps(request)) == request
    result = parse_usage_request(request)
    assert result.error == ""
    assert result.records
    assert result.span.pid == os.getpid()
    assert pickle.loads(pickle.dumps(result)) == result


def test_usage_file_error_is_data_not_pool_fallback(tmp_path: Path) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    path = corpus.corrupt_path
    stat = path.stat()
    request = UsageParseRequest(0, path.stem, path, stat.st_size, stat.st_mtime_ns)
    with OrderedProcessMapper(
        parse_usage_request, task_count=1, max_workers=1
    ) as mapper:
        result = mapper.map_batch([request])[0]
    assert result.records == ()
    assert result.error.startswith("UnicodeDecodeError: ")
    assert result.span.pid == os.getpid()
    assert mapper.worker_count == 1
    assert mapper.used_serial_fallback is False
    assert mapper.infrastructure_error == ""


def test_parallel_corpus_uses_overlapping_child_workers_without_path_leakage(
    tmp_path: Path,
) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    data = load_parallel(
        corpus,
        tmp_path / "parallel-cache",
        auto_transitions=False,
    )

    report = data.usage_run
    assert report.resolved_worker_count >= 2
    assert len(report.worker_pids) >= 2
    assert os.getpid() not in report.worker_pids
    assert report.max_concurrency >= 2
    assert report.actually_parallel(os.getpid()) is True
    assert report.used_serial_fallback is False
    assert report.infrastructure_error == ""
    assert report.file_error_count == data.stats.file_errors == 1
    assert len(data.file_errors) == 1
    assert next(iter(data.file_errors.values())).startswith("UnicodeDecodeError: ")
    report_text = repr(report.to_dict())
    assert all(str(path) not in report_text for path in corpus.ordered_paths)


def test_varied_shuffled_completion_preserves_exact_semantic_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    expected = load_serial(
        corpus, tmp_path / "serial-cache", auto_transitions=False
    )
    monkeypatch.setattr(
        refresh_module, "OrderedProcessMapper", ShuffledUsageResultMapper
    )
    observed_orders: set[tuple[int, ...]] = set()
    for seed in range(16):
        ShuffledUsageResultMapper.seed = seed
        ShuffledUsageResultMapper.observed_orders.clear()
        actual = load_cached_session_data(
            [corpus.sessions],
            cache_dir=tmp_path / f"shuffled-cache-{seed}",
            auto_transitions=False,
            max_workers=4,
        )
        observed_orders.update(ShuffledUsageResultMapper.observed_orders)
        assert actual.stats == expected.stats
        assert actual.files == expected.files
        assert actual.records == expected.records
        assert actual.file_summaries == expected.file_summaries
        assert actual.file_errors == expected.file_errors
    assert len(observed_orders) >= 4
    malformed = [
        record
        for record in expected.records
        if record.file_path == corpus.malformed_json_path
    ]
    assert [record.usage.total_tokens for record in malformed] == [211]


def test_worker_error_retains_old_complete_rows_and_retries(tmp_path: Path) -> None:
    sessions, (path,) = write_valid_usage_set(tmp_path / "codex", count=1)
    cache_dir = tmp_path / "cache"
    initial = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    old_snapshot = complete_generation_snapshot(cache_dir)
    path.write_bytes(b"\xff\xfe")

    failed = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert failed.stats.file_errors == 1
    assert failed.stats.files_parsed == 1
    assert failed.records == initial.records
    assert failed.file_errors[str(path)].startswith("UnicodeDecodeError: ")
    assert complete_generation_snapshot(cache_dir) != old_snapshot
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        assert connection.execute(
            "select count(*) from usage_records"
        ).fetchone() == (1,)
        assert connection.execute(
            "select count(*) from session_metadata"
        ).fetchone() == (1,)

    write_valid_usage_set(tmp_path / "replacement", count=1)[1][0].replace(path)
    recovered = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert recovered.stats.files_parsed == 1
    assert recovered.stats.file_errors == 0
    assert recovered.file_errors == {}
    assert [record.usage.total_tokens for record in recovered.records] == [100]


def test_unreadable_fallback_key_reuses_stable_metadata_identity(
    tmp_path: Path,
) -> None:
    sessions, (path,) = write_valid_usage_set(tmp_path / "codex", count=1)
    stable_key = "stable-metadata-thread"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["payload"]["id"] = stable_key
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    valid_bytes = path.read_bytes()
    cache_dir = tmp_path / "cache"

    initial_inventory = collect_session_file_inventory([sessions])
    assert [(entry.file_key, entry.file_key_is_fallback) for entry in initial_inventory] == [
        (stable_key, False)
    ]
    initial = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        assert connection.execute(
            "select file_key, is_missing, error from files"
        ).fetchall() == [(stable_key, 0, "")]

    path.write_bytes(b"\xff\xfe")
    corrupt_inventory = collect_session_file_inventory([sessions])
    assert [(entry.file_key, entry.file_key_is_fallback) for entry in corrupt_inventory] == [
        (path.stem, True)
    ]
    failed = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert failed.records == initial.records
    assert failed.stats.files_parsed == 1
    assert failed.stats.files_removed == 0
    assert failed.stats.files_missing_retained == 0
    assert failed.stats.file_errors == 1
    assert failed.retained_missing_files == []
    assert len(failed.file_errors) == 1
    assert next(iter(failed.file_errors.values())).startswith("UnicodeDecodeError: ")
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        failed_rows = connection.execute(
            "select file_key, path, is_missing, error from files"
        ).fetchall()
    assert len(failed_rows) == 1
    assert failed_rows[0][:3] == (stable_key, str(path), 0)
    assert failed_rows[0][3].startswith("UnicodeDecodeError: ")

    path.write_bytes(valid_bytes)
    recovered = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert recovered.records == initial.records
    assert recovered.stats.files_parsed == 1
    assert recovered.stats.files_removed == 0
    assert recovered.stats.files_missing_retained == 0
    assert recovered.stats.file_errors == 0
    assert recovered.file_errors == {}
    assert recovered.retained_missing_files == []
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        assert connection.execute(
            "select file_key, path, is_missing, error from files"
        ).fetchall() == [(stable_key, str(path), 0, "")]


def test_valid_new_metadata_identity_replaces_same_path_alias_generation(
    tmp_path: Path,
) -> None:
    sessions, (path,) = write_valid_usage_set(tmp_path / "codex", count=1)
    cache_dir = tmp_path / "cache"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["payload"]["id"] = "old-thread"
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )

    rows[0]["payload"]["id"] = "new-thread"
    usage = rows[1]["payload"]["info"]["total_token_usage"]
    usage["input_tokens"] = 200
    usage["total_tokens"] = 200
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    current_inventory = collect_session_file_inventory([sessions])
    assert [(entry.file_key, entry.file_key_is_fallback) for entry in current_inventory] == [
        ("new-thread", False)
    ]

    replaced = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert replaced.stats.files_parsed == 1
    assert replaced.stats.files_removed == 1
    assert replaced.stats.files_missing_retained == 0
    assert replaced.file_errors == {}
    assert replaced.retained_missing_files == []
    assert [(record.session_id, record.usage.total_tokens) for record in replaced.records] == [
        ("new-thread", 200)
    ]
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        assert connection.execute("select file_key from files").fetchall() == [
            ("new-thread",)
        ]
        assert connection.execute(
            "select file_key, session_id from usage_records"
        ).fetchall() == [("new-thread", "new-thread")]
        assert connection.execute(
            "select file_key, session_id from session_metadata"
        ).fetchall() == [("new-thread", "new-thread")]


def test_insert_failure_rolls_back_all_eight_replacements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions, paths = write_valid_usage_set(tmp_path / "codex", count=8)
    cache_dir = tmp_path / "cache"
    load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    before = complete_generation_snapshot(cache_dir)
    for index, path in enumerate(paths):
        append_cumulative_token_total(
            path,
            total_tokens=200 + index,
            timestamp=f"2026-07-31T12:{index:02d}:00Z",
        )

    calls = 0
    original = refresh_module.replace_file_generation

    def fail_second_replacement(
        connection: sqlite3.Connection,
        session_dirs: list[Path],
        entry: SessionFileInventoryEntry,
        records: tuple[UsageRecord, ...],
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.IntegrityError(
                "injected second replacement failure"
            )
        original(connection, session_dirs, entry, records)

    monkeypatch.setattr(
        refresh_module, "replace_file_generation", fail_second_replacement
    )
    with pytest.raises(
        sqlite3.IntegrityError,
        match="injected second replacement failure",
    ):
        load_cached_session_data(
            [sessions],
            cache_dir=cache_dir,
            auto_transitions=False,
            max_workers=1,
        )
    assert calls == 2
    assert complete_generation_snapshot(cache_dir) == before


def test_interrupt_after_first_group_reuses_exactly_eight_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions, paths = write_valid_usage_set(tmp_path / "codex", count=9)
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(
        refresh_module,
        "OrderedProcessMapper",
        InterruptAfterFirstBatchMapper,
    )
    with pytest.raises(
        KeyboardInterrupt, match="after first committed batch"
    ):
        load_cached_session_data(
            [sessions],
            cache_dir=cache_dir,
            auto_transitions=False,
            max_workers=4,
        )
    monkeypatch.undo()

    resumed = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert resumed.stats.files_reused == 8
    assert resumed.stats.files_parsed == 1
    assert [record.file_path for record in resumed.records] == list(paths)
    assert sum(record.usage.total_tokens for record in resumed.records) == sum(
        range(100, 109)
    )
    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        assert connection.execute(
            "select count(*) from (select file_key, record_index from usage_records "
            "group by file_key, record_index having count(*) = 1)"
        ).fetchone() == (9,)
        assert tuple(
            connection.execute("select key, value from schema_meta order by key")
        ) == (
            ("parser_version", "2"),
            ("project_transition_version", "1"),
            ("project_transitions_dirty", "1"),
            ("schema_version", "3"),
        )


def test_growth_after_parse_forces_next_load_reparse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions, (path,) = write_valid_usage_set(tmp_path / "codex", count=1)
    cache_dir = tmp_path / "cache"
    original = refresh_module.parse_usage_request
    grew = False

    def parse_then_grow(request: UsageParseRequest) -> UsageParseResult:
        nonlocal grew
        result = original(request)
        if not grew:
            append_cumulative_token_total(
                path,
                total_tokens=160,
                timestamp="2026-07-31T12:30:00Z",
            )
            grew = True
        return result

    monkeypatch.setattr(refresh_module, "parse_usage_request", parse_then_grow)
    first = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    monkeypatch.undo()
    second = load_cached_session_data(
        [sessions], cache_dir=cache_dir, auto_transitions=False, max_workers=1
    )
    assert [record.usage.total_tokens for record in first.records] == [100]
    assert second.stats.files_parsed == 1
    assert [record.usage.total_tokens for record in second.records] == [100, 60]
