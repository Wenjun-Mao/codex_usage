from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path

import pytest

import codex_usage.cli as cli_module
import codex_usage.session_cache as session_cache_module
import codex_usage.usage_context as usage_context_module
from codex_usage.aggregation import RangeBounds
from codex_usage.parallel.execution import ParallelRunReport
from codex_usage.performance_timing import PhaseTimer, write_timing_sidecar
from codex_usage.session_cache import CacheStats
from codex_usage.session_cache_models import CacheRefreshOutcome
from codex_usage.usage_context import UsageContext


class FakeClock:
    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def test_phase_timer_writes_versioned_atomic_sidecar(tmp_path: Path) -> None:
    clock = FakeClock([10.0, 10.2, 10.5, 11.0])
    timer = PhaseTimer(clock=clock)
    with timer.measure("inventory"):
        pass
    with timer.measure("range_query"):
        pass

    output = tmp_path / "timing.json"
    write_timing_sidecar(
        output,
        timer,
        cache_stats=CacheStats(
            rebuilt=True,
            files_parsed=2,
            files_reused=3,
            file_errors=1,
            legacy_cleanup_errors=1,
        ),
        command="report",
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["command"] == "report"
    assert payload["cache"] == {
        "rebuilt": True,
        "files_total": 0,
        "files_current": 0,
        "files_archived": 0,
        "files_parsed": 2,
        "files_reused": 3,
        "files_removed": 0,
        "files_missing_retained": 0,
        "file_errors": 1,
        "legacy_cleanup_errors": 1,
        "cache_errors": 0,
        "worker_infrastructure_errors": 0,
        "worker_serial_fallbacks": 0,
        "direct_fallback": False,
    }
    assert payload["phases_seconds"] == {
        "inventory": 0.2,
        "usage_refresh": 0.0,
        "transition_refresh": 0.0,
        "range_query": 0.5,
        "aggregation_render": 0.0,
        "total_cli": 0.0,
    }
    assert payload["total_seconds"] == 0.0
    assert not (tmp_path / "timing.json.tmp").exists()


def test_phase_timer_accumulates_full_precision_until_serialization() -> None:
    clock = FakeClock([0.0, 0.123456789])
    timer = PhaseTimer(clock=clock)

    with timer.measure("inventory"):
        pass

    assert timer.elapsed_seconds("inventory") == pytest.approx(0.123456789)


def test_phase_timer_rejects_nested_duplicate_phase_names() -> None:
    timer = PhaseTimer(clock=lambda: 1.0)

    with timer.measure("inventory"), pytest.raises(ValueError, match="already active"), timer.measure("inventory"):
        pass


def test_phase_timer_rejects_negative_elapsed_values() -> None:
    timer = PhaseTimer(clock=FakeClock([2.0, 1.0]))

    with pytest.raises(ValueError, match="negative"), timer.measure("inventory"):
        pass


def test_cli_sidecar_failure_is_non_fatal_for_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = UsageContext([], [], [], UTC, [], [], CacheStats())
    output = tmp_path / "report.html"
    monkeypatch.setattr(cli_module, "load_usage_context", lambda _args: context)
    monkeypatch.setattr(
        cli_module,
        "write_timing_sidecar",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unavailable")),
    )

    assert cli_module.main(
        [
            "report",
            "--range",
            "all",
            "--output",
            str(output),
            "--timing-output",
            str(tmp_path / "timing.json"),
        ]
    ) == 0
    assert output.is_file()
    assert capsys.readouterr().err.count("timing sidecar") == 1


def test_direct_cache_fallback_sidecar_has_complete_phases_and_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    session_file = session_dir / "session.jsonl"
    ticks = iter(float(value) for value in range(20))
    timer = PhaseTimer(clock=lambda: next(ticks))
    monkeypatch.setattr(
        usage_context_module,
        "load_cached_session_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache broken")),
    )
    monkeypatch.setattr(usage_context_module, "collect_jsonl_files", lambda _dirs: [session_file])
    monkeypatch.setattr(usage_context_module, "parse_session_files", lambda _files: [])
    monkeypatch.setattr(usage_context_module, "collect_repo_path_observations", lambda *_args: [])
    monkeypatch.setattr(usage_context_module, "infer_project_transitions", lambda *_args: [])
    monkeypatch.setattr(usage_context_module, "apply_project_transitions", lambda records, _transitions: records)

    data = usage_context_module.load_session_data(
        [session_dir],
        auto_transitions=True,
        range_bounds=RangeBounds(0, 1),
        range_name="today",
        timezone=UTC,
        timer=timer,
    )
    output = tmp_path / "fallback-timing.json"
    write_timing_sidecar(output, timer, cache_stats=data.stats, command="report")

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert set(payload["phases_seconds"]) == {
        "inventory",
        "usage_refresh",
        "transition_refresh",
        "range_query",
        "aggregation_render",
        "total_cli",
    }
    assert payload["phases_seconds"]["usage_refresh"] == 1.0
    assert payload["phases_seconds"]["transition_refresh"] == 1.0
    assert payload["phases_seconds"]["range_query"] == 1.0
    assert payload["cache"]["direct_fallback"] is True
    assert payload["cache"]["cache_errors"] == 1
    assert payload["cache"]["files_parsed"] == 1
    assert payload["cache"]["worker_infrastructure_errors"] == 0
    assert payload["cache"]["worker_serial_fallbacks"] == 0


def test_threads_timing_includes_aggregation_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = session_cache_module.uncached_session_data([], [], [], [])
    ticks = iter(float(value) for value in range(20))
    monkeypatch.setattr(cli_module, "PhaseTimer", lambda: PhaseTimer(clock=lambda: next(ticks)))
    monkeypatch.setattr(cli_module, "find_session_dirs", list)
    monkeypatch.setattr(cli_module, "load_session_data", lambda *_args, **_kwargs: data)
    output = tmp_path / "threads-timing.json"

    assert cli_module.main(["threads", "--json", "--timing-output", str(output)]) == 0

    captured = capsys.readouterr()
    sidecar = json.loads(output.read_text(encoding="utf-8"))
    assert json.loads(captured.out) == {"threads": [], "project_keys": []}
    assert sidecar["phases_seconds"]["aggregation_render"] == 1.0
    assert "timing" not in captured.out


def test_cached_worker_fallback_diagnostics_are_serialized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    usage_run = ParallelRunReport(2, (), True, "worker startup failed", 0)
    outcome = CacheRefreshOutcome(
        stats=CacheStats(files_parsed=2, files_reused=3, file_errors=4),
        usage_run=usage_run,
        affected_task_ids=frozenset(),
    )
    monkeypatch.setattr(session_cache_module._refresh, "refresh_files", lambda *_args, **_kwargs: outcome)

    data = session_cache_module.load_cached_session_data(
        [sessions],
        cache_dir=tmp_path / "cache",
        auto_transitions=False,
    )
    output = tmp_path / "worker-timing.json"
    write_timing_sidecar(output, PhaseTimer(), cache_stats=data.stats, command="report")

    cache = json.loads(output.read_text(encoding="utf-8"))["cache"]
    assert cache["rebuilt"] is False
    assert cache["files_parsed"] == 2
    assert cache["files_reused"] == 3
    assert cache["file_errors"] == 4
    assert cache["worker_infrastructure_errors"] == 1
    assert cache["worker_serial_fallbacks"] == 1
    assert cache["legacy_cleanup_errors"] == 0
    assert cache["direct_fallback"] is False
