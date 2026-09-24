from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import render_ledger_report
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_queries import allowance_highlights, build_allowance_report
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
    assert markup.count("Insufficient data") == 2
    assert "Account-wide" in markup


def _window(start, end, confidence, value, *, completed, closure=None, limit_id="codex"):
    return {"limit_id": limit_id, "plan": "pro", "duration_minutes": 10080,
            "start": start, "end": end, "completed": completed,
            "closure": closure or ("scheduled-compatible" if completed else "ongoing"),
            "corrections": 0, "fully_priced": True, "coverage_complete": True,
            "estimate": {"confidence": confidence, "value": value, "span": 25, "bins": 6,
                         "cost_span": 250, "r_squared": .99, "sensitivity_ratio": 1.1},
            "points": []}


def _report(windows):
    qualified, headline, latest_completed = allowance_highlights(windows)
    return {"status": {"plan": "pro", "active_buckets": [], "probe_status": "fresh",
                       "last_probe_at": "2026-09-24", "lifetime_tokens": None,
                       "recovery": {"complete": 0, "pending": 0, "unavailable": 0}},
            "windows": windows, "qualified": qualified, "headline": headline,
            "latest_completed": latest_completed}


def test_current_and_completed_estimates_are_distinct_and_dated():
    completed = _window("2026-08-24", "2026-08-31", "Medium", 1069.59, completed=True)
    current = _window("2026-09-19", "2026-09-24", "Low/provisional", 1375, completed=False)
    report = _report([completed, current])
    assert report["qualified"] == [completed]
    assert report["headline"] is current
    assert report["latest_completed"] is completed
    markup = render_allowance_section(report)
    assert "Current · provisional" in markup and "$1,375.00" in markup
    assert "Observed 2026-09-19–2026-09-24 · Low/provisional confidence" in markup
    assert "Latest completed · qualified" in markup and "$1,069.59" in markup
    assert "Observed 2026-08-24–2026-08-31 · Medium confidence" in markup
    assert markup.index("$1,375.00") < markup.index("$1,069.59")
    assert markup.index("Probe, coverage, and trend diagnostics") < markup.index("Last checked")
    assert "<script" not in markup


def test_absent_and_provisional_only_states():
    incomplete = _window("2026-09-19", "2026-09-24", "insufficient", None, completed=False)
    assert allowance_highlights([incomplete]) == ([], None, None)
    provisional = _window("2026-09-19", "2026-09-24", "Low/provisional", 1375, completed=False)
    report = _report([provisional])
    markup = render_allowance_section(report)
    assert report["qualified"] == [] and report["headline"] is provisional
    assert "$1,375.00" in markup and "No completed High/Medium window" in markup
    assert "The latest window has no valid priced estimate" in render_allowance_section(_report([incomplete]))


def test_latest_invalid_window_does_not_resurrect_older_valid_estimate():
    old = _window("2026-09-01", "2026-09-05", "Low/provisional", 1200, completed=False)
    latest = _window("2026-09-19", "2026-09-24", "insufficient", None, completed=False)
    report = _report([old, latest])
    assert report["headline"] is None
    markup = render_allowance_section(report)
    assert "The latest window has no valid priced estimate" in markup
    assert markup.index("Insufficient data") < markup.index("$1,200.00")


def test_rendered_capture_table_is_bounded_and_escaped():
    window = _window("2026-09-19", "2026-09-24", "Low/provisional", 1375, completed=False,
                     limit_id="<script>alert(1)</script>")
    window["points"] = [{"timestamp": f"2026-09-24T{i:03d}", "used_percent": i,
                         "slot": "primary", "resets_at": None} for i in range(105)]
    markup = render_allowance_section(_report([window]))
    assert "Most recent 100 of 105 observations shown" in markup
    assert "2026-09-24T000" not in markup and "2026-09-24T104" in markup
    assert "<script" not in markup and "&lt;script&gt;" in markup


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
