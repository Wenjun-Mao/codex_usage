from __future__ import annotations

import json
import time
from concurrent.futures import Future
from pathlib import Path

import pytest

from codex_usage.agent_capture import CaptureResult
from codex_usage.agent_jobs import JobPriority
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_runtime import CodexUsageAgent
from codex_usage.ledger_queries import load_ledger_status
from codex_usage.ledger_schema import open_ledger
from codex_usage.session_cache_models import CacheStats


def test_manual_only_agent_performs_one_startup_capture(tmp_path: Path) -> None:
    home = _codex_home(tmp_path)
    settings = _settings_file(tmp_path, home, interval=None)
    agent = CodexUsageAgent(settings_file=settings)
    try:
        agent.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = agent.status_payload()
            if status["last_capture_outcome"] == "success":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("startup capture did not complete")

        assert status["next_capture_seconds"] is None
        assert status["last_capture_outcome"] == "success"
    finally:
        agent.stop()


def test_scheduler_requests_catch_up_after_suspend_and_watcher_recovery(
    tmp_path: Path,
) -> None:
    home = _codex_home(tmp_path)
    agent = CodexUsageAgent(settings_file=_settings_file(tmp_path, home, interval=None))
    requests: list[tuple[str, JobPriority]] = []

    class FailedWatcher:
        def is_alive(self) -> bool:
            return False

        def recover(self) -> bool:
            return True

    agent._watcher = FailedWatcher()  # type: ignore[assignment]
    agent._submit_capture = (  # type: ignore[method-assign]
        lambda kind, priority: requests.append((kind, priority))
    )
    try:
        assert agent._scheduler_step(
            now=20.0,
            wall_now=200.0,
            last_wall_tick=100.0,
        ) == 200.0
        assert requests == [
            ("wake-catch-up", JobPriority.SCHEDULED_CAPTURE),
            ("watcher-recovery", JobPriority.SCHEDULED_CAPTURE),
        ]
    finally:
        agent._lane.close()


def test_manual_capture_resets_countdown_when_it_coalesces_with_scheduled_work(
    tmp_path: Path,
) -> None:
    home = _codex_home(tmp_path)
    settings = _settings_file(tmp_path, home, interval=15)
    now = [100.0]
    agent = CodexUsageAgent(settings_file=settings, clock=lambda: now[0])
    with open_ledger(ledger_database_path(home)):
        pass
    status = load_ledger_status(ledger_database_path(home))
    pending: Future[CaptureResult] = Future()
    agent._capture_future = pending
    agent._schedule.start(now[0])

    try:
        returned = agent.capture_now()
        assert returned is pending
        now[0] = 175.0
        pending.set_result(
            CaptureResult(
                run_id=1,
                request_kind="scheduled",
                outcome="success",
                elapsed_seconds=1.0,
                status=status,
                stats=CacheStats(),
            )
        )

        assert agent._schedule.seconds_until_due(now[0]) == 900.0
    finally:
        agent._lane.close()


def test_immediate_capture_completion_does_not_reenter_capture_lock(
    tmp_path: Path,
) -> None:
    home = _codex_home(tmp_path)
    agent = CodexUsageAgent(settings_file=_settings_file(tmp_path, home, interval=None))
    agent._lane.close()
    with open_ledger(ledger_database_path(home)):
        pass
    status = load_ledger_status(ledger_database_path(home))

    class ImmediateLane:
        def submit(self, _key, _priority, _operation):
            future: Future[CaptureResult] = Future()
            future.set_result(
                CaptureResult(
                    run_id=1,
                    request_kind="scheduled",
                    outcome="success",
                    elapsed_seconds=0.0,
                    status=status,
                    stats=CacheStats(),
                )
            )
            return future

    agent._lane = ImmediateLane()  # type: ignore[assignment]

    future = agent._submit_capture("scheduled", JobPriority.SCHEDULED_CAPTURE)

    assert future.done()
    assert future.result().outcome == "success"


def test_startup_failure_releases_home_lock_and_stops_runtime_threads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = _codex_home(tmp_path)
    settings = _settings_file(tmp_path, home, interval=None)
    failed = CodexUsageAgent(settings_file=settings)

    def fail_to_start(_self) -> None:
        raise RuntimeError("watcher could not start")

    monkeypatch.setattr("codex_usage.agent_watcher.SessionWatcher.start", fail_to_start)
    with pytest.raises(RuntimeError, match="watcher could not start"):
        failed.start()

    assert not failed._lock.is_locked
    assert failed._stop.is_set()

    monkeypatch.undo()
    replacement = CodexUsageAgent(settings_file=settings)
    try:
        replacement.start()
    finally:
        replacement.stop()


def test_core_onboarding_update_preserves_native_consent_and_preferences(
    tmp_path: Path,
) -> None:
    home = _codex_home(tmp_path)
    settings_file = _settings_file(tmp_path, home, interval=15)
    agent = CodexUsageAgent(settings_file=settings_file)
    try:
        core_onboarded = agent.update_settings({"onboarding_complete": True})

        assert core_onboarded.onboarding_complete is True
        assert core_onboarded.native_onboarding_complete is False
        assert core_onboarded.background_capture is False
        assert core_onboarded.daily_update_checks is False

        native_onboarded = agent.update_settings(
            {
                "native_onboarding_complete": True,
                "background_capture": True,
                "daily_update_checks": True,
            }
        )

        assert native_onboarded.native_onboarding_complete is True
        assert native_onboarded.background_capture is True
        assert native_onboarded.daily_update_checks is True
        restarted = CodexUsageAgent(settings_file=settings_file)
        try:
            assert restarted.settings == native_onboarded
        finally:
            restarted.stop()
    finally:
        agent.stop()


def _codex_home(tmp_path: Path) -> Path:
    home = tmp_path / ".codex"
    (home / "sessions").mkdir(parents=True)
    return home


def _settings_file(tmp_path: Path, home: Path, *, interval: int | None) -> Path:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "codex_home": str(home),
                "capture_interval_minutes": interval,
                "background_capture": False,
                "daily_update_checks": False,
                "onboarding_complete": True,
                "native_onboarding_complete": False,
                "timezone": "UTC",
                "theme": "auto",
                "auto_project_transitions": True,
                "transfer_folder": "",
            }
        ),
        encoding="utf-8",
    )
    return path
