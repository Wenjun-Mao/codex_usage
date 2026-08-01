from __future__ import annotations

import multiprocessing
import os
import pickle
import warnings
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from functools import partial
from types import TracebackType
from typing import Final, Self, cast

DEFAULT_MAX_WORKERS: Final[int] = 4
SERIAL_FALLBACK_WARNING: Final[str] = (
    "process pool infrastructure failed; continuing serially"
)

_CONSTRUCTION_OR_SUBMISSION_ERRORS = (
    OSError,
    RuntimeError,
    pickle.PicklingError,
    BrokenProcessPool,
)
_RESULT_TRANSPORT_ERRORS = (pickle.PicklingError, BrokenProcessPool)
_UNSET: Final[object] = object()


@dataclass(frozen=True, slots=True)
class _WorkerSuccess[ResultT]:
    result: ResultT


@dataclass(frozen=True, slots=True)
class _WorkerFailure:
    error: Exception


type _WorkerOutcome[ResultT] = _WorkerSuccess[ResultT] | _WorkerFailure


def _invoke_worker[RequestT, ResultT](
    worker: Callable[[RequestT], ResultT],
    request: RequestT,
) -> _WorkerOutcome[ResultT]:
    try:
        return _WorkerSuccess(worker(request))
    except _RESULT_TRANSPORT_ERRORS as error:
        return _WorkerFailure(error)


@dataclass(frozen=True, slots=True)
class WorkerSpan:
    pid: int
    started_ns: int
    finished_ns: int

    def __post_init__(self) -> None:
        if self.pid <= 0:
            raise ValueError("pid must be greater than zero")
        if self.finished_ns < self.started_ns:
            raise ValueError("finished_ns must be greater than or equal to started_ns")


@dataclass(frozen=True, slots=True)
class ParallelRunReport:
    resolved_worker_count: int
    worker_spans: tuple[WorkerSpan, ...]
    used_serial_fallback: bool
    infrastructure_error: str
    file_error_count: int

    @property
    def worker_pids(self) -> tuple[int, ...]:
        return tuple(dict.fromkeys(span.pid for span in self.worker_spans))

    @property
    def max_concurrency(self) -> int:
        events = [
            event
            for span in self.worker_spans
            if span.finished_ns > span.started_ns
            for event in (
                (span.started_ns, 1, span.pid),
                (span.finished_ns, -1, span.pid),
            )
        ]
        active_spans_by_pid: dict[int, int] = {}
        peak = 0
        for _, change, pid in sorted(events, key=lambda event: (event[0], event[1])):
            if change > 0:
                active_spans_by_pid[pid] = active_spans_by_pid.get(pid, 0) + 1
            else:
                remaining = active_spans_by_pid[pid] - 1
                if remaining:
                    active_spans_by_pid[pid] = remaining
                else:
                    del active_spans_by_pid[pid]
            peak = max(peak, len(active_spans_by_pid))
        return peak

    def actually_parallel(self, parent_pid: int) -> bool:
        worker_pids = set(self.worker_pids)
        return (
            self.resolved_worker_count > 1
            and not self.used_serial_fallback
            and parent_pid not in worker_pids
            and len(worker_pids) >= 2
            and self.max_concurrency >= 2
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "resolved_worker_count": self.resolved_worker_count,
            "worker_pids": list(self.worker_pids),
            "max_concurrency": self.max_concurrency,
            "used_serial_fallback": self.used_serial_fallback,
            "infrastructure_error": self.infrastructure_error,
            "span_count": len(self.worker_spans),
            "file_error_count": self.file_error_count,
        }


EMPTY_PARALLEL_RUN_REPORT: Final[ParallelRunReport] = ParallelRunReport(
    0,
    (),
    False,
    "",
    0,
)


def resolve_worker_count(
    task_count: int,
    *,
    available_cpus: int | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> int:
    if task_count < 0:
        raise ValueError("task_count must be non-negative")
    if max_workers < 1:
        raise ValueError("max_workers must be at least one")
    if task_count == 0:
        return 0

    cpu_count = available_cpus if available_cpus is not None else os.process_cpu_count()
    return min(task_count, max_workers, max(1, cpu_count or 1))


class OrderedProcessMapper[RequestT, ResultT]:
    def __init__(
        self,
        worker: Callable[[RequestT], ResultT],
        *,
        task_count: int,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> None:
        self._worker = worker
        self._process_worker = partial(_invoke_worker, worker)
        self.worker_count = resolve_worker_count(task_count, max_workers=max_workers)
        self.used_serial_fallback = False
        self.infrastructure_error = ""
        self._executor: ProcessPoolExecutor | None = None

        if self.worker_count >= 2:
            try:
                self._executor = ProcessPoolExecutor(
                    max_workers=self.worker_count,
                    mp_context=multiprocessing.get_context("spawn"),
                )
            except _CONSTRUCTION_OR_SUBMISSION_ERRORS as error:
                self._activate_serial_fallback(error)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        self._shutdown_executor(wait=exc_type is None, cancel_futures=exc_type is not None)

    def map_batch(self, requests: Sequence[RequestT]) -> list[ResultT]:
        if self.worker_count == 0:
            return []
        if self.worker_count == 1 or self.used_serial_fallback:
            return self._map_serially(requests)

        executor = self._executor
        if executor is None:
            raise RuntimeError("process executor is unavailable")

        futures_by_position: dict[Future[_WorkerOutcome[ResultT]], int] = {}
        try:
            for position, request in enumerate(requests):
                future = executor.submit(self._process_worker, request)
                futures_by_position[future] = position
        except _CONSTRUCTION_OR_SUBMISSION_ERRORS as error:
            return self._fallback_current_batch(error, requests)

        results: list[ResultT | object] = [_UNSET] * len(requests)
        worker_error: Exception | None = None
        try:
            for future in as_completed(futures_by_position):
                outcome = future.result()
                if isinstance(outcome, _WorkerFailure):
                    worker_error = outcome.error
                    break
                results[futures_by_position[future]] = outcome.result
        except _RESULT_TRANSPORT_ERRORS as error:
            return self._fallback_current_batch(error, requests)
        if worker_error is not None:
            raise worker_error
        return [cast(ResultT, result) for result in results]

    def _map_serially(self, requests: Sequence[RequestT]) -> list[ResultT]:
        return [self._worker(request) for request in requests]

    def _fallback_current_batch(
        self,
        error: Exception,
        requests: Sequence[RequestT],
    ) -> list[ResultT]:
        self._activate_serial_fallback(error)
        return self._map_serially(requests)

    def _activate_serial_fallback(self, error: Exception) -> None:
        if self.used_serial_fallback:
            return
        self.used_serial_fallback = True
        self.infrastructure_error = f"{type(error).__name__}: {error}"
        self._shutdown_executor(wait=False, cancel_futures=True)
        warnings.warn(SERIAL_FALLBACK_WARNING, RuntimeWarning, stacklevel=2)

    def _shutdown_executor(self, *, wait: bool, cancel_futures: bool) -> None:
        executor = self._executor
        if executor is None:
            return
        self._executor = None
        executor.shutdown(wait=wait, cancel_futures=cancel_futures)
