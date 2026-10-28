"""Coalescing, capture priority, progress without new writes and joined shutdown."""
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
import threading
from time import monotonic, sleep

import pytest

from codex_usage.agent_jobs import HeavyIOLane, JobPriority
from codex_usage.agent_storage_maintenance import StorageMaintenance
from codex_usage.sqlite_activity import notify, operation
from codex_usage.sqlite_wal import CheckpointResult


def until(condition):
    deadline = monotonic() + 5
    while not condition():
        assert monotonic() < deadline
        sleep(0.002)


class ImmediateLane:
    def __init__(self):
        self.calls = 0

    def submit(self, key, priority, operation):
        self.calls += 1
        future = Future()
        future.set_result(operation())
        return future


def test_long_checkpoint_does_not_occupy_capture_lane_and_close_joins_it(tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow(path, **kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(5)
        return CheckpointResult('complete')

    lane = HeavyIOLane()
    controller = StorageMaintenance(tmp_path / 'ledger', owner=object(), lane=lane,
        capture_running=lambda: False, wakeup=lambda: None, run_checkpoint=slow)
    try:
        for _ in range(20):
            controller.request()
            controller.tick()
        assert entered.wait(5)
        assert lane.submit('capture', JobPriority.CAPTURE_NOW, lambda: 123).result(1) == 123
        assert len(calls) == 1
        with ThreadPoolExecutor(max_workers=1) as pool:
            closed = pool.submit(controller.close)
            assert not closed.done()
            release.set()
            closed.result(5)
        assert not controller.status()['running']
        assert datetime.fromisoformat(controller.status()['last_result']['completed_at']).tzinfo is not None
    finally:
        release.set()
        controller.close()
        lane.close()


def test_partial_backlog_retries_without_new_writes_and_reader_release_wakes_it(tmp_path):
    clock = [0.0]
    results = iter(['partial', 'partial', 'reclaimed'])
    lane = ImmediateLane()
    controller = StorageMaintenance(tmp_path / 'ledger', owner=object(), lane=lane,
        capture_running=lambda: False, wakeup=lambda: None, clock=lambda: clock[0],
        run_checkpoint=lambda *_, **__: CheckpointResult(next(results)))
    try:
        controller.tick()
        until(lambda: not controller.status()['running'])
        assert controller.status()['pending']
        controller.tick()
        assert lane.calls == 1
        clock[0] = 1.0
        controller.tick()
        until(lambda: not controller.status()['running'])
        assert lane.calls == 2
        notify(controller.path, 'reader_release')
        controller.tick()
        until(lambda: not controller.status()['running'])
        assert lane.calls == 3 and not controller.status()['pending']
    finally:
        controller.close()


def test_write_arriving_during_checkpoint_is_not_lost(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def run(*_, **__):
        entered.set()
        assert release.wait(5)
        return CheckpointResult('complete')

    controller = StorageMaintenance(tmp_path / 'ledger', owner=object(), lane=ImmediateLane(),
        capture_running=lambda: False, wakeup=lambda: None, run_checkpoint=run)
    try:
        controller.tick()
        assert entered.wait(5)
        notify(controller.path, 'write')
        release.set()
        until(lambda: not controller.status()['running'])
        assert controller.status()['pending']
    finally:
        release.set()
        controller.close()


def test_capture_takes_priority_and_runtime_mismatch_never_activates(tmp_path, monkeypatch):
    lane = ImmediateLane()
    capture = [True]
    controller = StorageMaintenance(tmp_path / 'ledger', owner=object(), lane=lane,
        capture_running=lambda: capture[0], wakeup=lambda: None)
    try:
        controller.tick()
        assert lane.calls == 0
    finally:
        controller.close()

    def unavailable():
        raise RuntimeError('older engine')

    monkeypatch.setattr('codex_usage.agent_storage_maintenance.require_release_runtime', unavailable)
    replacement = StorageMaintenance(tmp_path / 'ledger', owner=object(), lane=lane,
        capture_running=lambda: False, wakeup=lambda: None)
    try:
        replacement.tick()
        assert lane.calls == 0 and replacement.status()['runtime_error'] == 'older engine'
    finally:
        replacement.close()


def test_two_ledgers_have_independent_owners_and_duplicate_owner_is_rejected(tmp_path):
    controllers = [StorageMaintenance(tmp_path / name, owner=object(), lane=ImmediateLane(),
        capture_running=lambda: False, wakeup=lambda: None) for name in ('a', 'b')]
    try:
        with pytest.raises(RuntimeError, match='already has'):
            StorageMaintenance(tmp_path / 'a', owner=object(), lane=ImmediateLane(),
                               capture_running=lambda: False, wakeup=lambda: None)
    finally:
        for controller in controllers:
            controller.close()


def test_reader_release_cannot_strand_a_coalesced_unfinished_dispatch(tmp_path):
    class DelayedLane:
        def __init__(self):
            self.future = None
            self.operation = None
            self.calls = 0

        def submit(self, key, priority, callback):
            if self.future is None or self.future.done():
                self.calls += 1
                self.future = Future()
                self.operation = callback
            return self.future

    lane = DelayedLane()
    controller = StorageMaintenance(tmp_path / 'ledger', owner=object(), lane=lane,
        capture_running=lambda: False, wakeup=lambda: None,
        run_checkpoint=lambda *_, **__: CheckpointResult('reclaimed'))
    try:
        controller.tick()
        with operation(controller.path, read_only=True):
            lane.operation()
        # The lane has returned from dispatch, but its shared future is not done.
        controller.tick()
        assert lane.calls == 1
        lane.future.set_result(None)
        controller.tick()
        assert lane.calls == 2, 'maintenance was stranded behind the old coalesced future'
        lane.operation()
        lane.future.set_result(None)
        until(lambda: not controller.status()['pending'])
    finally:
        controller.close()
