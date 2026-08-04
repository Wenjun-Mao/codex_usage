#!/usr/bin/env python3
"""Prove cold, warm, and one-file incremental cache-refresh semantics."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from codex_usage.aggregation import (
    RangeBounds,
    aggregate_records,
    datetime_to_utc_microseconds,
    summarize_records,
)
from codex_usage.discovery import find_session_dirs
from codex_usage.models import UsageRecord
from codex_usage.parallel.execution import ParallelRunReport
from codex_usage.parallel_audit import require_actual_parallel
from codex_usage.report_breakdown import build_report_breakdown
from codex_usage.reporting import render_html_report
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data
from codex_usage.session_cache_models import CachedSessionData
from codex_usage.session_inventory import collect_session_file_inventory

SCRIPT_DIRECTORY = str(Path(__file__).parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

from parallel_cache_fixture import (  # noqa: E402 - direct execution needs the sibling fixture path.
    FixtureCorpus,
    append_incremental_change,
    write_parallel_cache_fixture,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prove spawned-worker cache refresh and warm reuse semantics."
    )
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--sessions-dir", type=Path)
    sources.add_argument("--synthetic", action="store_true")
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args(argv)

    if (os.process_cpu_count() or 1) <= 1:
        raise RuntimeError("parallel acceptance requires more than one process CPU")
    if args.synthetic:
        with tempfile.TemporaryDirectory(prefix="codex-usage-parallel-") as directory:
            root = Path(directory)
            corpus = write_parallel_cache_fixture(root)
            payload = _run_fixture_acceptance(corpus, args.cache_dir or root / "cache")
    else:
        session_dirs = [args.sessions_dir] if args.sessions_dir else find_session_dirs()
        payload = _run_existing_acceptance(
            session_dirs,
            args.cache_dir,
            exercise_changed=args.sessions_dir is not None,
        )
    print(json.dumps(payload, sort_keys=True))
    return 0


def _run_fixture_acceptance(corpus: FixtureCorpus, cache_dir: Path) -> dict[str, object]:
    session_dirs = [corpus.sessions_dir]
    inventory = collect_session_file_inventory(session_dirs)
    _require_cold_cache(cache_dir)

    cold, cold_elapsed = _timed_load(session_dirs, cache_dir)
    _require_actual_parallel(cold.usage_run, "cold usage")
    _require_zero_transition_spans(cold, "cold")

    warm, warm_elapsed = _timed_load(session_dirs, cache_dir)
    _require_warm_semantics(cold, warm)
    warm_report = _render_bounded_warm_report(session_dirs, cache_dir, warm)

    changed_file = append_incremental_change(corpus)
    changed, changed_elapsed = _timed_load(session_dirs, cache_dir)
    _require_changed_semantics(changed, len(inventory))

    oracle, oracle_elapsed = _timed_load(session_dirs, cache_dir / "cold-oracle")
    changed_semantic_digest = _semantic_digest(changed)
    cold_after_same_append_digest = _semantic_digest(oracle)
    if changed_semantic_digest != cold_after_same_append_digest:
        raise RuntimeError("incremental semantic digest differs from cold oracle")

    return {
        "corpus": {"file_count": len(inventory), "byte_count": corpus.byte_count},
        "elapsed_seconds": {
            "cold": round(cold_elapsed, 6),
            "warm": round(warm_elapsed, 6),
            "changed": round(changed_elapsed, 6),
            "cold_oracle": round(oracle_elapsed, 6),
        },
        "cold": _acceptance_snapshot(cold),
        "warm": _acceptance_snapshot(warm),
        "warm_report": warm_report,
        "changed": {
            **_acceptance_snapshot(changed),
            "source_bytes_eligible": changed_file.stat().st_size,
        },
        "oracle": _acceptance_snapshot(oracle),
    }


def _run_existing_acceptance(
    session_dirs: list[Path],
    cache_dir: Path | None,
    *,
    exercise_changed: bool = True,
) -> dict[str, object]:
    inventory = collect_session_file_inventory(session_dirs)
    if len(inventory) < 2:
        raise RuntimeError("parallel acceptance requires at least two session files")
    if cache_dir is None:
        with tempfile.TemporaryDirectory(prefix="codex-usage-parallel-") as directory:
            return _run_existing_acceptance(
                session_dirs,
                Path(directory),
                exercise_changed=exercise_changed,
            )
    _require_cold_cache(cache_dir)
    cold, cold_elapsed = _timed_load(session_dirs, cache_dir)
    _require_actual_parallel(cold.usage_run, "cold usage")
    _require_zero_transition_spans(cold, "cold")
    warm, warm_elapsed = _timed_load(session_dirs, cache_dir)
    _require_warm_semantics(cold, warm)
    warm_report = _render_bounded_warm_report(session_dirs, cache_dir, warm)
    payload = {
        "corpus": {
            "file_count": len(inventory),
            "byte_count": sum(entry.path.stat().st_size for entry in inventory),
        },
        "elapsed_seconds": {"cold": round(cold_elapsed, 6), "warm": round(warm_elapsed, 6)},
        "cold": _acceptance_snapshot(cold),
        "warm": _acceptance_snapshot(warm),
        "warm_report": warm_report,
    }
    if not exercise_changed:
        return payload

    changed_file = append_incremental_change(
        FixtureCorpus(
            sessions_dir=session_dirs[0],
            files=tuple(entry.path for entry in inventory),
            transition_target=Path.cwd(),
            changed_file=inventory[0].path,
        )
    )
    changed, changed_elapsed = _timed_load(session_dirs, cache_dir)
    _require_changed_semantics(changed, len(inventory))

    oracle, oracle_elapsed = _timed_load(session_dirs, cache_dir / "cold-oracle")
    changed_semantic_digest = _semantic_digest(changed)
    cold_after_same_append_digest = _semantic_digest(oracle)
    if changed_semantic_digest != cold_after_same_append_digest:
        raise RuntimeError("incremental semantic digest differs from cold oracle")

    payload["elapsed_seconds"].update(
        {"changed": round(changed_elapsed, 6), "cold_oracle": round(oracle_elapsed, 6)}
    )
    payload["changed"] = {
        **_acceptance_snapshot(changed),
        "source_bytes_eligible": changed_file.stat().st_size,
    }
    payload["oracle"] = _acceptance_snapshot(oracle)
    return payload


def _timed_load(
    session_dirs: list[Path],
    cache_dir: Path,
    *,
    range_bounds: RangeBounds | None = None,
    max_workers: int | None = None,
) -> tuple[CachedSessionData, float]:
    started = time.perf_counter()
    data = load_cached_session_data(
        session_dirs,
        cache_dir=cache_dir,
        auto_transitions=True,
        range_bounds=range_bounds,
        max_workers=max_workers,
    )
    return data, time.perf_counter() - started


def _require_cold_cache(cache_dir: Path) -> None:
    if (cache_dir / CACHE_DB_NAME).exists():
        raise RuntimeError("parallel acceptance cache must be cold")


def _require_actual_parallel(report: ParallelRunReport, label: str) -> None:
    require_actual_parallel(report, parent_pid=os.getpid(), label=label)


def _require_zero_transition_spans(data: CachedSessionData, label: str) -> None:
    if data.transition_run.worker_spans:
        raise RuntimeError(f"{label} transition: unexpected worker spans")


def _require_no_fallback(report: ParallelRunReport, label: str) -> None:
    if report.used_serial_fallback:
        raise RuntimeError(f"{label}: serial fallback observed")


def _require_warm_semantics(cold: CachedSessionData, warm: CachedSessionData) -> None:
    if _semantic_digest(cold) != _semantic_digest(warm):
        raise RuntimeError("warm semantic digest differs from cold digest")
    _require_no_fallback(warm.usage_run, "warm usage")
    _require_no_fallback(warm.transition_run, "warm transition")
    if warm.stats.files_parsed != 0 or warm.usage_run.worker_spans:
        raise RuntimeError("warm usage parsed source files")
    _require_zero_transition_spans(warm, "warm")
    successful_cold_generations = cold.stats.files_parsed - cold.stats.file_errors
    if warm.stats.files_reused != successful_cold_generations:
        raise RuntimeError("warm run did not reuse every successful cold generation")


def _render_bounded_warm_report(
    session_dirs: list[Path],
    cache_dir: Path,
    unbounded: CachedSessionData,
) -> dict[str, object]:
    bounds = _bounded_range(unbounded.records)
    with tempfile.TemporaryDirectory(prefix="codex-usage-warm-report-") as directory:
        report_path = Path(directory) / "report.html"
        with _block_source_jsonl_reads(session_dirs) as read_attempts:
            ranged, _ = _timed_load(
                session_dirs,
                cache_dir,
                range_bounds=bounds,
                max_workers=1,
            )
            _require_bounded_warm_semantics(unbounded, ranged)
            breakdown = build_report_breakdown(ranged.records)
            render_html_report(
                output_path=report_path,
                generated_at=datetime(2026, 7, 31, 12, tzinfo=UTC),
                range_name="bounded-cache-acceptance",
                total=summarize_records(ranged.records),
                daily_rows=aggregate_records(ranged.records, "day", UTC),
                hourly_rows=aggregate_records(ranged.records, "hour", UTC),
                breakdown=breakdown,
                sessions_dirs=session_dirs,
                files_scanned=len(ranged.files),
                theme="night",
            )
            report_html = report_path.read_text(encoding="utf-8")

    if read_attempts.count:
        raise RuntimeError("bounded warm report opened source JSONL files")
    for marker in ('data-report-section="project-breakdown"', 'data-report-section="model-mix"'):
        if marker not in report_html:
            raise RuntimeError(f"bounded warm report is missing {marker}")
    if not breakdown.projects or not breakdown.model_rows:
        raise RuntimeError("bounded warm report did not build project/model breakdown rows")
    return {
        "range_record_count": len(ranged.records),
        "unbounded_record_count": len(unbounded.records),
        "source_jsonl_read_attempts": read_attempts.count,
        "stats": asdict(ranged.stats),
        "usage_run": _run_counts(ranged.usage_run),
        "transition_run": _run_counts(ranged.transition_run),
        "project_count": len(breakdown.projects),
        "model_count": len(breakdown.model_rows),
        "report_bytes": len(report_html.encode()),
    }


def _bounded_range(records: list[UsageRecord]) -> RangeBounds:
    timestamps = sorted({record.timestamp for record in records})
    if len(timestamps) < 2:
        raise RuntimeError("bounded warm report requires at least two cached timestamps")
    return RangeBounds(
        start_us=datetime_to_utc_microseconds(timestamps[0]),
        end_us=datetime_to_utc_microseconds(timestamps[-1]),
    )


def _require_bounded_warm_semantics(
    unbounded: CachedSessionData,
    ranged: CachedSessionData,
) -> None:
    _require_no_fallback(ranged.usage_run, "bounded warm usage")
    _require_no_fallback(ranged.transition_run, "bounded warm transition")
    if ranged.stats.files_parsed or ranged.usage_run.worker_spans:
        raise RuntimeError("bounded warm report parsed source files")
    _require_zero_transition_spans(ranged, "bounded warm")
    if not 0 < len(ranged.records) < len(unbounded.records):
        raise RuntimeError("bounded warm range query did not filter cached records")


class _SourceJsonlReadAttempts:
    def __init__(self, session_dirs: list[Path]) -> None:
        self._roots = tuple(path.resolve() for path in session_dirs)
        self.count = 0

    def blocks(self, path: Path) -> bool:
        candidate = path.resolve(strict=False)
        return candidate.suffix == ".jsonl" and any(
            candidate.is_relative_to(root) for root in self._roots
        )


@contextmanager
def _block_source_jsonl_reads(
    session_dirs: list[Path],
) -> Iterator[_SourceJsonlReadAttempts]:
    attempts = _SourceJsonlReadAttempts(session_dirs)
    original_open = Path.open
    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text

    def guard_open(path: Path, *args: object, **kwargs: object):
        if attempts.blocks(path):
            attempts.count += 1
            raise RuntimeError("bounded warm report attempted source JSONL access")
        return original_open(path, *args, **kwargs)

    def guard_read_bytes(path: Path) -> bytes:
        if attempts.blocks(path):
            attempts.count += 1
            raise RuntimeError("bounded warm report attempted source JSONL access")
        return original_read_bytes(path)

    def guard_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if attempts.blocks(path):
            attempts.count += 1
            raise RuntimeError("bounded warm report attempted source JSONL access")
        return original_read_text(path, *args, **kwargs)

    with (
        patch.object(Path, "open", guard_open),
        patch.object(Path, "read_bytes", guard_read_bytes),
        patch.object(Path, "read_text", guard_read_text),
    ):
        yield attempts


def _require_changed_semantics(
    changed: CachedSessionData,
    inventory_file_count: int,
) -> None:
    _require_no_fallback(changed.usage_run, "changed usage")
    _require_no_fallback(changed.transition_run, "changed transition")
    if changed.stats.files_parsed != 1 or len(changed.usage_run.worker_spans) != 1:
        raise RuntimeError("one-file change did not produce one combined usage worker span")
    if changed.stats.files_reused != inventory_file_count - 1:
        raise RuntimeError("one-file change did not reuse every other inventory file")
    _require_zero_transition_spans(changed, "changed")


def _acceptance_snapshot(data: CachedSessionData) -> dict[str, object]:
    return {
        "stats": asdict(data.stats),
        "record_count": len(data.records),
        "transition_count": len(data.project_transitions),
        "semantic_digest": _semantic_digest(data),
        "usage_run": _run_counts(data.usage_run),
        "transition_run": _run_counts(data.transition_run),
    }


def _semantic_digest(data: CachedSessionData) -> str:
    return _json_digest(
        {
            "records": [record.to_dict() for record in data.records],
            "transitions": [transition.to_dict() for transition in data.project_transitions],
        }
    )


def _json_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _run_counts(report: ParallelRunReport) -> dict[str, object]:
    return report.to_dict()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
