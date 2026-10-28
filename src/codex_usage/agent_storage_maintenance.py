"""Coalesce idle checkpoint work without occupying the agent's capture lane."""
from pathlib import Path
from datetime import UTC, datetime
import threading
import time

from codex_usage.agent_jobs import JobPriority
from codex_usage import sqlite_activity
from codex_usage.sqlite_runtime import require_release_runtime
from codex_usage.sqlite_wal import checkpoint


class StorageMaintenance:
    def __init__(self, path, *, owner, lane, capture_running, wakeup, clock=time.monotonic,
                 run_checkpoint=checkpoint):
        self.path = Path(path).resolve()
        self.owner, self.lane = owner, lane
        self.capture_running, self.wakeup, self.clock = capture_running, wakeup, clock
        self.run_checkpoint = run_checkpoint
        self._lock = threading.Lock()
        self._closed = False
        self._pending = True
        # A fenced startup attempt also recovers reclaim lost at process exit.
        self._reclaim = True
        self._generation = 0
        self._next_attempt = 0.0
        self._backoff = 1.0
        self._worker = None
        self._queued = False
        self._last = None
        self._runtime = None
        try:
            runtime = require_release_runtime()
            self._runtime = {key: runtime[key] for key in ('version', 'source_id')}
            self._runtime_error = None
        except RuntimeError as error:
            self._runtime_error = str(error)
        self._unsubscribe = sqlite_activity.subscribe(self.path, self._event)

    def _event(self, event):
        with self._lock:
            if self._closed:
                return
            if event in {"write", "reclaim"}:
                self._pending = True
                self._generation += 1
            if event == "reclaim":
                self._reclaim = True
            if self._pending:
                self._next_attempt = 0.0
        self.wakeup()

    def request(self, *, reclaim=False):
        self._event("reclaim" if reclaim else "write")

    def tick(self, *, readers=()):
        with self._lock:
            if (self._closed or self._runtime_error or not self._pending or self._worker is not None or self._queued
                    or self.clock() < self._next_attempt):
                return
        if self.capture_running() or not sqlite_activity.idle(self.path, readers=readers):
            return
        with self._lock:
            if self._closed or self._worker is not None or self._queued:
                return
            self._queued = True
        try:
            future = self.lane.submit("wal-maintenance", JobPriority.MAINTENANCE,
                                      lambda: self._dispatch(readers))
            future.add_done_callback(self._dispatched)
        except BaseException:
            with self._lock:
                self._queued = False
            raise

    def _dispatched(self, _future):
        # A coalesced lane future can outlive its callback's return.
        with self._lock:
            self._queued = False
        self.wakeup()

    def _dispatch(self, readers=()):
        with self._lock:
            if (self._closed or not self._pending or self._worker is not None
                    or self.clock() < self._next_attempt):
                return
            if self.capture_running() or not sqlite_activity.idle(self.path, readers=readers):
                return
            worker = threading.Thread(target=self._run, args=(self._generation, self._reclaim, readers),
                                      name="codex-usage-wal", daemon=True)
            self._worker = worker
            worker.start()

    def _run(self, generation, reclaim, readers=()):
        try:
            options = dict(readers=readers) if readers else {}
            result = self.run_checkpoint(self.path, owner=self.owner, reclaim=reclaim, **options).to_dict()
        except Exception as error:
            result = {"outcome": "error", "error_type": type(error).__name__}
        result['completed_at'] = datetime.now(UTC).isoformat()
        with self._lock:
            self._last = result
            complete = result["outcome"] in {"absent", "not_wal", "reclaimed"} or (
                result["outcome"] == "complete" and not reclaim)
            if generation == self._generation and complete:
                self._pending = self._reclaim = False
                self._backoff = 1.0
            else:
                self._next_attempt = self.clock() + self._backoff
                self._backoff = min(60.0, self._backoff * 2)
            self._worker = None
        self.wakeup()

    def status(self):
        with self._lock:
            return {"pending": self._pending, "running": self._worker is not None,
                    "runtime": self._runtime,
                    "reclaim_pending": self._reclaim, "runtime_error": self._runtime_error,
                    "last_result": dict(self._last) if self._last is not None else None}

    def close(self):
        with self._lock:
            self._closed = True
            worker = self._worker
        self._unsubscribe()
        if worker is not None:
            worker.join()
