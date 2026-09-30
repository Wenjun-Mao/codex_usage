"""Observation provenance and local-time presentation do not change quota math."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_queries import build_allowance_report
from codex_usage.allowance_store import store_observations
from codex_usage.ledger_schema import open_ledger
from codex_usage.report_allowance import render_allowance_section
from test_allowance_capture_report import _report, _window


def _point(timestamp="2026-09-30T19:20:17.392000+00:00", used=97):
    return QuotaObservation(timestamp, "codex", "primary", "pro", used, 10080, 1791046718)


@pytest.mark.parametrize("origin,label", [
    ("live", "Live probe"), ("parsed", "Task snapshot"),
    ("recovered", "Recovered task snapshot"), ("future-source", "Unknown source"),
])
def test_labels_come_from_durable_provenance(tmp_path, origin, label):
    point = _point()
    with open_ledger(tmp_path / "ledger") as connection:
        store_observations(connection, [point], source_key="fixture", provenance=origin)
        report = build_allowance_report(connection)
        assert dict(connection.execute("select * from quota_observations").fetchone())["used_percent"] == 97
    assert len(report["windows"]) == 1
    assert report["windows"][0]["points"] == [dict(point.to_dict(), provenance=label)]


def test_multiple_sources_do_not_multiply_observations(tmp_path):
    point = _point()
    with open_ledger(tmp_path / "ledger") as connection:
        for source, origin in (("task-a", "parsed"), ("task-b", "parsed"), ("read:1", "live")):
            store_observations(connection, [point], source_key=source, provenance=origin)
        report = build_allowance_report(connection)
    assert report["windows"][0]["points"] == [dict(point.to_dict(), provenance="Live probe, Task snapshot")]


def test_missing_provenance_is_not_misrepresented_as_a_live_probe(tmp_path):
    with open_ledger(tmp_path / "ledger") as connection:
        store_observations(connection, [_point()], source_key="fixture", provenance="parsed")
        connection.execute("delete from quota_provenance")
        report = build_allowance_report(connection)
    assert report["windows"][0]["points"][0]["provenance"] == "Unknown source"


def test_recovered_timestamps_and_overlapping_parsed_provenance_are_preserved(tmp_path):
    first = _point()
    second = replace(first, timestamp="2026-09-30T19:20:25.371000+00:00")
    with open_ledger(tmp_path / "ledger") as connection:
        store_observations(connection, [first, second], source_key="history", provenance="recovered")
        store_observations(connection, [second], source_key="task", provenance="parsed")
        report = build_allowance_report(connection)
    assert report["windows"][0]["points"] == [
        dict(first.to_dict(), provenance="Recovered task snapshot"),
        dict(second.to_dict(), provenance="Recovered task snapshot, Task snapshot"),
    ]


def test_interleaved_one_point_dips_remain_corrections_without_rewriting_values(tmp_path):
    base = datetime(2026, 9, 30, 19, 20, tzinfo=UTC)
    points = [replace(_point(), timestamp=(base + timedelta(seconds=i)).isoformat(), used_percent=used)
              for i, used in enumerate((96, 97, 96, 97))]
    with open_ledger(tmp_path / "ledger") as connection:
        store_observations(connection, points[::2], source_key="task-a", provenance="parsed")
        store_observations(connection, points[1::2], source_key="task-b", provenance="parsed")
        report = build_allowance_report(connection)
    assert len(report["windows"]) == 1
    window = report["windows"][0]
    assert window["corrections"] == 1 and window["closure"] == "ongoing"
    assert [p["used_percent"] for p in window["points"]] == [96, 97, 96, 97]


def _markup(point, timezone="America/Toronto"):
    window = _window(point["timestamp"], point["timestamp"], "insufficient", None, completed=False)
    window["points"] = [point]
    return render_allowance_section(_report([window]), timezone=ZoneInfo(timezone))


def test_details_show_local_observation_and_reset_times_with_source_tooltips():
    point = dict(_point().to_dict(), provenance="Task snapshot")
    markup = _markup(point)
    assert "Quota observations (1)" in markup
    assert "Observed at" in markup and "Slot · Source" in markup
    assert "Captured at" not in markup and "Reset (Unix seconds)" not in markup
    assert "2026-09-30 15:20:17.392 EDT" in markup
    assert "2026-10-03 12:58 EDT" in markup
    assert 'title="UTC: 2026-09-30T19:20:17.392000+00:00"' in markup
    assert 'title="Unix seconds: 1791046718"' in markup
    assert "task-reported quota reading; concurrent tasks may report slightly different values." in markup


@pytest.mark.parametrize("timestamp,expected", [
    ("2026-11-01T05:30:00+00:00", "2026-11-01 01:30:00 EDT"),
    ("2026-11-01T06:30:00+00:00", "2026-11-01 01:30:00 EST"),
    ("2026-03-08T06:30:00+00:00", "2026-03-08 01:30:00 EST"),
    ("2026-03-08T07:30:00+00:00", "2026-03-08 03:30:00 EDT"),
])
def test_observation_details_resolve_dst_from_each_timestamp(timestamp, expected):
    assert expected in _markup(dict(_point(timestamp).to_dict(), provenance="Live probe"))


def test_non_hour_timezone_and_unknown_reset_are_supported():
    point = dict(_point().to_dict(), provenance="Live probe, Task snapshot", resets_at=None)
    markup = _markup(point, "Asia/Kolkata")
    assert "2026-10-01 00:50:17.392 IST" in markup
    assert "quota reading queried during collector capture." in markup
    assert "task-reported quota reading" in markup
    assert "<td>Unavailable</td>" in markup


def test_diagnostic_probe_times_use_the_report_timezone():
    report = _report([])
    report["status"]["last_probe_at"] = "2026-09-30T19:28:13.002605+00:00"
    report["status"]["last_observed_at"] = "2026-09-30T19:13:07.827407+00:00"
    markup = render_allowance_section(report, timezone=ZoneInfo("America/Toronto"))
    assert "2026-09-30 15:28:13.002 EDT" in markup
    assert "2026-09-30 15:13:07.827 EDT" in markup


def test_missing_or_malformed_times_and_source_labels_remain_safe():
    point = dict(_point('<script>bad</script>').to_dict(), provenance='<img src=x onerror="bad">')
    markup = _markup(point)
    assert "time unavailable" in markup
    assert "<img" not in markup and "<script>" not in markup
    assert "&lt;img src=x onerror=&quot;bad&quot;&gt;" in markup
    assert "Unknown source" in _markup(_point().to_dict())
    report = _report([])
    report["status"]["last_probe_at"] = ""
    assert "Last checked: Not captured" in render_allowance_section(report)
