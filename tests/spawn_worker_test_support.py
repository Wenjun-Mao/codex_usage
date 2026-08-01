from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Never

from codex_usage.parallel.execution import WorkerSpan
from codex_usage.parallel.transitions import (
    TransitionScanRequest,
    TransitionScanResult,
    scan_transition_request,
)
from codex_usage.parallel.usage import (
    UsageParseRequest,
    UsageParseResult,
    parse_usage_request,
)


@dataclass(frozen=True, slots=True)
class OverlapRequest:
    ordinal: int
    barrier: Any
    active: Any
    peak: Any
    lock: Any


@dataclass(frozen=True, slots=True)
class OverlapResult:
    ordinal: int
    span: WorkerSpan


def overlap_worker(request: OverlapRequest) -> OverlapResult:
    started = time.monotonic_ns()
    pid = os.getpid()
    with request.lock:
        request.active.value += 1
        request.peak.value = max(request.peak.value, request.active.value)
    request.barrier.wait(timeout=20)
    with request.lock:
        request.active.value -= 1
    return OverlapResult(
        ordinal=request.ordinal,
        span=WorkerSpan(pid=pid, started_ns=started, finished_ns=time.monotonic_ns()),
    )


def reject_sqlite_connect(*args: object, **kwargs: object) -> Never:
    raise AssertionError("worker attempted SQLite")


def guarded_usage_worker(request: UsageParseRequest) -> UsageParseResult:
    original = sqlite3.connect
    sqlite3.connect = reject_sqlite_connect
    try:
        return parse_usage_request(request)
    finally:
        sqlite3.connect = original


def guarded_transition_worker(
    request: TransitionScanRequest,
) -> TransitionScanResult:
    original = sqlite3.connect
    sqlite3.connect = reject_sqlite_connect
    try:
        return scan_transition_request(request)
    finally:
        sqlite3.connect = original
