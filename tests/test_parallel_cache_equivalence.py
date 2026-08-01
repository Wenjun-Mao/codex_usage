from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import project_transition_serial_oracle as serial_oracle
from parallel_cache_test_support import (
    EXPECTED_SCHEMA_META,
    EXPECTED_SQLITE_MASTER,
    attach_transition_evidence,
    complete_schema_metadata,
    load_parallel,
    load_serial,
    normalized_sqlite_master,
    write_usage_corpus,
)

from codex_usage.project_transition_collection import (
    collect_repo_path_observations_with_report,
)
from codex_usage.project_transitions import infer_project_transitions
from codex_usage.session_cache import CACHE_DB_NAME


def test_serial_and_parallel_cache_state_are_exactly_equal(tmp_path: Path) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    serial_cache = tmp_path / "serial-cache"
    parallel_cache = tmp_path / "parallel-cache"
    serial = load_serial(corpus, serial_cache, auto_transitions=False)
    parallel = load_parallel(corpus, parallel_cache, auto_transitions=False)

    assert parallel.stats == serial.stats
    assert parallel.files == serial.files
    assert parallel.records == serial.records
    assert parallel.file_summaries == serial.file_summaries
    assert parallel.file_errors == serial.file_errors
    assert parallel.retained_missing_files == serial.retained_missing_files
    assert parallel.project_transitions == serial.project_transitions == []
    malformed_serial = [
        record for record in serial.records if record.file_path == corpus.malformed_json_path
    ]
    malformed_parallel = [
        record for record in parallel.records if record.file_path == corpus.malformed_json_path
    ]
    assert [record.usage.total_tokens for record in malformed_serial] == [211]
    assert malformed_parallel == malformed_serial
    assert serial.usage_run.resolved_worker_count == 1
    assert serial.usage_run.worker_pids == (os.getpid(),)
    assert serial.usage_run.used_serial_fallback is False
    assert parallel.usage_run.resolved_worker_count > 1
    assert parallel.usage_run.worker_pids
    assert os.getpid() not in parallel.usage_run.worker_pids
    assert parallel.usage_run.used_serial_fallback is False

    for cache_dir in (serial_cache, parallel_cache):
        with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
            assert normalized_sqlite_master(connection) == EXPECTED_SQLITE_MASTER
            assert complete_schema_metadata(connection) == EXPECTED_SCHEMA_META


def test_serial_and_parallel_errors_and_retained_missing_are_equal(tmp_path: Path) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    serial_cache = tmp_path / "serial-cache"
    parallel_cache = tmp_path / "parallel-cache"
    load_serial(corpus, serial_cache, auto_transitions=False)
    load_parallel(corpus, parallel_cache, auto_transitions=False)
    corpus.missing_path.unlink()

    serial = load_serial(corpus, serial_cache, auto_transitions=False)
    parallel = load_parallel(corpus, parallel_cache, auto_transitions=False)
    assert parallel.stats == serial.stats
    assert parallel.records == serial.records
    assert parallel.file_summaries == serial.file_summaries
    assert parallel.file_errors == serial.file_errors
    assert parallel.retained_missing_files == serial.retained_missing_files == [corpus.missing_path]


def test_serial_and_parallel_transition_enabled_state_is_exactly_equal(
    tmp_path: Path,
) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    attach_transition_evidence(corpus)
    expected_observations = serial_oracle.collect_repo_path_observations(
        [corpus.sessions], list(corpus.ordered_paths)
    )
    raw = load_serial(corpus, tmp_path / "raw-cache", auto_transitions=False)
    expected_transitions = infer_project_transitions(raw.records, expected_observations)
    assert expected_observations
    assert expected_transitions

    serial = load_serial(corpus, tmp_path / "serial-cache", auto_transitions=True)
    parallel = load_parallel(corpus, tmp_path / "parallel-cache", auto_transitions=True)
    actual_observations, transition_run = collect_repo_path_observations_with_report(
        [corpus.sessions], list(corpus.ordered_paths), max_workers=4
    )
    assert actual_observations == expected_observations
    assert serial.project_transitions == parallel.project_transitions == expected_transitions
    assert parallel.records == serial.records
    assert parallel.file_summaries == serial.file_summaries
    assert parallel.stats == serial.stats
    assert parallel.file_errors == serial.file_errors
    assert parallel.retained_missing_files == serial.retained_missing_files
    assert transition_run.resolved_worker_count > 1
    assert transition_run.worker_pids
    assert os.getpid() not in transition_run.worker_pids
    assert transition_run.used_serial_fallback is False
