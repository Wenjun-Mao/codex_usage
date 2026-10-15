"""Blocked work yields the one I/O lane instead of retrying itself indefinitely."""
from concurrent.futures import Future
import sqlite3
from threading import Event

import pytest

from codex_usage.agent_jobs import HeavyIOLane, JobPriority
from codex_usage.agent_rebuild_models import (
    RebuildOutcome as Outcome, RebuildReason as Reason, RebuildSliceResult, checkpoint_advanced,
)
from codex_usage.agent_rebuild_queue import RebuildQueue


def result(key, outcome):
    return RebuildSliceResult(key, outcome, 1, 1 if outcome == Outcome.COMPLETE else 2, 10,
                             Reason.NO_PROGRESS if outcome == Outcome.BLOCKED else Reason.NONE)


class ControlledLane:
    def __init__(self):
        self.jobs = []

    def submit(self, _key, priority, operation):
        assert priority == JobPriority.BASELINE_REBUILD
        future = Future()
        self.jobs.append((operation, future))
        return future

    def run_one(self):
        operation, future = self.jobs.pop(0)
        try:
            future.set_result(operation())
        except BaseException as error:
            future.set_exception(error)


@pytest.mark.parametrize("failure", [None, OSError("synthetic IO"), RuntimeError("synthetic authority failure")])
def test_blocked_or_failed_source_does_not_repeat_or_starve_another_source(failure):
    lane, keys, calls = ControlledLane(), ["A", "B"], []
    evidence = {"A": "a1", "B": "b1"}

    def rebuild(key):
        calls.append(key)
        if key == "A":
            if failure is not None:
                raise failure
            return result(key, Outcome.BLOCKED)
        keys.remove(key)
        return result(key, Outcome.COMPLETE)

    queue = RebuildQueue(lane=lambda: lane, stopped=lambda: False,
        candidates=lambda: list(keys), fingerprint=evidence.get, rebuild=rebuild)
    queue.reconcile()
    lane.run_one()
    lane.run_one()
    assert calls == ["A", "B"] and lane.jobs == []
    for _ in range(3):
        queue.reconcile()
    queue.capture_completed(1, baseline=True)
    queue.reconcile()
    assert lane.jobs == []
    queue.capture_completed(1)
    queue.reconcile()
    if isinstance(failure, RuntimeError):
        assert lane.jobs == []
        evidence["A"] = "a2"
        queue.reconcile()
    assert len(lane.jobs) == 1
    lane.run_one()
    queue.capture_completed(1)
    queue.capture_completed(2, baseline=True)
    queue.reconcile()
    assert calls == ["A", "B", "A"] and lane.jobs == []


def test_progress_moves_to_tail_and_completes_without_a_new_capture():
    lane, keys, calls = ControlledLane(), ["A", "B"], []

    def rebuild(key):
        calls.append(key)
        if calls == ["A"]:
            return result(key, Outcome.PROGRESS)
        keys.remove(key)
        return result(key, Outcome.COMPLETE)

    queue = RebuildQueue(lane=lambda: lane, stopped=lambda: False,
        candidates=lambda: list(keys), fingerprint=lambda key: key, rebuild=rebuild)
    queue.reconcile()
    for _ in range(3):
        lane.run_one()
    assert calls == ["A", "B", "A"] and lane.jobs == []


def test_capture_and_ui_priority_work_run_before_a_progressing_continuation():
    lane = HeavyIOLane()
    started, release, finished = Event(), Event(), Event()
    keys, calls = ["A"], []

    def rebuild(key):
        if not started.is_set():
            started.set()
            assert release.wait(5)
            calls.append("slice1")
            return result(key, Outcome.PROGRESS)
        calls.append("slice2")
        keys.clear()
        finished.set()
        return result(key, Outcome.COMPLETE)

    queue = RebuildQueue(lane=lambda: lane, stopped=lambda: False,
        candidates=lambda: list(keys), fingerprint=lambda key: key, rebuild=rebuild)
    try:
        queue.reconcile()
        assert started.wait(5)
        lane.submit("capture", JobPriority.CAPTURE_NOW, lambda: calls.append("capture"))
        lane.submit("ui", JobPriority.STORAGE_ANALYSIS, lambda: calls.append("ui"))
        release.set()
        assert finished.wait(5)
    finally:
        release.set()
        lane.close()
    assert calls == ["slice1", "capture", "ui", "slice2"]


def test_drain_and_fact_advancement_count_but_rewinds_do_not():
    before = (10, 2, 3, '{"offset": 1}')
    assert checkpoint_advanced(before, (10, 2, 3, '{"offset": 2}'))
    assert checkpoint_advanced(before, (10, 3, 3, '{"offset": 1}'))
    assert not checkpoint_advanced(before, before)
    assert not checkpoint_advanced(before, (9, 2, 3, '{"offset": 2}'))


def test_rebuild_outcome_cannot_claim_a_partial_target_is_complete():
    with pytest.raises(ValueError, match="cover its target"):
        RebuildSliceResult("A", Outcome.COMPLETE, 1, 2, 10)


def test_retry_uses_the_capture_that_precedes_execution_not_submission():
    lane = HeavyIOLane()
    started, release = Event(), Event()
    calls, probes = [], []
    queue = RebuildQueue(lane=lambda: lane, stopped=lambda: False,
        candidates=lambda: ["A"], fingerprint=lambda key: probes.append(key) or key,
        rebuild=lambda key: calls.append(key) or result(key, Outcome.BLOCKED))

    def capture():
        started.set()
        assert release.wait(5)
        queue.capture_completed(1)

    try:
        capture_future = lane.submit("capture", JobPriority.CAPTURE_NOW, capture)
        assert started.wait(5)
        queue.reconcile()
        assert probes == []
        release.set()
        capture_future.result(timeout=5)
    finally:
        release.set()
        lane.close()
    assert calls == ["A"]


@pytest.mark.parametrize("failed_probe", [1, 2])
def test_fingerprint_failure_yields_to_other_sources_and_requires_a_new_capture(failed_probe):
    lane, keys, calls, probes = ControlledLane(), ["A", "B"], [], []

    def fingerprint(key):
        probes.append(key)
        if key == "A" and probes.count("A") == failed_probe:
            raise OSError("synthetic fingerprint failure")
        return key

    def rebuild(key):
        calls.append(key)
        if key == "B":
            keys.remove(key)
        return result(key, Outcome.COMPLETE if key == "B" else Outcome.BLOCKED)

    queue = RebuildQueue(lane=lambda: lane, stopped=lambda: False,
        candidates=lambda: keys[:], fingerprint=fingerprint, rebuild=rebuild)
    queue.reconcile()
    lane.run_one()
    lane.run_one()
    assert calls.count("B") == 1 and lane.jobs == []
    before = probes[:]
    for _ in range(3):
        queue.reconcile()
    assert probes == before
    queue.capture_completed(1)
    queue.reconcile()
    assert len(lane.jobs) == 1
    lane.run_one()
    assert calls.count("A") == failed_probe and lane.jobs == []


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED,
    sqlite3.SQLITE_BUSY_SNAPSHOT, sqlite3.SQLITE_LOCKED_SHAREDCACHE, sqlite3.SQLITE_CONSTRAINT])
def test_sqlite_retry_policy_uses_primary_error_codes(code):
    lane, keys, calls = ControlledLane(), ["A", "B"], []

    def rebuild(key):
        calls.append(key)
        if key == "A":
            error = sqlite3.OperationalError("synthetic SQLite failure")
            error.sqlite_errorcode = code
            raise error
        keys.remove(key)
        return result(key, Outcome.COMPLETE)

    queue = RebuildQueue(lane=lambda: lane, stopped=lambda: False,
        candidates=lambda: keys[:], fingerprint=lambda key: key, rebuild=rebuild)
    queue.reconcile()
    lane.run_one()
    lane.run_one()
    assert calls == ["A", "B"] and lane.jobs == []
    queue.capture_completed(1)
    queue.reconcile()
    retryable = code & 0xff in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    assert len(lane.jobs) == int(retryable)
    if retryable:
        lane.run_one()
        assert calls == ["A", "B", "A"] and lane.jobs == []
