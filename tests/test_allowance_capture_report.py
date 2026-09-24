from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import render_ledger_report
from codex_usage.allowance_estimation import AllowanceEstimate
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_queries import (
    allowance_highlights,
    allowance_history,
    build_allowance_report,
)
from codex_usage.allowance_store import store_observations
from codex_usage.ledger_schema import open_ledger
from codex_usage.report_allowance import render_allowance_section
from codex_usage.allowance_windows import AllowanceWindow
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
    assert markup.count("Insufficient data") == 1
    assert "Account-wide" in markup


def _window(start, end, confidence, value, *, completed, closure=None, limit_id="codex", duration=10080):
    return {"limit_id": limit_id, "plan": "pro", "duration_minutes": duration,
            "start": start, "end": end, "completed": completed,
            "closure": closure or ("scheduled-compatible" if completed else "ongoing"),
            "corrections": 0, "fully_priced": True, "coverage_complete": True,
            "estimate": {"confidence": confidence, "value": value, "span": 25, "bins": 6,
                         "cost_span": 250, "r_squared": .99, "sensitivity_ratio": 1.1},
            "points": []}


def _report(windows):
    qualified, headline = allowance_highlights(windows)
    latest = windows[-1] if windows else None
    return {"status": {"plan": "pro", "active_buckets": [
                           {"limit_id": "codex", "plan": "pro", "duration_minutes": 10080,
                            "used_percent": 97, "resets_at": None}], "probe_status": "fresh",
                       "last_probe_at": "2026-09-24", "lifetime_tokens": None,
                       "recovery": {"complete": 0, "pending": 0, "unavailable": 0}},
            "windows": windows, "qualified": qualified, "headline": headline,
            "headline_previous": headline is not None and headline is not latest,
            "history": allowance_history(windows)}


def test_current_estimate_is_primary_and_older_qualified_value_is_collapsed():
    completed = _window("2026-08-24", "2026-08-31", "Medium", 1069.59, completed=True)
    current = _window("2026-09-19", "2026-09-24", "Low/provisional", 1375, completed=False)
    report = _report([completed, current])
    assert report["qualified"] == [completed]
    assert report["headline"] is current
    markup = render_allowance_section(report)
    assert "Current · provisional" in markup and "$1,375.00" in markup
    summary = markup.split('<details><summary>Probe, coverage, and allowance history')[0]
    assert "Observed 2026-09-19–2026-09-24" in summary
    assert "codex · pro · 7 days" not in summary
    assert "Low/provisional confidence" not in summary
    assert "Latest completed · qualified" not in markup
    assert "$1,069.59" not in markup.split('<details><summary>Probe, coverage, and allowance history')[0]
    assert "$1,069.59" in markup.split('<details><summary>Reset windows and capture details</summary>')[1]
    assert "Earlier qualified estimates (latest 1 of 1" in markup
    assert markup.index("Probe, coverage, and allowance history") < markup.index("Last checked")
    assert markup.index("Probe, coverage, and allowance history") < markup.index("Latest window fit: 25 percentage points")
    assert markup.index("Latest window fit:") > markup.index("</div></div>")
    assert "<svg" not in markup and "Qualified completed-window trend" not in markup
    assert "<script" not in markup


def test_absent_and_provisional_only_states():
    incomplete = _window("2026-09-19", "2026-09-24", "insufficient", None, completed=False)
    assert allowance_highlights([incomplete]) == ([], None)
    provisional = _window("2026-09-19", "2026-09-24", "Low/provisional", 1375, completed=False)
    report = _report([provisional])
    markup = render_allowance_section(report)
    assert report["qualified"] == [] and report["headline"] is provisional
    assert "$1,375.00" in markup and "No earlier qualified completed estimate" in markup
    assert "The latest window has no valid priced estimate" in render_allowance_section(_report([incomplete]))


def test_just_reset_nine_point_window_uses_dated_same_series_previous_estimate():
    old = _window("2026-08-24", "2026-08-31", "Medium", 1200, completed=True)
    latest = _window("2026-09-01", "2026-09-01", "insufficient", None, completed=False)
    latest["estimate"].update(span=9, bins=5)
    report = _report([old, latest])
    assert report["headline"] is old
    assert report["headline_previous"]
    markup = render_allowance_section(report)
    summary = markup.split('<details><summary>Probe, coverage, and allowance history')[0]
    assert "Previous window" in summary
    assert "Observed 2026-08-24–2026-08-31" in summary
    assert "codex · pro · 7 days" in summary
    assert "$1,200.00" in summary
    assert "Current · provisional" not in summary
    assert "Previous window fit: 25 percentage points" in markup


@pytest.mark.parametrize(
    "changed_series",
    [
        {"limit_id": "extra-model"},
        {"duration": 300},
        {"plan": "plus"},
    ],
)
def test_no_valid_prior_from_another_series(changed_series):
    previous = _window("2026-08-24", "2026-08-31", "High", 1200, completed=True)
    if "duration" in changed_series:
        previous["duration_minutes"] = changed_series["duration"]
    else:
        previous.update({key: value for key, value in changed_series.items() if key != "duration"})
    latest = _window("2026-09-01", "2026-09-01", "insufficient", None, completed=False)
    assert allowance_highlights([previous, latest])[1] is None
    markup = render_allowance_section(_report([previous, latest]))
    assert "The latest window has no valid priced estimate" in markup
    assert "Previous window</h3>" not in markup


def test_ten_point_current_window_takes_over_from_previous_fallback():
    previous = _window("2026-08-24", "2026-08-31", "Medium", 1200, completed=True)
    current = _window("2026-09-01", "2026-09-02", "Low/provisional", 1400, completed=False)
    current["estimate"].update(span=10, bins=5)
    report = _report([previous, current])
    assert report["headline"] is current
    assert not report["headline_previous"]
    markup = render_allowance_section(report)
    summary = markup.split('<details><summary>Probe, coverage, and allowance history')[0]
    assert "Current · provisional" in summary
    assert "Observed 2026-09-01–2026-09-02" in summary
    assert "$1,400.00" in summary
    assert "Previous window" not in summary


def test_unpriced_latest_window_falls_back_without_entering_priced_history():
    previous = _window("2026-08-24", "2026-08-31", "Medium", 1200, completed=True)
    latest = _window("2026-09-01", "2026-09-02", "Low/provisional", None, completed=False)
    latest["fully_priced"] = False
    report = _report([previous, latest])
    assert report["headline"] is previous
    assert report["history"] == [previous]
    assert "$1,200.00" in render_allowance_section(report).split(
        '<details><summary>Probe, coverage, and allowance history'
    )[0]
    assert "$1,200.00" in render_allowance_section(report).split(
        '<details><summary>Probe, coverage, and allowance history'
    )[1]
    assert "$0.00" not in render_allowance_section(report)


def test_built_report_marks_same_series_fallback_as_previous(tmp_path, monkeypatch):
    base = datetime(2026, 8, 1, tzinfo=UTC)
    prior_points = [
        QuotaObservation((base + timedelta(hours=i)).isoformat(), "codex", "primary", "pro",
                         used, 10080, None)
        for i, used in enumerate((0, 15, 30, 45, 60))
    ]
    current_points = [
        QuotaObservation((base + timedelta(hours=5 + i)).isoformat(), "codex", "primary", "pro",
                         used, 10080, None)
        for i, used in enumerate((1, 3, 5, 8, 10))
    ]
    prior = AllowanceWindow(prior_points, "scheduled-compatible")
    current = AllowanceWindow(current_points, "ongoing")
    monkeypatch.setattr(
        "codex_usage.allowance_queries.segment_windows",
        lambda _points: [prior, current],
    )
    monkeypatch.setattr(
        "codex_usage.allowance_queries.estimate_window",
        lambda window, *_args, **_kwargs: (
            AllowanceEstimate("Medium", 1200, span=60, bins=13)
            if window.completed
            else AllowanceEstimate("insufficient", span=9, bins=5)
        ),
    )

    with open_ledger(tmp_path / "ledger") as connection:
        store_observations(
            connection,
            prior_points + current_points,
            source_key="fixture",
            provenance="parsed",
        )
        report = build_allowance_report(connection)

    assert report["headline"] is report["windows"][0]
    assert report["headline_previous"]
    assert report["history"] == [report["windows"][0]]


def test_allowance_history_is_newest_first_and_includes_valid_provisional_windows():
    completed = _window("2026-08-01", "2026-08-07", "High", 1200, completed=True)
    current = _window("2026-09-01", "2026-09-02", "Low/provisional", 1400, completed=False)
    other = _window("2026-08-10", "2026-08-11", "Low/provisional", 500, completed=True,
                    limit_id="extra-model", duration=300)
    unpriced = _window("2026-08-15", "2026-08-16", "Low/provisional", None, completed=True)
    unpriced["fully_priced"] = False
    report = _report([completed, other, unpriced, current])
    assert report["history"] == [current, other, completed]
    markup = render_allowance_section(report)
    history = markup.split('<ol class="allowance-history"')[1].split("</ol>")[0]
    assert history.index("2026-09-01") < history.index("2026-08-10") < history.index("2026-08-01")
    assert "Low/provisional confidence" in history
    assert "Current" in history and "Completed" in history
    assert "extra-model · pro · 5 hours" in history
    assert "2026-08-15" not in history
    assert '<details' not in history


def test_allowance_history_is_bounded_and_discloses_omitted_count():
    windows = [
        _window(f"2026-08-{index:02d}", f"2026-08-{index:02d}", "Low/provisional", 1000 + index,
                completed=False)
        for index in range(1, 15)
    ]
    markup = render_allowance_section(_report(windows))
    assert "Newest 12 of 14 valid priced windows" in markup
    history = markup.split('<ol class="allowance-history"')[1].split("</ol>")[0]
    assert "2026-08-14" in history and "2026-08-03" in history
    assert "2026-08-02" not in history


def test_allowance_history_escapes_series_labels():
    malicious = _window("2026-08-24", "2026-08-31", "High", 1200, completed=True,
                        limit_id='<script>alert("series")</script>')
    markup = render_allowance_section(_report([malicious]))
    assert "<script" not in markup
    assert "&lt;script&gt;alert(&quot;series&quot;)&lt;/script&gt;" in markup


def test_ended_identity_window_is_not_labeled_current():
    ended = _window("2026-08-24", "2026-08-31", "Low/provisional", 1200,
                    completed=False, closure="identity-change")
    markup = render_allowance_section(_report([ended]))
    history = markup.split('<ol class="allowance-history"')[1].split("</ol>")[0]
    assert "Ended after plan change" in history
    assert "Current · Low/provisional confidence" not in history


def test_multiple_series_keep_qualified_history_in_collapsed_details():
    same = _window("2026-08-24", "2026-08-31", "Medium", 1069, completed=True)
    other = _window("2026-09-01", "2026-09-10", "High", 500, completed=True,
                    limit_id="extra-model", duration=300)
    current = _window("2026-09-19", "2026-09-24", "Low/provisional", 1375, completed=False)
    report = _report([same, other, current])
    markup = render_allowance_section(report)
    assert report["qualified"] == [same, other]
    assert "$1,069.00" not in markup.split('<details><summary>Probe, coverage, and allowance history')[0]
    assert "$500.00" in markup.split('<details><summary>Reset windows and capture details</summary>')[1]
    assert "extra-model · pro · 5 hours" in markup


def test_unrelated_qualified_history_stays_in_details():
    other = _window("2026-09-01", "2026-09-10", "High", 500, completed=True,
                    limit_id="extra-model", duration=300)
    current = _window("2026-09-19", "2026-09-24", "Low/provisional", 1375, completed=False)
    report = _report([other, current])
    markup = render_allowance_section(report)
    assert "Earlier qualified estimates (latest 1 of 1" in markup
    assert "$500.00" in markup.split('<details><summary>Reset windows and capture details</summary>')[1]


def test_latest_qualified_headline_excludes_itself_from_older_context():
    previous = _window("2026-08-24", "2026-08-31", "Medium", 1069, completed=True)
    latest = _window("2026-09-19", "2026-09-24", "High", 1375, completed=True)
    report = _report([previous, latest])
    assert report["headline"] is latest
    markup = render_allowance_section(report)
    assert "Latest window · qualified" in markup
    assert "$1,069.00" in markup.split('<details><summary>Reset windows and capture details</summary>')[1]
    assert "Earlier qualified estimates (latest 1 of 1" in markup
    assert "No earlier qualified completed estimate" in render_allowance_section(_report([latest]))


def test_summary_retains_series_for_multiple_active_buckets_and_historic_headlines():
    current = _window("2026-09-19", "2026-09-24", "Low/provisional", 1375, completed=False)
    multiple = _report([current])
    multiple["status"]["active_buckets"].append(
        {"limit_id": "extra-model", "plan": "pro", "duration_minutes": 300,
         "used_percent": 8, "resets_at": None}
    )
    summary = render_allowance_section(multiple).split(
        '<details><summary>Probe, coverage, and allowance history'
    )[0]
    assert "codex · pro · 7 days" in summary

    historical = _window("2026-09-01", "2026-09-10", "High", 500, completed=True,
                         limit_id="extra-model", duration=300)
    history_report = _report([historical])
    summary = render_allowance_section(history_report).split(
        '<details><summary>Probe, coverage, and allowance history'
    )[0]
    assert "extra-model · pro · 5 hours" in summary
    assert "High confidence" in summary


@pytest.mark.parametrize(
    ("timestamp", "expected", "datetime_value"),
    [
        (datetime(2026, 3, 8, 6, 30, tzinfo=UTC).timestamp(),
         "2026-03-08 01:30 EST (UTC−05:00)", "2026-03-08T01:30-05:00"),
        (datetime(2026, 3, 8, 7, 30, tzinfo=UTC).timestamp(),
         "2026-03-08 03:30 EDT (UTC−04:00)", "2026-03-08T03:30-04:00"),
    ],
)
def test_reset_display_tracks_configured_timezone_across_dst(timestamp, expected, datetime_value):
    report = _report([])
    report["status"]["active_buckets"][0]["resets_at"] = timestamp

    markup = render_allowance_section(report, timezone=ZoneInfo("America/Toronto"))

    assert expected in markup
    assert f'<time datetime="{datetime_value}">' in markup


def test_reset_display_includes_non_hour_utc_offset():
    report = _report([])
    report["status"]["active_buckets"][0]["resets_at"] = 2_000_000_000

    markup = render_allowance_section(report, timezone=ZoneInfo("Asia/Kolkata"))

    assert "2033-05-18 09:03 IST (UTC+05:30)" in markup
    assert 'datetime="2033-05-18T09:03+05:30"' in markup


def test_report_pipeline_passes_configured_timezone_and_cache_identity(tmp_path, monkeypatch):
    home = setup_home(tmp_path)
    stamp = datetime.now(UTC).isoformat()
    monkeypatch.setattr(
        "codex_usage.allowance_capture.probe_allowance",
        lambda _: QuotaRead(stamp, "pro", quota_observations(bucket(), stamp)),
    )
    capture_once(home, request_kind="manual", max_workers=1)

    toronto = render_ledger_report(
        home, range_name="all", project_keys=[], theme="day", timezone_name="America/Toronto"
    )
    assert "2033-05-17 23:33 EDT (UTC−04:00)" in toronto.html
    assert 'Reset: <time datetime="2033-05-17T23:33-04:00">' in toronto.html
    assert not toronto.cache_hit

    utc = render_ledger_report(
        home, range_name="all", project_keys=[], theme="day", timezone_name="UTC"
    )
    assert "2033-05-18 03:33 UTC (UTC+00:00)" in utc.html
    assert not utc.cache_hit
    assert render_ledger_report(
        home, range_name="all", project_keys=[], theme="day", timezone_name="America/Toronto"
    ).cache_hit


def test_rendered_capture_table_is_bounded_and_escaped():
    window = _window("2026-09-19", "2026-09-24", "Low/provisional", 1375, completed=False,
                     limit_id="<script>alert(1)</script>")
    window["points"] = [{"timestamp": f"2026-09-24T{i:03d}", "used_percent": i,
                         "slot": "primary", "resets_at": None} for i in range(105)]
    markup = render_allowance_section(_report([window]))
    assert "Most recent 100 of 105 observations shown" in markup
    assert "2026-09-24T000" not in markup and "2026-09-24T104" in markup
    assert "<script" not in markup and "&lt;script&gt;" in markup


def test_active_bucket_and_timezone_text_remain_escaped():
    class UnsafeTimezone(tzinfo):
        def utcoffset(self, _value):
            return timedelta(hours=2)

        def dst(self, _value):
            return timedelta(0)

        def tzname(self, _value):
            return '<script>alert("zone")</script>'

    report = _report([])
    bucket_row = report["status"]["active_buckets"][0]
    bucket_row["limit_id"] = '<img src=x onerror="bad">'
    bucket_row["resets_at"] = 2_000_000_000

    markup = render_allowance_section(report, timezone=UnsafeTimezone())

    assert "<script" not in markup and "<img" not in markup
    assert "&lt;script&gt;alert(&quot;zone&quot;)&lt;/script&gt;" in markup
    assert "&lt;img src=x onerror=&quot;bad&quot;&gt;" in markup


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
