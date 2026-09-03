from __future__ import annotations

import itertools
import queue
import sys
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, TypeVar, cast


ResultT = TypeVar("ResultT")


class JobPriority(IntEnum):
    TASK_TRANSFER = 0
    CAPTURE_NOW = 0
    SCHEDULED_CAPTURE = 10
    STORAGE_ANALYSIS = 20
    BASELINE_REBUILD = 30


@dataclass(order=True)
class _QueuedJob:
    priority: int
    sequence: int
    key: str = field(compare=False)
    operation: Callable[[], object] | None = field(compare=False)
    future: Future[object] | None = field(compare=False)


_STOP_PRIORITY = sys.maxsize


class HeavyIOLane:
    """One writer/I/O lane with priority ordering and duplicate coalescing."""

    def __init__(self) -> None:
        self._queue: queue.PriorityQueue[_QueuedJob] = queue.PriorityQueue()
        self._lock = threading.Lock()
        self._futures: dict[str, Future[object]] = {}
        self._queued_jobs: dict[str, _QueuedJob] = {}
        self._sequence = itertools.count()
        self._closed = False
        self._worker = threading.Thread(
            target=self._run,
            name="codex-usage-io",
            daemon=True,
        )
        self._worker.start()

    def submit(
        self,
        key: str,
        priority: JobPriority,
        operation: Callable[[], ResultT],
    ) -> Future[ResultT]:
        with self._lock:
            if self._closed:
                raise RuntimeError("heavy I/O lane is closed")
            existing = self._futures.get(key)
            if existing is not None and not existing.done():
                return existing  # type: ignore[return-value]
            future: Future[object] = Future()
            self._futures[key] = future
            job = _QueuedJob(
                priority=int(priority),
                sequence=next(self._sequence),
                key=key,
                operation=operation,
                future=future,
            )
            self._queued_jobs[key] = job
            self._queue.put(job)
            return cast(Future[ResultT], future)

    def promote(self, key: str, priority: JobPriority) -> None:
        """Raise a coalesced queued job without interrupting running work."""
        with self._lock:
            current = self._queued_jobs.get(key)
            if current is None or int(priority) >= current.priority:
                return
            promoted = _QueuedJob(
                priority=int(priority),
                sequence=next(self._sequence),
                key=current.key,
                operation=current.operation,
                future=current.future,
            )
            self._queued_jobs[key] = promoted
            self._queue.put(promoted)

    def close(self, *, wait: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._queue.put(
            _QueuedJob(
                priority=_STOP_PRIORITY,
                sequence=next(self._sequence),
                key="",
                operation=None,
                future=None,
            )
        )
        if wait:
            self._worker.join()

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job.operation is None:
                self._queue.task_done()
                return
            with self._lock:
                if self._queued_jobs.get(job.key) is not job:
                    self._queue.task_done()
                    continue
                self._queued_jobs.pop(job.key, None)
            try:
                if job.future is None:
                    raise AssertionError("queued operation is missing its future")
                if not job.future.set_running_or_notify_cancel():
                    continue
                try:
                    result = job.operation()
                except BaseException as exc:
                    job.future.set_exception(exc)
                else:
                    job.future.set_result(result)
            finally:
                with self._lock:
                    if job.future is not None and self._futures.get(job.key) is job.future:
                        self._futures.pop(job.key, None)
                self._queue.task_done()
