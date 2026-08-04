from __future__ import annotations

import json
import os
from pathlib import Path

from parallel_cache_test_support import (
    load_parallel,
    write_usage_corpus,
    write_valid_usage_set,
)

_MINIMUM_PARALLEL_FILE_BYTES = 2 * 1024 * 1024


def test_parallel_corpus_uses_overlapping_child_workers_without_path_leakage(
    tmp_path: Path,
) -> None:
    corpus_root = tmp_path / "codex"
    corpus = write_usage_corpus(corpus_root)
    _, parallel_paths = write_valid_usage_set(corpus_root, count=10)
    for path in parallel_paths:
        _pad_jsonl_file(path)

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
    assert all(
        str(path) not in report_text
        for path in (*corpus.ordered_paths, *parallel_paths)
    )


def _pad_jsonl_file(path: Path) -> None:
    remaining = _MINIMUM_PARALLEL_FILE_BYTES - path.stat().st_size
    filler = json.dumps(
        {
            "timestamp": "2026-07-31T10:00:00Z",
            "type": "event_msg",
            "payload": {"type": "task_started", "padding": "x" * 896},
        }
    ) + "\n"
    repetitions = (remaining + len(filler) - 1) // len(filler)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(filler * repetitions)
