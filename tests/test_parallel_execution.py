from __future__ import annotations

import multiprocessing
import os
import pickle
import random
import re
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from multiprocessing.context import BaseContext
from typing import ClassVar, Never

import pytest
from spawn_worker_test_support import OverlapRequest, overlap_worker

import codex_usage.parallel.execution as execution_module
from codex_usage.parallel.execution import (
    SERIAL_FALLBACK_WARNING,
    OrderedProcessMapper,
    ParallelRunReport,
    WorkerSpan,
    resolve_worker_count,
)

WORKER_CALLS: list[int] = []
COMPLETION_SEED = 0
COMPLETION_ORDERS: list[tuple[int, ...]] = []


def recording_worker(value: int) -> int:
    WORKER_CALLS.append(value)
    return value * 10


def pid_worker(value: int) -> tuple[int, int]:
    return value, os.getpid()


def value_error_worker(value: int) -> int:
    raise ValueError(f"bad worker value {value}")


def pickling_error_worker(value: int) -> int:
    raise pickle.PicklingError(f"worker {os.getpid()} rejected {value}")


def interrupt_worker(value: int) -> int:
    raise KeyboardInterrupt(value)


class StubExecutor:
    fail_on: ClassVar[int | None] = None

    def __init__(self, *, max_workers: int, mp_context: BaseContext) -> None:
        self.max_workers = max_workers
        self.mp_context = mp_context
        self.futures: list[Future[int]] = []
        self.shutdown_calls: list[tuple[bool, bool]] = []

    def submit(self, worker: Callable[[int], int], request: int) -> Future[int]:
        future: Future[int] = Future()
        if request == self.fail_on:
            future.set_exception(BrokenProcessPool(f"transport failed for {request}"))
        else:
            future.set_result(worker(request))
        self.futures.append(future)
        return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        self.shutdown_calls.append((wait, cancel_futures))


def shuffled_completed(futures: Iterable[Future[int]]) -> Iterator[Future[int]]:
    ordered = list(futures)
    random.Random(COMPLETION_SEED).shuffle(ordered)
    COMPLETION_ORDERS.append(tuple(future.result() for future in ordered))
    return iter(ordered)


def raising_executor(*args: object, **kwargs: object) -> Never:
    raise OSError("spawn unavailable")


def forbidden_executor(*args: object, **kwargs: object) -> Never:
    raise AssertionError("max_workers=1 must not create a process executor")


@pytest.fixture(autouse=True)
def reset_executor_double() -> Iterator[None]:
    global COMPLETION_SEED
    WORKER_CALLS.clear()
    COMPLETION_ORDERS.clear()
    COMPLETION_SEED = 0
    StubExecutor.fail_on = None
    yield
    WORKER_CALLS.clear()
    COMPLETION_ORDERS.clear()
    COMPLETION_SEED = 0
    StubExecutor.fail_on = None


def test_resolve_worker_count_uses_process_cpu_count(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def process_cpu_count() -> int:
        nonlocal calls
        calls += 1
        return 64

    monkeypatch.setattr(os, "process_cpu_count", process_cpu_count)
    assert resolve_worker_count(0) == 0
    assert resolve_worker_count(1) == 1
    assert resolve_worker_count(100) == 4
    assert calls == 2
    assert resolve_worker_count(100, available_cpus=2) == 2
    assert calls == 2


def test_spawn_mapper_proves_two_overlapping_child_pids() -> None:
    parent_pid = os.getpid()
    with multiprocessing.Manager() as manager:
        barrier = manager.Barrier(2)
        active = manager.Value("i", 0)
        peak = manager.Value("i", 0)
        lock = manager.Lock()
        requests = [OverlapRequest(index, barrier, active, peak, lock) for index in range(2)]
        with OrderedProcessMapper(overlap_worker, task_count=2, max_workers=2) as mapper:
            results = mapper.map_batch(requests)
        peak_value = peak.value
    report = ParallelRunReport(
        resolved_worker_count=mapper.worker_count,
        worker_spans=tuple(result.span for result in results),
        used_serial_fallback=mapper.used_serial_fallback,
        infrastructure_error=mapper.infrastructure_error,
        file_error_count=0,
    )
    assert peak_value == 2
    assert report.worker_pids == tuple(result.span.pid for result in results)
    assert parent_pid not in report.worker_pids
    assert report.max_concurrency == 2
    assert report.actually_parallel(parent_pid) is True


def test_parallel_report_rejects_overlap_within_only_one_worker_pid() -> None:
    report = ParallelRunReport(
        resolved_worker_count=2,
        worker_spans=(
            WorkerSpan(901, 0, 20),
            WorkerSpan(901, 5, 15),
            WorkerSpan(902, 21, 30),
        ),
        used_serial_fallback=False,
        infrastructure_error="",
        file_error_count=0,
    )

    assert report.worker_pids == (901, 902)
    assert report.max_concurrency == 1
    assert report.actually_parallel(parent_pid=900) is False


def test_varied_shuffled_future_completion_keeps_request_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global COMPLETION_SEED
    monkeypatch.setattr(execution_module, "ProcessPoolExecutor", StubExecutor)
    monkeypatch.setattr(execution_module, "as_completed", shuffled_completed)
    for seed in range(16):
        COMPLETION_SEED = seed
        with OrderedProcessMapper(recording_worker, task_count=4, max_workers=4) as mapper:
            assert mapper.map_batch([1, 2, 3, 4]) == [10, 20, 30, 40]
        assert mapper.used_serial_fallback is False
    assert len(set(COMPLETION_ORDERS)) >= 4


def test_max_workers_one_is_intentional_in_process_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_pid = os.getpid()
    monkeypatch.setattr(execution_module, "ProcessPoolExecutor", forbidden_executor)
    with OrderedProcessMapper(pid_worker, task_count=3, max_workers=1) as mapper:
        results = mapper.map_batch([1, 2, 3])
    assert results == [(1, parent_pid), (2, parent_pid), (3, parent_pid)]
    assert mapper.worker_count == 1
    assert mapper.used_serial_fallback is False
    assert mapper.infrastructure_error == ""


def test_constructor_oserror_falls_back_once_and_is_observable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution_module, "ProcessPoolExecutor", raising_executor)
    with pytest.warns(RuntimeWarning, match=re.escape(SERIAL_FALLBACK_WARNING)) as caught:
        with OrderedProcessMapper(recording_worker, task_count=2, max_workers=2) as mapper:
            assert mapper.map_batch([1, 2]) == [10, 20]
    assert len(caught) == 1
    assert mapper.used_serial_fallback is True
    assert mapper.infrastructure_error == "OSError: spawn unavailable"


def test_broken_pool_reruns_current_group_but_not_committed_group(monkeypatch: pytest.MonkeyPatch) -> None:
    StubExecutor.fail_on = 3
    monkeypatch.setattr(execution_module, "ProcessPoolExecutor", StubExecutor)
    with pytest.warns(RuntimeWarning, match=re.escape(SERIAL_FALLBACK_WARNING)) as caught:
        with OrderedProcessMapper(recording_worker, task_count=3, max_workers=2) as mapper:
            assert mapper.map_batch([1]) == [10]
            assert mapper.map_batch([2, 3]) == [20, 30]
    assert len(caught) == 1
    assert WORKER_CALLS == [1, 2, 2, 3]
    assert mapper.used_serial_fallback is True
    assert mapper.infrastructure_error == "BrokenProcessPool: transport failed for 3"


def test_worker_value_error_is_not_pool_fallback() -> None:
    with OrderedProcessMapper(value_error_worker, task_count=1, max_workers=1) as mapper:
        with pytest.raises(ValueError, match="bad worker value 7"):
            mapper.map_batch([7])
    assert mapper.used_serial_fallback is False
    assert mapper.infrastructure_error == ""


def test_spawn_worker_pickling_error_is_not_pool_fallback() -> None:
    parent_pid = os.getpid()
    with OrderedProcessMapper(pickling_error_worker, task_count=2, max_workers=2) as mapper:
        with pytest.raises(pickle.PicklingError, match=r"worker \d+ rejected 7") as caught:
            mapper.map_batch([7])
    worker_pid = int(str(caught.value).split()[1])
    assert worker_pid != parent_pid
    assert mapper.used_serial_fallback is False
    assert mapper.infrastructure_error == ""


def test_keyboard_interrupt_is_never_caught() -> None:
    with OrderedProcessMapper(interrupt_worker, task_count=1, max_workers=1) as mapper:
        with pytest.raises(KeyboardInterrupt):
            mapper.map_batch([7])
    assert mapper.used_serial_fallback is False


@pytest.mark.parametrize(("task_count", "max_workers"), [(-1, 1), (1, 0)])
def test_invalid_worker_counts_raise(task_count: int, max_workers: int) -> None:
    with pytest.raises(ValueError):
        resolve_worker_count(task_count, available_cpus=8, max_workers=max_workers)
