"""Fair rebuild scheduling with capture-scoped retries, on the existing I/O lane."""
from collections import deque
from dataclasses import dataclass
import sqlite3
import threading

from codex_usage.agent_jobs import JobPriority
from codex_usage.agent_rebuild_authority import StagedCaptureUnavailableError
from codex_usage.agent_rebuild_models import RebuildOutcome


@dataclass(frozen=True, slots=True)
class _Suppressed:
    evidence: str | None
    capture: int
    retryable: bool
    probe_failed: bool = False


@dataclass(slots=True)
class _Attempt:
    capture: int
    evidence: str | None = None
    evidence_known: bool = False


def _recoverable(error):
    code = getattr(error, "sqlite_errorcode", None)
    return isinstance(error, (OSError, StagedCaptureUnavailableError)) or (
        isinstance(error, sqlite3.Error) and isinstance(code, int)
        and code & 0xff in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED))


class RebuildQueue:
    def __init__(self, *, lane, stopped, candidates, fingerprint, rebuild):
        self._lane = lane
        self._stopped = stopped
        self._candidates = candidates
        self._fingerprint = fingerprint
        self._rebuild = rebuild
        self._lock = threading.Lock()
        self._queue = deque()
        self._active = None
        self._future = None
        self._suppressed = {}
        self._capture = 0
        self._last_capture_run = None

    def capture_completed(self, run_id, *, baseline=False):
        if baseline:
            return
        with self._lock:
            if run_id != self._last_capture_run:
                self._last_capture_run = run_id
                self._capture += 1

    def reconcile(self):
        if self._stopped():
            return
        keys = self._candidates()
        with self._lock:
            active = set(keys)
            self._suppressed = {key: value for key, value in self._suppressed.items() if key in active}
            eligible = []
            for key in keys:
                previous = self._suppressed.get(key)
                if previous is not None:
                    if not self._eligible(key, previous):
                        continue
                    self._suppressed.pop(key)
                if key != self._active:
                    eligible.append(key)
            retained = [key for key in self._queue if key in eligible]
            self._queue = deque(retained + [key for key in eligible if key not in retained])
        self._submit_next()

    def _eligible(self, key, previous):
        if previous.retryable and previous.capture != self._capture:
            return True
        if previous.probe_failed and previous.capture == self._capture:
            return False
        try:
            return previous.evidence != self._fingerprint(key)
        except BaseException:
            self._suppressed[key] = _Suppressed(
                previous.evidence, self._capture, previous.retryable, probe_failed=True)
            return False

    def _submit_next(self):
        with self._lock:
            if self._active is not None or not self._queue or self._stopped():
                return
            key = self._queue.popleft()
            attempt = _Attempt(self._capture)
            self._active = key
            try:
                future = self._lane().submit("baseline-rebuild", JobPriority.BASELINE_REBUILD,
                                             lambda: self._run(key, attempt))
            except BaseException:
                self._active = None
                raise
            self._future = future
        # An already-completed test/host Future can call back synchronously.
        future.add_done_callback(lambda completed: self._completed(key, attempt, completed))

    def _run(self, key, attempt):
        with self._lock:
            attempt.capture = self._capture
        attempt.evidence = self._fingerprint(key)
        attempt.evidence_known = True
        return self._rebuild(key)

    def _completed(self, key, attempt, future):
        try:
            result = future.result()
            if result.source_key != key:
                raise RuntimeError("rebuild result belongs to a different source")
            outcome = result.outcome
            retryable = outcome == RebuildOutcome.BLOCKED
        except BaseException as error:
            outcome = RebuildOutcome.FAILED
            retryable = _recoverable(error)
        with self._lock:
            if self._future is not future or self._active != key:
                return
            self._active = self._future = None
            if outcome in (RebuildOutcome.BLOCKED, RebuildOutcome.FAILED):
                self._suppressed[key] = _Suppressed(attempt.evidence, attempt.capture, retryable,
                                                   probe_failed=not attempt.evidence_known)
            elif outcome == RebuildOutcome.PROGRESS:
                self._queue.append(key)
        self.reconcile()
