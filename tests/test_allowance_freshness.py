from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from codex_usage import allowance_capture
from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.allowance_models import quota_observations
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_queries import build_allowance_report
from codex_usage.ledger_schema import open_ledger
from codex_usage.report_allowance import render_allowance_section
from test_allowance_protocol import bucket


def _codex_home(tmp_path):
    home = tmp_path / "codex"
    (home / "sessions").mkdir(parents=True)
    return home


def _allowance_markup(home):
    with open_ledger(ledger_database_path(home), read_only=True) as connection:
        report = build_allowance_report(connection)
    return render_allowance_section(report, timezone=ZoneInfo("America/Toronto"))


def test_meter_labels_track_unavailable_fresh_stale_and_recovery(
    tmp_path, monkeypatch
):
    home = _codex_home(tmp_path)
    failed = QuotaRead(datetime.now(UTC).isoformat(), diagnostics="probe_unavailable")
    monkeypatch.setattr(allowance_capture, "probe_allowance", lambda _: failed)

    unavailable = capture_once(home, request_kind="manual", max_workers=1)
    assert unavailable.status.plan_allowance["probe_status"] == "unavailable"
    markup = _allowance_markup(home)
    assert "No current quota reading is available." in markup
    assert "<meter" not in markup

    first_stamp = datetime.now(UTC).replace(microsecond=0).isoformat()
    first = QuotaRead(first_stamp, "pro", quota_observations(bucket(51), first_stamp))
    monkeypatch.setattr(allowance_capture, "probe_allowance", lambda _: first)
    fresh = capture_once(home, request_kind="scheduled", max_workers=1)
    assert fresh.status.plan_allowance["probe_status"] == "fresh"
    markup = _allowance_markup(home)
    local_first = datetime.fromisoformat(first_stamp).astimezone(
        ZoneInfo("America/Toronto")
    )
    assert "Current reading" in markup
    assert f'{local_first:%Y-%m-%d %H:%M} {local_first.tzname()}' in markup
    assert "51% used · 49% remaining" in markup
    assert "Last known reading" not in markup

    monkeypatch.setattr(
        allowance_capture,
        "probe_allowance",
        lambda _: QuotaRead(datetime.now(UTC).isoformat(), diagnostics="probe_unavailable"),
    )
    stale = capture_once(home, request_kind="scheduled", max_workers=1)
    status = stale.status.plan_allowance
    assert status["probe_status"] == "stale"
    assert status["plan"] == "pro"
    assert status["active_buckets"][0]["used_percent"] == 51
    markup = _allowance_markup(home)
    assert "Last known reading" in markup
    assert "51% used · 49% remaining" in markup
    assert f'datetime="{first_stamp}"' in markup

    recovered_stamp = datetime.now(UTC).replace(microsecond=0).isoformat()
    recovered = QuotaRead(
        recovered_stamp,
        "pro",
        quota_observations(bucket(50), recovered_stamp),
    )
    monkeypatch.setattr(allowance_capture, "probe_allowance", lambda _: recovered)
    restored = capture_once(home, request_kind="scheduled", max_workers=1)
    assert restored.status.plan_allowance["probe_status"] == "fresh"
    assert restored.status.plan_allowance["active_buckets"][0]["used_percent"] == 50
    markup = _allowance_markup(home)
    assert "Current reading" in markup
    assert "50% used · 50% remaining" in markup
    assert "Last known reading" not in markup
