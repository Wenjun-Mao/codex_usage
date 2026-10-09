from datetime import UTC, datetime
from statistics import median
from zoneinfo import ZoneInfo

import pytest

from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import render_ledger_report
from codex_usage.aggregation import resolve_report_range
from codex_usage.ledger_schema import open_ledger
from codex_usage.speed_queries import calendar_buckets, chart_navigation, describe, hour_bucket, speed_aggregates
from codex_usage.speed_store import touch
from speed_test_support import AT, append_rows, response, write_source


@pytest.fixture(autouse=True)
def no_quota(monkeypatch):
    monkeypatch.setattr("codex_usage.agent_capture.capture_quota_read", lambda *a: None)


@pytest.mark.parametrize("n,numeric,small", [(0, False, False), (4, False, False), (5, True, True), (19, True, True), (20, True, False)])
def test_display_gates_and_independent_medians(n, numeric, small):
    samples = [{"rate": i * 2 + 1, "task": "one-task", "source": "one-source"} for i in range(n)]
    result = describe(samples)
    assert (result["median"] is not None) == numeric
    assert result["small"] == small
    if numeric:
        assert result["median"] == median([s["rate"] for s in samples])
        assert result["tasks"] == result["sources"] == 1


@pytest.mark.parametrize("day,hours", [("2026-03-08", 23), ("2026-11-01", 25)])
def test_hourly_calendar_preserves_dst_offsets(tmp_path, day, hours):
    zone = ZoneInfo("America/Toronto")
    nav = {"granularity": "hourly", "window_start": day, "window_end": day}
    buckets = calendar_buckets(nav, zone)
    assert len(buckets) == hours and len(set(buckets)) == hours
    if hours == 25:
        assert len([b for b in buckets if "T01:00:00" in b]) == 2


@pytest.mark.parametrize("zone_name,day,hour,minute", [
    ("Australia/Lord_Howe", "2026-10-04", 3, 0),
    ("Australia/Lord_Howe", "2026-04-05", 2, 0),
    ("Pacific/Chatham", "2026-09-27", 3, 50),
])
def test_partial_hour_dst_calendar_contains_actual_aggregate_keys(tmp_path, zone_name, day, hour, minute):
    zone = ZoneInfo(zone_name)
    local = datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=zone)
    write_source(tmp_path, count=5, at=local)
    capture_once(tmp_path, request_kind="manual", max_workers=1)
    selected = resolve_report_range("today", zone, now=local.replace(hour=12))
    with open_ledger(ledger_database_path(tmp_path), read_only=True) as connection:
        result, _ = speed_aggregates(connection, selected, [], zone)
    calendar = set(calendar_buckets({"granularity": "hourly", "window_start": day, "window_end": day}, zone))
    assert result["hourly"] and result["hourly"][0]["n"] == 5
    assert {point["bucket"] for point in result["hourly"]} <= calendar
    assert result["hourly"][0]["bucket"].endswith(local.strftime("%z")[:3] + ":" + local.strftime("%z")[3:])


@pytest.mark.parametrize("zone_name,day", [
    ("America/Toronto", "2026-03-08"), ("America/Toronto", "2026-11-01"),
    ("Australia/Lord_Howe", "2026-10-04"), ("Australia/Lord_Howe", "2026-04-05"),
    ("Pacific/Chatham", "2026-09-27"), ("Pacific/Chatham", "2026-04-05"),
])
def test_hour_calendar_contains_observed_wall_clock_bins(zone_name, day):
    from datetime import timedelta
    zone = ZoneInfo(zone_name)
    first = datetime.fromisoformat(day).replace(tzinfo=zone)
    stop = (first + timedelta(days=1)).astimezone(UTC)
    instant = first.astimezone(UTC)
    observed = set()
    while instant < stop:
        observed.add(hour_bucket(instant.astimezone(zone)))
        instant += timedelta(minutes=5)
    calendar = calendar_buckets({"granularity": "hourly", "window_start": day, "window_end": day}, zone)
    assert set(calendar) == observed
    assert calendar == sorted(calendar, key=lambda bucket: datetime.fromisoformat(bucket).timestamp())


def test_fact_level_oracle_and_project_transition_filter(tmp_path):
    path = write_source(tmp_path, count=5)
    for i in range(5, 10):
        append_rows(path, response(i, seconds=4))
    capture_once(tmp_path, request_kind="manual", max_workers=1)
    report_range = resolve_report_range("all", UTC, now=AT)
    with open_ledger(ledger_database_path(tmp_path)) as connection:
        before, _ = speed_aggregates(connection, report_range, [], UTC)
        assert before["summaries"]["gpt-6.1-sol"]["median"] == median([300] * 5 + [150] * 5)
        key = connection.execute("select project_key from ledger_projects").fetchone()[0]
        connection.execute("""insert into ledger_transitions(owner_task_id, source_key, source_label,
            target_key, target_label, effective_from, confidence, evidence_json, task_ids_json)
            values ('task', ?, 'Old', 'new-project', 'New', ?, 100, '[]', '["task"]')""", (key, "2026-10-08T12:02:00+00:00"))
        touch(connection)
        chosen, _ = speed_aggregates(connection, report_range, ["new-project"], UTC)
        assert chosen["summaries"]["gpt-6.1-sol"]["n"] == 6
        none, _ = speed_aggregates(connection, report_range, ["unknown-project"], UTC)
        assert none["summaries"] == {}


def test_warm_and_window_change_do_no_timing_scan_or_monetary_work(tmp_path, monkeypatch):
    write_source(tmp_path)
    capture_once(tmp_path, request_kind="manual", max_workers=1)
    def render(**state):
        return render_ledger_report(tmp_path, range_name="all", project_keys=[], theme="day", timezone_name="UTC", now=AT, **state)
    initial = render()
    assert not initial.cache_hit
    def forbidden(*args, **kwargs):
        raise AssertionError("warm/window change revisited full timing or monetary history")
    monkeypatch.setattr("codex_usage.agent_reports.materialize_ledger", forbidden)
    monkeypatch.setattr("codex_usage.agent_reports.indexed_allowance_report", forbidden)
    monkeypatch.setattr("codex_usage.ledger_queries._row_to_usage_record", forbidden)
    monkeypatch.setattr("codex_usage.speed_queries._row_to_usage_record", forbidden)
    warm = render()
    assert warm.cache_hit and warm.html == initial.html
    hourly = render(speed_granularity="hourly")
    assert "300.0" in hourly.html
    assert hourly.speed_navigation["granularity"] == "hourly"
    assert render(speed_granularity="hourly").cache_hit


def test_seven_day_windows_clamp_without_changing_global_range(tmp_path):
    write_source(tmp_path)
    capture_once(tmp_path, request_kind="manual", max_workers=1)
    now = datetime(2026, 10, 8, tzinfo=UTC)
    selected = resolve_report_range("30d", UTC, now=now)
    with open_ledger(ledger_database_path(tmp_path), read_only=True) as connection:
        nav = chart_navigation(connection, selected, [], UTC, now, "hourly")
        assert nav["window_start"] == "2026-10-02" and nav["window_end"] == "2026-10-08"
        earlier = chart_navigation(connection, selected, [], UTC, now, "hourly", nav["previous"])
        assert earlier["max_date"] == nav["max_date"]
        assert earlier["min_date"] == nav["min_date"]
        assert earlier["next"] == nav["window_start"]
        with pytest.raises(ValueError):
            chart_navigation(connection, selected, [], UTC, now, "hourly", "1900-01-01")


def test_saved_window_rolls_forward_only_with_prior_range_scope(tmp_path):
    from datetime import timedelta
    write_source(tmp_path)
    capture_once(tmp_path, request_kind="manual", max_workers=1)
    with open_ledger(ledger_database_path(tmp_path), read_only=True) as connection:
        previous = chart_navigation(connection, resolve_report_range("today", UTC, now=AT), [], UTC, AT, "hourly")
        tomorrow = AT + timedelta(days=1)
        selected = resolve_report_range("today", UTC, now=tomorrow)
        advanced = chart_navigation(connection, selected, [], UTC, tomorrow, "hourly", previous["window_start"], previous["scope"])
        assert advanced["window_start"] == advanced["window_end"] == "2026-10-09"
        with pytest.raises(ValueError):
            chart_navigation(connection, selected, [], UTC, tomorrow, "hourly", previous["window_start"])
        with pytest.raises(ValueError):
            chart_navigation(connection, selected, [], UTC, tomorrow, "hourly", previous["window_start"], "invalid")


def test_future_custom_range_keeps_existing_date_validation(tmp_path):
    write_source(tmp_path)
    capture_once(tmp_path, request_kind="manual", max_workers=1)
    with pytest.raises(ValueError, match="cannot include future dates"):
        render_ledger_report(tmp_path, range_name="custom", start_date="2026-11-01", end_date="2026-11-03",
            project_keys=[], theme="day", timezone_name="UTC", now=AT)
