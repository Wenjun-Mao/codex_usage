from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import render_ledger_report
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_queries import build_allowance_report
from codex_usage.ledger_schema import open_ledger
from codex_usage.report_allowance import render_allowance_section
from test_allowance_protocol import bucket
from codex_usage.allowance_models import quota_observations


def setup_home(tmp_path):
    home = tmp_path / "codex"
    (home / "sessions").mkdir(parents=True)
    return home


@pytest.mark.parametrize("kind", ["startup", "scheduled", "manual", "catch-up"])
def test_every_capture_records_metadata_and_probe_failure_is_nonfatal(tmp_path, monkeypatch, kind):
    home = setup_home(tmp_path)
    called = []

    def fail(selected):
        called.append(selected)
        raise RuntimeError("PRIVATE AUTH DATA")

    monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance", fail)
    result = capture_once(home, request_kind=kind, max_workers=1)
    assert result.outcome == "success"
    assert called == [home]
    with open_ledger(ledger_database_path(home)) as connection:
        row = connection.execute("select * from quota_reads").fetchone()
        assert row["diagnostics"] == "probe_failed"
        assert "PRIVATE" not in str(tuple(row))


def test_project_date_theme_reports_open_zero_jsonl_and_never_probe(tmp_path, monkeypatch):
    home = setup_home(tmp_path)
    stamp = datetime.now(UTC).isoformat()
    read = QuotaRead(stamp, "pro", quota_observations(bucket(), stamp), 999)
    monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance", lambda _: read)
    capture_once(home, request_kind="manual", max_workers=1)
    original = Path.open

    def checked(path, *args, **kwargs):
        assert path.suffix != ".jsonl", "report opened a JSONL"
        return original(path, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("report triggered capture/probe")

    monkeypatch.setattr(Path, "open", checked)
    monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance", forbidden)
    monkeypatch.setattr("codex_usage.agent_capture.capture_once", forbidden)
    sections = []
    for theme, range_name, projects in (("day", "all", []), ("night", "today", ["other"]), ("day", "month", [])):
        result = render_ledger_report(home, range_name=range_name, project_keys=projects, theme=theme, timezone_name="UTC")
        assert "Plan Allowance" in result.html and "31% used" in result.html
        assert "<script" not in result.html
        assert result.html.index('id="plan-allowance"') < result.html.index('data-report-section="project-economics"') if 'data-report-section="project-economics"' in result.html else True
        sections.append(result.html.split('id="plan-allowance"')[1].split('</section>')[0])
    assert sections[0] == sections[1] == sections[2]


def test_empty_report_is_explicitly_unavailable(tmp_path):
    with open_ledger(tmp_path / "ledger") as connection:
        report = build_allowance_report(connection)
    markup = render_allowance_section(report)
    assert "Quota information is unavailable" in markup
    assert "Insufficient qualified" in markup
    assert "Account-wide" in markup


def test_failed_probe_preserves_last_known_buckets_as_stale(tmp_path, monkeypatch):
    home = setup_home(tmp_path)
    stamp = datetime.now(UTC).isoformat()
    monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance", lambda _: QuotaRead(stamp, "pro", quota_observations(bucket(), stamp)))
    capture_once(home, request_kind="manual", max_workers=1)
    monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance", lambda _: QuotaRead(stamp, diagnostics="probe_unavailable"))
    result = capture_once(home, request_kind="scheduled", max_workers=1)
    status = result.status.plan_allowance
    assert status["probe_status"] == "stale"
    assert status["plan"] == "pro"
    assert status["active_buckets"][0]["used_percent"] == 31


def test_coalesced_capture_performs_one_probe(tmp_path, monkeypatch):
    import threading
    from codex_usage.agent_jobs import JobPriority
    from codex_usage.agent_runtime import CodexUsageAgent
    from test_agent_runtime import _settings_file

    home = setup_home(tmp_path)
    agent = CodexUsageAgent(settings_file=_settings_file(tmp_path, home, interval=None))
    entered, release = threading.Event(), threading.Event()
    calls = []

    def probe(selected):
        calls.append(selected)
        entered.set()
        assert release.wait(5)
        return QuotaRead(datetime.now(UTC).isoformat(), diagnostics="unavailable")

    monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance", probe)
    try:
        first = agent._submit_capture("scheduled", JobPriority.SCHEDULED_CAPTURE)
        assert entered.wait(5)
        assert agent.capture_now() is first
        assert agent.capture_now() is first
        release.set()
        assert first.result(timeout=5).outcome == "success"
        assert calls == [home]
    finally:
        release.set()
        agent._stop.set()
        agent._lane.close()
