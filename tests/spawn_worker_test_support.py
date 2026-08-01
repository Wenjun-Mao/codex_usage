from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from codex_usage.parallel.execution import WorkerSpan


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
