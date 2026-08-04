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
from dataclasses import asdict
from pathlib import Path

SCRIPT_DIRECTORY = str(Path(__file__).parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

from parallel_cache_fixture import (
    FixtureCorpus,
    append_incremental_change,
    write_parallel_cache_fixture,
)

from codex_usage.discovery import find_session_dirs
from codex_usage.parallel.execution import ParallelRunReport
from codex_usage.parallel_audit import require_actual_parallel
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data
from codex_usage.session_cache_models import CachedSessionData
from codex_usage.session_inventory import collect_session_file_inventory


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
    payload = {
        "corpus": {
            "file_count": len(inventory),
            "byte_count": sum(entry.path.stat().st_size for entry in inventory),
        },
        "elapsed_seconds": {"cold": round(cold_elapsed, 6), "warm": round(warm_elapsed, 6)},
        "cold": _acceptance_snapshot(cold),
        "warm": _acceptance_snapshot(warm),
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
    session_dirs: list[Path], cache_dir: Path
) -> tuple[CachedSessionData, float]:
    started = time.perf_counter()
    data = load_cached_session_data(session_dirs, cache_dir=cache_dir, auto_transitions=True)
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
