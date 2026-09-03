from __future__ import annotations

import os
import threading
import time
from collections import deque
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path
from typing import Callable

from filelock import FileLock, Timeout

from codex_usage.agent_capture import (
    CaptureResult,
    capture_once,
    recover_interrupted_capture_runs,
    session_dirs_for_home,
)
from codex_usage.agent_features import AgentFeatures
from codex_usage.agent_jobs import HeavyIOLane, JobPriority
from codex_usage.agent_operations import OperationRegistry
from codex_usage.agent_paths import (
    agent_data_dir,
    agent_descriptor_path,
    agent_lock_path,
    ledger_database_path,
)
from codex_usage.agent_private_files import (
    ensure_private_directory,
    ensure_private_file,
)
from codex_usage.agent_protocol import AgentDescriptor, write_agent_descriptor
from codex_usage.agent_reports import RenderedLedgerReport
from codex_usage.agent_rebuild import (
    RebuildSliceResult,
    pending_incremental_source_count,
    rebuild_stale_source_slice,
    stale_source_keys,
)
from codex_usage.agent_schedule import CaptureSchedule
from codex_usage.agent_settings import (
    AgentSettings,
    load_agent_settings,
    save_agent_settings,
)
from codex_usage.agent_watcher import DirtyPathSet, SessionWatcher
from codex_usage.ledger_queries import (
    load_ledger_status,
)
from codex_usage.ledger_schema import open_ledger


class AgentAlreadyRunningError(RuntimeError):
    pass


class CodexUsageAgent:
    def __init__(
        self,
        *,
        settings_file: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings_file = settings_file
        self.settings = load_agent_settings(settings_file)
        self.codex_home = Path(self.settings.codex_home)
        self._clock = clock
        self._wall_clock = wall_clock
        self._stop = threading.Event()
        self._shutdown_requested = threading.Event()
        self._schedule_wakeup = threading.Event()
        self._schedule = CaptureSchedule(self.settings.capture_interval_minutes)
        self._lane = HeavyIOLane()
        self._operations = OperationRegistry(self._lane)
        self._features = AgentFeatures(
            self.codex_home,
            self._lane,
            self._operations,
            settings=lambda: self.settings,
            on_import=self.request_catch_up,
        )
        self._dirty_paths = DirtyPathSet()
        self._watcher: SessionWatcher | None = None
        self._scheduler_thread: threading.Thread | None = None
        self._server = None
        self._descriptor: AgentDescriptor | None = None
        self._lock = FileLock(str(agent_lock_path(self.codex_home)))
        self._capture_lock = threading.Lock()
        self._capture_future: Future[CaptureResult] | None = None
        self._rebuild_lock = threading.Lock()
        self._rebuild_queue: deque[str] = deque()
        self._rebuild_future: Future[RebuildSliceResult] | None = None

    @property
    def descriptor(self) -> AgentDescriptor:
        if self._descriptor is None:
            raise RuntimeError("agent has not started")
        return self._descriptor

    def start(self, *, port: int = 0) -> AgentDescriptor:
        ensure_private_directory(agent_data_dir(self.codex_home))
        try:
            self._lock.acquire(timeout=0)
        except Timeout as exc:
            self._lane.close(wait=True)
            raise AgentAlreadyRunningError(
                f"Codex Usage agent is already running for {self.codex_home}"
            ) from exc
        try:
            ensure_private_file(agent_lock_path(self.codex_home))
            ledger_path = ledger_database_path(self.codex_home)
            with open_ledger(ledger_path):
                pass
            recover_interrupted_capture_runs(ledger_path)
            roots = session_dirs_for_home(self.codex_home)
            self._watcher = SessionWatcher(
                roots,
                self._dirty_paths,
                on_overflow=self.request_catch_up,
            )
            self._watcher.start()
            from codex_usage.agent_api import AgentHttpServer

            provisional = AgentDescriptor.create(
                port=port or 1, codex_home=self.codex_home
            )
            self._server = AgentHttpServer(self, token=provisional.token, port=port)
            self._server.start()
            self._descriptor = replace(provisional, port=self._server.port)
            write_agent_descriptor(
                agent_descriptor_path(self.codex_home), self._descriptor
            )
            self._schedule.start(self._clock())
            self._submit_capture("startup", JobPriority.SCHEDULED_CAPTURE)
            self._scheduler_thread = threading.Thread(
                target=self._scheduler_loop,
                name="codex-usage-scheduler",
                daemon=True,
            )
            self._scheduler_thread.start()
            return self._descriptor
        except Exception:
            self.stop()
            raise

    def run_forever(self) -> None:
        self._shutdown_requested.wait()

    def request_shutdown(self) -> None:
        self._shutdown_requested.set()

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self._schedule_wakeup.set()
        if self._server is not None:
            self._server.stop()
        if self._watcher is not None:
            self._watcher.stop()
        if self._scheduler_thread is not None:
            self._scheduler_thread.join(timeout=5)
        self._operations.cancel_all()
        self._lane.close(wait=True)
        descriptor_path = agent_descriptor_path(self.codex_home)
        try:
            if self._descriptor is not None and descriptor_path.is_file():
                current = descriptor_path.read_text(encoding="utf-8")
                if self._descriptor.token in current:
                    descriptor_path.unlink(missing_ok=True)
        finally:
            if self._lock.is_locked:
                self._lock.release()

    def capture_now(self) -> Future[CaptureResult]:
        future = self._submit_capture("manual", JobPriority.CAPTURE_NOW)
        future.add_done_callback(self._manual_capture_completed)
        return future

    def request_catch_up(self) -> None:
        self._submit_capture("catch-up", JobPriority.SCHEDULED_CAPTURE)
        self._schedule_wakeup.set()

    def report(
        self,
        *,
        range_name: str,
        project_keys: list[str],
        theme: str,
    ) -> RenderedLedgerReport:
        return self._features.report(
            range_name=range_name,
            project_keys=project_keys,
            theme=theme,
        )

    def status_payload(self) -> dict[str, object]:
        status = load_ledger_status(ledger_database_path(self.codex_home)).to_dict()
        status.update(
            {
                "agent_pid": os.getpid(),
                "api_version": self.descriptor.api_version,
                "codex_home": str(self.codex_home),
                "capture_running": self._capture_is_running(),
                "next_capture_seconds": self._schedule.seconds_until_due(
                    self._clock()
                ),
                "dirty_paths": len(self._dirty_paths.snapshot()),
            }
        )
        return status

    def projects(self) -> list[dict[str, object]]:
        return self._features.projects()

    def tasks(self, project_key: str | None = None) -> list[dict[str, object]]:
        return self._features.tasks(project_key)

    def transitions(self) -> list[dict[str, object]]:
        return self._features.transitions()

    def storage_snapshot(self, project_keys: list[str]) -> dict[str, object]:
        return self._features.storage_snapshot(project_keys)

    def start_storage_analysis(self, tree_id: str) -> dict[str, object]:
        return self._features.start_storage_analysis(tree_id)

    def operation_status(self, operation_id: str) -> dict[str, object]:
        return self._features.operation_status(operation_id)

    def cancel_operation(self, operation_id: str) -> dict[str, object]:
        return self._features.cancel_operation(operation_id)

    def transfer_inventory(self, payload: dict[str, object]) -> dict[str, object]:
        return self._features.transfer_inventory(payload)

    def execute_transfer(self, payload: dict[str, object]) -> dict[str, object]:
        return self._features.execute_transfer(payload)

    def service_status(self) -> dict[str, object]:
        return self._features.service_status()

    def migration_plan(self) -> dict[str, object]:
        return self._features.migration_plan()

    def migrate_legacy(self, precedence: dict[str, str]) -> dict[str, object]:
        return self._features.migrate_legacy(precedence)

    def update_settings(self, changes: dict[str, object]) -> AgentSettings:
        requested_home = str(changes.get("codex_home", self.settings.codex_home))
        if Path(requested_home).expanduser().resolve() != self.codex_home:
            raise ValueError("changing CODEX_HOME requires an agent restart")
        interval_value = changes.get(
            "capture_interval_minutes", self.settings.capture_interval_minutes
        )
        interval = None if interval_value is None else int(interval_value)
        updated = replace(
            self.settings,
            capture_interval_minutes=interval,
            background_capture=_required_bool(
                changes.get("background_capture", self.settings.background_capture)
            ),
            daily_update_checks=_required_bool(
                changes.get(
                    "daily_update_checks", self.settings.daily_update_checks
                )
            ),
            onboarding_complete=_required_bool(
                changes.get(
                    "onboarding_complete", self.settings.onboarding_complete
                )
            ),
            timezone=_optional_text(changes.get("timezone", self.settings.timezone)),
            theme=str(changes.get("theme", self.settings.theme)),
            auto_project_transitions=_required_bool(
                changes.get(
                    "auto_project_transitions",
                    self.settings.auto_project_transitions,
                )
            ),
            transfer_folder=str(
                changes.get("transfer_folder", self.settings.transfer_folder)
            ),
        ).validated()
        save_agent_settings(updated, self.settings_file)
        self.settings = updated
        self._schedule.update_interval(interval, self._clock())
        self._schedule_wakeup.set()
        return updated

    def _scheduler_loop(self) -> None:
        last_wall_tick = self._wall_clock()
        while not self._stop.is_set():
            now = self._clock()
            wall_now = self._wall_clock()
            last_wall_tick = self._scheduler_step(
                now=now,
                wall_now=wall_now,
                last_wall_tick=last_wall_tick,
            )
            delay = self._schedule.seconds_until_due(now)
            timeout = 1.0 if delay is None else max(0.1, min(1.0, delay))
            self._schedule_wakeup.wait(timeout)
            self._schedule_wakeup.clear()

    def _scheduler_step(
        self,
        *,
        now: float,
        wall_now: float,
        last_wall_tick: float,
    ) -> float:
        if wall_now - last_wall_tick > 60:
            self._submit_capture("wake-catch-up", JobPriority.SCHEDULED_CAPTURE)
        if self._watcher is not None and not self._watcher.is_alive():
            if self._watcher.recover():
                self._submit_capture(
                    "watcher-recovery", JobPriority.SCHEDULED_CAPTURE
                )
        if self._schedule.is_due(now) and not self._capture_is_running():
            self._submit_capture("scheduled", JobPriority.SCHEDULED_CAPTURE)
        return wall_now

    def _submit_capture(
        self,
        request_kind: str,
        priority: JobPriority,
    ) -> Future[CaptureResult]:
        with self._capture_lock:
            current = self._capture_future
            if current is not None and not current.done():
                self._lane.promote("capture", priority)
                return current
            # Clear only events known before this inventory. Watcher events arriving
            # during the capture remain visible for the next reconciliation.
            preferred_paths = self._dirty_paths.drain()
            future = self._lane.submit(
                "capture",
                priority,
                lambda: capture_once(
                    self.codex_home,
                    request_kind=request_kind,
                    auto_transitions=self.settings.auto_project_transitions,
                    preferred_paths=preferred_paths,
                ),
            )
            self._capture_future = future
        future.add_done_callback(self._capture_completed)
        return future

    def _capture_completed(self, future: Future[CaptureResult]) -> None:
        try:
            result = future.result()
        except BaseException:
            return
        if self._stop.is_set():
            return
        if result.outcome == "success":
            if result.request_kind != "baseline":
                self._schedule.mark_success(self._clock())
            ledger_path = ledger_database_path(self.codex_home)
            if pending_incremental_source_count(ledger_path):
                self._submit_capture("baseline", JobPriority.BASELINE_REBUILD)
            else:
                self._queue_stale_rebuilds()
        else:
            self._schedule.request_catch_up(self._clock() + 60)
        self._schedule_wakeup.set()

    def _manual_capture_completed(self, future: Future[CaptureResult]) -> None:
        try:
            result = future.result()
        except BaseException:
            return
        if result.outcome == "success":
            self._schedule.mark_success(self._clock())
            self._schedule_wakeup.set()

    def _queue_stale_rebuilds(self) -> None:
        keys = stale_source_keys(ledger_database_path(self.codex_home))
        with self._rebuild_lock:
            active = set(keys)
            retained = [key for key in self._rebuild_queue if key in active]
            queued = set(retained)
            retained.extend(key for key in keys if key not in queued)
            self._rebuild_queue = deque(retained)
        self._submit_next_rebuild_slice()

    def _submit_next_rebuild_slice(self) -> None:
        with self._rebuild_lock:
            if self._rebuild_future is not None and not self._rebuild_future.done():
                return
            if not self._rebuild_queue:
                return
            source_key = self._rebuild_queue.popleft()
            future = self._lane.submit(
                "baseline-rebuild",
                JobPriority.BASELINE_REBUILD,
                lambda: rebuild_stale_source_slice(
                    self.codex_home,
                    source_key,
                    max_bytes=64 * 1024 * 1024,
                ),
            )
            self._rebuild_future = future
        future.add_done_callback(self._rebuild_completed)

    def _rebuild_completed(
        self,
        future: Future[RebuildSliceResult],
    ) -> None:
        try:
            result = future.result()
        except BaseException:
            return
        if self._stop.is_set():
            return
        if not result.complete:
            with self._rebuild_lock:
                self._rebuild_queue.append(result.source_key)
        self._queue_stale_rebuilds()

    def _capture_is_running(self) -> bool:
        with self._capture_lock:
            return self._capture_future is not None and not self._capture_future.done()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("boolean settings must be true or false")
    return value
