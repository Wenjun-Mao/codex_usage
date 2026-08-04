from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from codex_usage.parallel_audit import atomic_write
from codex_usage.session_cache_models import CacheStats

_SERIALIZATION_DECIMAL_PLACES = 6


class PhaseTimer:
    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._elapsed: dict[str, float] = {}
        self._active: list[str] = []

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        if not name:
            raise ValueError("phase name must not be empty")
        if name in self._active:
            raise ValueError(f"phase {name!r} is already active")

        self._active.append(name)
        started = self._clock()
        try:
            yield
        finally:
            elapsed = self._clock() - started
            self._active.remove(name)
            if elapsed < 0:
                raise ValueError(f"phase {name!r} has negative elapsed time")
            self._elapsed[name] = self._elapsed.get(name, 0.0) + elapsed

    def elapsed_seconds(self, name: str) -> float:
        return self._elapsed.get(name, 0.0)

    def phases_seconds(self) -> dict[str, float]:
        return dict(self._elapsed)


def write_timing_sidecar(
    path: Path,
    timer: PhaseTimer,
    *,
    cache_stats: CacheStats,
    command: str,
) -> None:
    payload = {
        "version": 1,
        "command": command,
        "cache": {
            "rebuilt": cache_stats.rebuilt,
            "files_total": cache_stats.files_total,
            "files_current": cache_stats.files_current,
            "files_archived": cache_stats.files_archived,
            "files_parsed": cache_stats.files_parsed,
            "files_reused": cache_stats.files_reused,
            "files_removed": cache_stats.files_removed,
            "files_missing_retained": cache_stats.files_missing_retained,
            "file_errors": cache_stats.file_errors,
            "legacy_cleanup_errors": cache_stats.legacy_cleanup_errors,
        },
        "phases_seconds": _rounded_values(timer.phases_seconds()),
        "total_seconds": _rounded(timer.elapsed_seconds("total_cli")),
    }
    atomic_write(path, json.dumps(payload, indent=2) + "\n")


def _rounded_values(values: dict[str, float]) -> dict[str, float]:
    return {name: _rounded(value) for name, value in values.items()}


def _rounded(value: float) -> float:
    return round(value, _SERIALIZATION_DECIMAL_PLACES)
