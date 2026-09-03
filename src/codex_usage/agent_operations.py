from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable, Literal

from codex_usage.agent_jobs import HeavyIOLane, JobPriority
from codex_usage.storage_analysis import StorageAnalysisCancelled


OperationState = Literal["queued", "running", "completed", "failed", "cancelled"]


@dataclass(slots=True)
class ManagedOperation:
    operation_id: str
    kind: str
    state: OperationState = "queued"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str = ""
    progress: dict[str, object] = field(default_factory=dict)
    result: dict[str, object] = field(default_factory=dict)
    error: str = ""
    cancellation: threading.Event = field(default_factory=threading.Event)
    future: Future[dict[str, object]] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "state": self.state,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "progress": dict(self.progress),
            "result": dict(self.result),
            "error": self.error,
        }


class OperationRegistry:
    def __init__(self, lane: HeavyIOLane) -> None:
        self._lane = lane
        self._lock = threading.Lock()
        self._operations: dict[str, ManagedOperation] = {}

    def start(
        self,
        *,
        kind: str,
        priority: JobPriority,
        operation: Callable[
            [Callable[[dict[str, object]], None], Callable[[], bool]],
            dict[str, object],
        ],
    ) -> dict[str, object]:
        operation_id = str(uuid.uuid4())
        managed = ManagedOperation(operation_id=operation_id, kind=kind)
        with self._lock:
            self._operations[operation_id] = managed

        def run() -> dict[str, object]:
            self._set_state(managed, "running")
            if managed.cancellation.is_set():
                raise StorageAnalysisCancelled("Task Storage analysis was cancelled")
            return operation(
                lambda progress: self._set_progress(managed, progress),
                managed.cancellation.is_set,
            )

        future = self._lane.submit(
            f"managed-operation:{operation_id}",
            priority,
            run,
        )
        managed.future = future
        future.add_done_callback(lambda completed: self._complete(managed, completed))
        return managed.to_dict()

    def get(self, operation_id: str) -> dict[str, object]:
        with self._lock:
            managed = self._operations.get(operation_id)
            if managed is None:
                raise KeyError(f"operation not found: {operation_id}")
            return managed.to_dict()

    def cancel(self, operation_id: str) -> dict[str, object]:
        with self._lock:
            managed = self._operations.get(operation_id)
            if managed is None:
                raise KeyError(f"operation not found: {operation_id}")
            if managed.state in {"completed", "failed", "cancelled"}:
                return managed.to_dict()
            managed.cancellation.set()
            future = managed.future
        cancelled = future is not None and future.cancel()
        with self._lock:
            if cancelled:
                managed.state = "cancelled"
                managed.completed_at = datetime.now(UTC).isoformat()
            return managed.to_dict()

    def cancel_all(self) -> None:
        """Request cancellation for every nonterminal managed operation."""
        with self._lock:
            operation_ids = [
                operation_id
                for operation_id, managed in self._operations.items()
                if managed.state not in {"completed", "failed", "cancelled"}
            ]
        for operation_id in operation_ids:
            self.cancel(operation_id)

    def _set_state(self, managed: ManagedOperation, state: OperationState) -> None:
        with self._lock:
            managed.state = state

    def _set_progress(
        self,
        managed: ManagedOperation,
        progress: dict[str, object],
    ) -> None:
        with self._lock:
            managed.progress = dict(progress)

    def _complete(
        self,
        managed: ManagedOperation,
        future: Future[dict[str, object]],
    ) -> None:
        with self._lock:
            managed.completed_at = datetime.now(UTC).isoformat()
            if future.cancelled() or managed.cancellation.is_set():
                managed.state = "cancelled"
                return
            try:
                managed.result = future.result()
            except StorageAnalysisCancelled:
                managed.state = "cancelled"
            except Exception as exc:
                managed.state = "failed"
                managed.error = f"{type(exc).__name__}: {exc}"
            else:
                managed.state = "completed"
