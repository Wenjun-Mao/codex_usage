from __future__ import annotations

import threading
import time

from codex_usage.agent_jobs import HeavyIOLane, JobPriority
from codex_usage.agent_operations import OperationRegistry
from codex_usage.storage_analysis import StorageAnalysisCancelled


def test_managed_operation_reports_progress_and_result() -> None:
    lane = HeavyIOLane()
    registry = OperationRegistry(lane)
    try:
        operation = registry.start(
            kind="storage-analysis",
            priority=JobPriority.STORAGE_ANALYSIS,
            operation=lambda progress, _cancelled: _successful_operation(progress),
        )
        result = _wait_for_terminal(registry, str(operation["operation_id"]))
        assert result["state"] == "completed"
        assert result["progress"] == {"completed_files": 1, "total_files": 1}
        assert result["result"] == {"files_analyzed": 1}
    finally:
        lane.close()


def test_queued_managed_operation_can_be_cancelled_without_running() -> None:
    lane = HeavyIOLane()
    registry = OperationRegistry(lane)
    blocker = threading.Event()
    started = threading.Event()
    lane.submit(
        "blocker",
        JobPriority.TASK_TRANSFER,
        lambda: _blocking_operation(started, blocker),
    )
    assert started.wait(1)
    ran = False

    def queued(_progress, _cancelled) -> dict[str, object]:
        nonlocal ran
        ran = True
        return {}

    try:
        operation = registry.start(
            kind="storage-analysis",
            priority=JobPriority.STORAGE_ANALYSIS,
            operation=queued,
        )
        result = registry.cancel(str(operation["operation_id"]))
        assert result["state"] == "cancelled"
        blocker.set()
        time.sleep(0.05)
        assert ran is False
    finally:
        blocker.set()
        lane.close()


def test_running_cancellation_never_publishes_result() -> None:
    lane = HeavyIOLane()
    registry = OperationRegistry(lane)
    started = threading.Event()

    def cancellable(_progress, cancelled) -> dict[str, object]:
        started.set()
        while not cancelled():
            time.sleep(0.005)
        raise StorageAnalysisCancelled("cancelled")

    try:
        operation = registry.start(
            kind="storage-analysis",
            priority=JobPriority.STORAGE_ANALYSIS,
            operation=cancellable,
        )
        assert started.wait(1)
        registry.cancel(str(operation["operation_id"]))
        result = _wait_for_terminal(registry, str(operation["operation_id"]))
        assert result["state"] == "cancelled"
        assert result["result"] == {}
    finally:
        lane.close()


def test_cancel_all_stops_running_and_queued_managed_operations() -> None:
    lane = HeavyIOLane()
    registry = OperationRegistry(lane)
    started = threading.Event()
    ran_queued = False

    def running(_progress, cancelled) -> dict[str, object]:
        started.set()
        while not cancelled():
            time.sleep(0.005)
        raise StorageAnalysisCancelled("cancelled")

    def queued(_progress, _cancelled) -> dict[str, object]:
        nonlocal ran_queued
        ran_queued = True
        return {}

    first = registry.start(
        kind="storage-analysis",
        priority=JobPriority.STORAGE_ANALYSIS,
        operation=running,
    )
    assert started.wait(1)
    second = registry.start(
        kind="storage-analysis",
        priority=JobPriority.STORAGE_ANALYSIS,
        operation=queued,
    )

    registry.cancel_all()
    first_result = _wait_for_terminal(registry, str(first["operation_id"]))
    second_result = _wait_for_terminal(registry, str(second["operation_id"]))
    lane.close()

    assert first_result["state"] == "cancelled"
    assert second_result["state"] == "cancelled"
    assert ran_queued is False


def test_lane_close_drains_queued_jobs_before_stopping() -> None:
    lane = HeavyIOLane()
    blocker = threading.Event()
    started = threading.Event()
    completed: list[str] = []
    lane.submit(
        "blocker",
        JobPriority.CAPTURE_NOW,
        lambda: _blocking_then_record(started, blocker, completed),
    )
    assert started.wait(1)
    queued = lane.submit(
        "queued",
        JobPriority.BASELINE_REBUILD,
        lambda: completed.append("queued"),
    )

    closer = threading.Thread(target=lane.close)
    closer.start()
    blocker.set()
    closer.join(2)

    assert not closer.is_alive()
    assert queued.result(timeout=1) is None
    assert completed == ["blocker", "queued"]


def test_lane_can_promote_a_coalesced_capture_ahead_of_lower_priority_work() -> None:
    lane = HeavyIOLane()
    blocker = threading.Event()
    started = threading.Event()
    completed: list[str] = []
    lane.submit(
        "blocker",
        JobPriority.TASK_TRANSFER,
        lambda: _blocking_then_record(started, blocker, completed),
    )
    assert started.wait(1)
    analysis = lane.submit(
        "analysis",
        JobPriority.STORAGE_ANALYSIS,
        lambda: completed.append("analysis"),
    )
    capture = lane.submit(
        "capture",
        JobPriority.BASELINE_REBUILD,
        lambda: completed.append("capture"),
    )

    lane.promote("capture", JobPriority.CAPTURE_NOW)
    blocker.set()
    capture.result(timeout=1)
    analysis.result(timeout=1)
    lane.close()

    assert completed == ["blocker", "capture", "analysis"]


def _successful_operation(progress) -> dict[str, object]:
    progress({"completed_files": 1, "total_files": 1})
    return {"files_analyzed": 1}


def _blocking_operation(started: threading.Event, blocker: threading.Event) -> None:
    started.set()
    blocker.wait(2)


def _blocking_then_record(
    started: threading.Event,
    blocker: threading.Event,
    completed: list[str],
) -> None:
    started.set()
    blocker.wait(2)
    completed.append("blocker")


def _wait_for_terminal(
    registry: OperationRegistry,
    operation_id: str,
) -> dict[str, object]:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        payload = registry.get(operation_id)
        if payload["state"] in {"completed", "failed", "cancelled"}:
            return payload
        time.sleep(0.005)
    raise AssertionError("operation did not finish")
