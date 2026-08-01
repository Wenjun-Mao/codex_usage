#!/usr/bin/env python3
"""Prove cold process parallelism and warm cache reuse on a source corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from codex_usage.discovery import find_session_dirs
from codex_usage.parallel.execution import ParallelRunReport
from codex_usage.parallel_audit import require_actual_parallel
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data
from codex_usage.session_cache_models import CachedSessionData
from codex_usage.session_inventory import (
    SessionFileInventoryEntry,
    collect_session_file_inventory,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prove spawned-worker cache refresh and warm reuse semantics."
    )
    parser.add_argument("--sessions-dir", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args(argv)

    available_cpus = os.process_cpu_count() or 1
    if available_cpus <= 1:
        raise RuntimeError("parallel acceptance requires more than one process CPU")

    session_dirs = [args.sessions_dir] if args.sessions_dir else find_session_dirs()
    inventory = collect_session_file_inventory(session_dirs)
    if len(inventory) < 2:
        raise RuntimeError("parallel acceptance requires at least two session files")

    if args.cache_dir is None:
        with tempfile.TemporaryDirectory(prefix="codex-usage-parallel-") as directory:
            return _run_acceptance(session_dirs, Path(directory), inventory)
    return _run_acceptance(session_dirs, args.cache_dir, inventory)


def _run_acceptance(
    session_dirs: list[Path],
    cache_dir: Path,
    inventory: list[SessionFileInventoryEntry],
) -> int:
    if (cache_dir / CACHE_DB_NAME).exists():
        raise RuntimeError("parallel acceptance cache must be cold")

    parent_pid = os.getpid()
    cold_started = time.perf_counter()
    cold = load_cached_session_data(
        session_dirs,
        cache_dir=cache_dir,
        auto_transitions=True,
    )
    cold_elapsed = time.perf_counter() - cold_started
    require_actual_parallel(cold.usage_run, parent_pid=parent_pid, label="cold usage")
    require_actual_parallel(
        cold.transition_run,
        parent_pid=parent_pid,
        label="cold transition",
    )

    warm_started = time.perf_counter()
    warm = load_cached_session_data(
        session_dirs,
        cache_dir=cache_dir,
        auto_transitions=True,
    )
    warm_elapsed = time.perf_counter() - warm_started
    _require_no_fallback(warm.usage_run, "warm usage")
    _require_no_fallback(warm.transition_run, "warm transition")
    _require_warm_semantics(cold, warm)

    corpus_bytes = sum(entry.path.stat().st_size for entry in inventory)
    payload = {
        "corpus": {"file_count": len(inventory), "byte_count": corpus_bytes},
        "elapsed_seconds": {
            "cold": round(cold_elapsed, 6),
            "warm": round(warm_elapsed, 6),
        },
        "cold": _acceptance_snapshot(cold),
        "warm": _acceptance_snapshot(warm),
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


def _require_no_fallback(report: ParallelRunReport, label: str) -> None:
    if report.used_serial_fallback:
        raise RuntimeError(f"{label}: serial fallback observed")


def _require_warm_semantics(
    cold: CachedSessionData,
    warm: CachedSessionData,
) -> None:
    cold_digests = _semantic_digests(cold)
    warm_digests = _semantic_digests(warm)
    if warm_digests != cold_digests:
        raise RuntimeError("warm semantic digests do not match cold digests")

    successful_cold_generations = cold.stats.files_parsed - cold.stats.file_errors
    if warm.stats.files_reused != successful_cold_generations:
        raise RuntimeError("warm run did not reuse every successful cold generation")
    if warm.stats.files_parsed != cold.stats.file_errors:
        raise RuntimeError("warm run did not retry only cold error rows")


def _acceptance_snapshot(data: CachedSessionData) -> dict[str, object]:
    return {
        "stats": asdict(data.stats),
        "record_count": len(data.records),
        "transition_count": len(data.project_transitions),
        "digests": _semantic_digests(data),
        "usage_run": _run_counts(data.usage_run),
        "transition_run": _run_counts(data.transition_run),
    }


def _semantic_digests(data: CachedSessionData) -> dict[str, str]:
    return {
        "records_sha256": _json_digest([record.to_dict() for record in data.records]),
        "transitions_sha256": _json_digest(
            [transition.to_dict() for transition in data.project_transitions]
        ),
    }


def _json_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _run_counts(report: ParallelRunReport) -> dict[str, object]:
    return {
        "resolved_worker_count": report.resolved_worker_count,
        "worker_pids": list(report.worker_pids),
        "max_concurrency": report.max_concurrency,
        "used_serial_fallback": report.used_serial_fallback,
        "span_count": len(report.worker_spans),
        "file_error_count": report.file_error_count,
    }


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
