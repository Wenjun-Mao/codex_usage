from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import codex_usage.project_transition_evidence as evidence_module
import codex_usage.project_transition_state as state_module
from codex_usage.parallel.execution import (
    DEFAULT_MAX_WORKERS,
    OrderedProcessMapper,
    ParallelRunReport,
)
from codex_usage.parallel.transitions import (
    TransitionScanRequest,
    TransitionScanResult,
    scan_transition_request,
)
from codex_usage.project_transition_evidence import RepoPathObservation


def collect_repo_path_observations(
    session_dirs: list[Path],
    session_files: list[Path],
) -> list[RepoPathObservation]:
    observations, _report = collect_repo_path_observations_with_report(
        session_dirs,
        session_files,
    )
    return observations


def collect_repo_path_observations_with_report(
    session_dirs: list[Path],
    session_files: list[Path],
    *,
    max_workers: int | None = None,
) -> tuple[list[RepoPathObservation], ParallelRunReport]:
    requests = [
        TransitionScanRequest(ordinal=ordinal, path=path)
        for ordinal, path in enumerate(session_files)
    ]
    resolved_max_workers = (
        DEFAULT_MAX_WORKERS if max_workers is None else max_workers
    )
    with OrderedProcessMapper(
        scan_transition_request,
        task_count=len(requests),
        max_workers=resolved_max_workers,
    ) as mapper:
        results = _ordered_results(requests, mapper.map_batch(requests))

    verification_cache: evidence_module.VerificationCache = {}
    observations: list[RepoPathObservation] = []
    for result in results:
        observations.extend(
            evidence_module.verify_repo_path_candidates(
                result.candidates,
                verification_cache=verification_cache,
            )
        )
    observations.extend(
        state_module.collect_state_repo_path_observations(
            session_dirs,
            verification_cache=verification_cache,
        )
    )
    report = ParallelRunReport(
        resolved_worker_count=mapper.worker_count,
        worker_spans=tuple(result.span for result in results),
        used_serial_fallback=mapper.used_serial_fallback,
        infrastructure_error=mapper.infrastructure_error,
        file_error_count=sum(bool(result.error) for result in results),
    )
    return evidence_module._dedupe_observations(observations), report


def _ordered_results(
    requests: Sequence[TransitionScanRequest],
    results: Sequence[TransitionScanResult],
) -> tuple[TransitionScanResult, ...]:
    if len(results) != len(requests):
        raise ValueError("transition scan result count does not match request count")
    expected_by_ordinal = {request.ordinal: request for request in requests}
    if len(expected_by_ordinal) != len(requests):
        raise ValueError("transition scan requests contain duplicate ordinals")

    seen: set[int] = set()
    for result in results:
        ordinal = result.request.ordinal
        if ordinal in seen:
            raise ValueError("transition scan results contain duplicate ordinals")
        if expected_by_ordinal.get(ordinal) != result.request:
            raise ValueError("transition scan result does not match its request")
        seen.add(ordinal)
    if seen != set(expected_by_ordinal):
        raise ValueError("transition scan results do not cover every request")
    return tuple(sorted(results, key=lambda result: result.request.ordinal))
