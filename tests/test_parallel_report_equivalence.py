from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from parallel_cache_test_support import (
    attach_transition_evidence,
    load_parallel,
    load_serial,
    render_report_text,
    write_usage_corpus,
)

from codex_usage.aggregation import (
    GROUP_CHOICES,
    aggregate_records,
    filter_records_by_range,
    resolve_range_bounds,
    resolve_timezone,
    summarize_records,
)
from codex_usage.reporting import summary_payload
from codex_usage.session_cache import load_cached_session_data


def test_serial_parallel_aggregation_payload_and_html_are_identical(
    tmp_path: Path,
) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    serial = load_serial(corpus, tmp_path / "serial-cache", auto_transitions=True)
    parallel = load_parallel(corpus, tmp_path / "parallel-cache", auto_transitions=True)
    timezone = resolve_timezone("UTC")
    generated_at = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    serial_rows = {
        group: aggregate_records(serial.records, group, timezone) for group in GROUP_CHOICES
    }
    parallel_rows = {
        group: aggregate_records(parallel.records, group, timezone)
        for group in GROUP_CHOICES
    }
    assert parallel_rows == serial_rows
    assert summarize_records(parallel.records) == summarize_records(serial.records)

    serial_payload = summary_payload(
        rows=serial_rows["day"], total=summarize_records(serial.records),
        generated_at=generated_at, range_name="all", group_by="day",
        sessions_dirs=serial.session_dirs, files_scanned=len(serial.files),
        storage_roots=[str(path) for path in serial.session_dirs],
        files_archived=serial.stats.files_archived,
        files_retained_missing=serial.stats.files_missing_retained,
        project_keys=[], project_transitions=[item.to_dict() for item in serial.project_transitions],
    )
    parallel_payload = summary_payload(
        rows=parallel_rows["day"], total=summarize_records(parallel.records),
        generated_at=generated_at, range_name="all", group_by="day",
        sessions_dirs=parallel.session_dirs, files_scanned=len(parallel.files),
        storage_roots=[str(path) for path in parallel.session_dirs],
        files_archived=parallel.stats.files_archived,
        files_retained_missing=parallel.stats.files_missing_retained,
        project_keys=[], project_transitions=[item.to_dict() for item in parallel.project_transitions],
    )
    assert parallel_payload == serial_payload
    assert render_report_text(parallel, generated_at, tmp_path / "parallel.html") == render_report_text(
        serial, generated_at, tmp_path / "serial.html"
    )


def test_old_start_and_old_mtime_do_not_prune_recent_usage(tmp_path: Path) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    old = datetime.now(UTC) - timedelta(days=30)
    os.utime(corpus.recent_old_metadata_path, (old.timestamp(), old.timestamp()))
    data = load_parallel(corpus, tmp_path / "cache", auto_transitions=False)
    ranged = filter_records_by_range(data.records, "7d", resolve_timezone("UTC"))
    assert any(record.file_path == corpus.recent_old_metadata_path for record in ranged)
    assert data.stats.files_parsed == data.stats.files_current


@pytest.mark.parametrize(
    ("timezone", "now"),
    [
        (UTC, datetime(2026, 7, 31, 12, tzinfo=UTC)),
        (
            ZoneInfo("America/Toronto"),
            datetime(2026, 7, 31, 12, tzinfo=ZoneInfo("America/Toronto")),
        ),
    ],
)
def test_range_queries_match_full_load_oracle_for_every_range(
    tmp_path: Path,
    timezone,
    now: datetime,
) -> None:
    corpus = write_usage_corpus(tmp_path / "codex")
    attach_transition_evidence(corpus)
    cache_dir = tmp_path / "cache"
    full = load_serial(corpus, cache_dir, auto_transitions=True)

    for range_name in ("today", "yesterday", "7d", "30d", "month", "all"):
        bounds = resolve_range_bounds(range_name, timezone, now)
        ranged = load_cached_session_data(
            [corpus.sessions],
            cache_dir=cache_dir,
            auto_transitions=True,
            max_workers=1,
            range_bounds=bounds,
        )

        expected = filter_records_by_range(full.records, range_name, timezone, now)

        assert sorted(ranged.records, key=_record_key) == sorted(expected, key=_record_key)
        assert ranged.project_transitions == full.project_transitions


def _record_key(record) -> tuple[str, datetime, str, str, int]:
    return (
        record.session_id,
        record.timestamp,
        str(record.file_path),
        record.turn_id,
        record.usage.total_tokens,
    )
