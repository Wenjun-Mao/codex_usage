from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import codex_usage.project_transition_candidates as candidate_module
from codex_usage.parallel.execution import WorkerSpan
from codex_usage.project_transition_candidates import RawRepoPathCandidate


@dataclass(frozen=True, slots=True)
class TransitionScanRequest:
    ordinal: int
    path: Path


@dataclass(frozen=True, slots=True)
class TransitionScanResult:
    request: TransitionScanRequest
    candidates: tuple[RawRepoPathCandidate, ...]
    error: str
    span: WorkerSpan


def scan_transition_request(request: TransitionScanRequest) -> TransitionScanResult:
    started_ns = time.monotonic_ns()
    pid = os.getpid()
    try:
        candidates = tuple(
            candidate_module.collect_jsonl_repo_path_candidates(request.path)
        )
        error = ""
    except candidate_module.PartialTransitionReadError as exc:
        candidates = exc.candidates
        error = f"{type(exc.cause).__name__}: {exc.cause}"
    return TransitionScanResult(
        request=request,
        candidates=candidates,
        error=error,
        span=WorkerSpan(
            pid=pid,
            started_ns=started_ns,
            finished_ns=time.monotonic_ns(),
        ),
    )
