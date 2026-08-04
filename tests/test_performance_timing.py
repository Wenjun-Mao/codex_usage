from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path

import pytest

import codex_usage.cli as cli_module
from codex_usage.performance_timing import PhaseTimer, write_timing_sidecar
from codex_usage.session_cache import CacheStats
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
    }
    assert payload["phases_seconds"] == {"inventory": 0.2, "range_query": 0.5}
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
