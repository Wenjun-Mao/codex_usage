"""Manager reproductions at the complete report, evidence and chart boundary."""
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from runpy import run_path
from zoneinfo import ZoneInfo

import pytest

from codex_usage.agent_reports import render_ledger_report
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_store import store_read
from codex_usage.breakdown_reports import load
from codex_usage.breakdown_reports import store
from codex_usage.breakdown_commands import RECEIPT_MAX_SCOPES, RECEIPT_PREFIX, issued_action, receipt, prune_receipts
from codex_usage.breakdown_aggregation import aggregate, local_hours
from codex_usage.aggregation import value_records
from codex_usage.ledger_schema import increment_ledger_revision, open_ledger
from codex_usage.models import TokenUsage, UsageRecord

fixture = run_path(str(Path(__file__).resolve().parents[1] / "scripts/usage_breakdown_fixture.py"))
AT, breakdown_home = fixture["AT"], fixture["breakdown_home"]


def render(home, action=None):
    return render_ledger_report(home, range_name="all", project_keys=[], theme="day",
        timezone_name="UTC", now=AT, breakdown_action=json.dumps(action) if action else None)


@pytest.mark.parametrize("durations", [(None, 10080), (None, 300), (300,)])
def test_selected_range_preserves_missing_nonweekly_and_weekly_evidence(tmp_path, durations):
    path = breakdown_home(tmp_path)
    with open_ledger(path) as connection:
        # Remove only synthetic quota history, then use the public capture store.
        connection.execute("delete from quota_provenance")
        connection.execute("delete from quota_observations")
        for i, duration in enumerate(durations):
            point = QuotaObservation((AT - timedelta(minutes=10-i)).isoformat(), "codex", "primary",
                "" if duration is None else "pro", 30+i, duration, int((AT+timedelta(days=4)).timestamp()))
            store_read(connection, QuotaRead(point.timestamp, point.plan, (point,)), None)
        increment_ledger_revision(connection)
        connection.commit()
    first = render(tmp_path)
    action = next(a for a in first.breakdown_navigation["actions"] if a["state"]["basis"] == "selected")
    report = render(tmp_path, action)
    section = report.html.split('<section class="section usage-breakdown"', 1)[1]
    assert "Captured weekly allowance remaining" in section
    assert f"Exact captured readings ({len(durations)})" in section
    if None in durations:
        assert "duration unavailable" in section and "plan unavailable" in section
    if 10080 in durations:
        assert "codex · weekly · pro" in section
    else:
        assert "Weekly allowance unavailable: no supported weekly readings" in section
        assert 'class="ub-meter-legend"' not in section


def calibrated_home(home, *, unknown=False, full=False):
    path = breakdown_home(home)
    with open_ledger(path) as connection:
        if not unknown:
            connection.execute("""update ledger_usage_events set model_id=(select model_id from ledger_models where model_key='gpt-6.1-sol')
                where model_id=(select model_id from ledger_models where model_key='unknown-synthetic')""")
        # Real valued events at both calibration endpoints prove the inclusion
        # convention, rather than borrowing handcrafted pace/cost metadata.
        first_id = connection.execute("select event_id from ledger_usage_events order by timestamp_us limit 1").fetchone()[0]
        last_id = connection.execute("select event_id from ledger_usage_events order by timestamp_us desc limit 1").fetchone()[0]
        for event_id, at in ((first_id, AT-timedelta(days=3)), (last_id, AT)):
            connection.execute("update ledger_usage_events set timestamp=?,timestamp_us=? where event_id=?",
                (at.isoformat(), round(at.timestamp()*1e6), event_id))
        # Existing earlier observations establish a genuine priced fit. Three
        # final points establish the exact one-hour recent pace at 11:00-12:00.
        connection.execute("delete from quota_provenance where observation_key in (select observation_key from quota_observations where timestamp=?)", (AT.isoformat(),))
        connection.execute("delete from quota_observations where timestamp=?", (AT.isoformat(),))
        for minutes, used in ((60, 30), (30, 32), (0, 100 if full else 34)):
            point = QuotaObservation((AT-timedelta(minutes=minutes)).isoformat(), "codex", "secondary",
                "pro", used, 10080, int((AT+timedelta(days=4)).timestamp()))
            store_read(connection, QuotaRead(point.timestamp, "pro", (point,)), None)
        increment_ledger_revision(connection)
        connection.commit()
    return path


def test_real_calibrated_cycle_and_hour_render_with_exact_endpoints(tmp_path):
    path = calibrated_home(tmp_path)
    first = render(tmp_path)
    with open_ledger(path, read_only=True) as connection:
        key = connection.execute("select cache_key from rendered_reports where cache_key like 'breakdown:%:metadata'").fetchone()[0]
        metadata = load(connection, key)
        cycle_basis = metadata["ranges"]["cycle"]["partition_basis"]
        cycle = load(connection, key[:-len("metadata")] + cycle_basis + ":summary")
        assert cycle["end"] == AT.timestamp()
        assert cycle["calibration"]["value"] is not None
        evidence = metadata["evidence"]
        pace = next(p for series in evidence["paces"] for p in series if p["name"] == "Cycle" and p["method"] == "calibrated cost")
        assert cycle["total"]["allowance_cost"] == pytest.approx(pace["cost"])
        excluded_tokens = connection.execute("select sum(total_tokens) from ledger_usage_events where timestamp_us<=?", (round(cycle["start"]*1e6),)).fetchone()[0]
        selected = load(connection, key[:-len("metadata")] + "selected:summary")
        assert selected["total"]["tokens"] - cycle["total"]["tokens"] == excluded_tokens
        day = load(connection, key[:-len("metadata")] + cycle_basis + ":day:2026-10-09")
        hour_key = (AT-timedelta(hours=1)).isoformat()
        assert day["calibrations"][hour_key]["value"] is not None
        assert any(r["hour"] == hour_key for r in day["rows"])
        recent = next(p for series in evidence["paces"] for p in series if p["name"] == "Recent" and p["method"] == "calibrated cost")
        assert sum(r["allowance_cost"] for r in day["rows"] if r["hour"] == hour_key) == pytest.approx(recent["cost"])
    assert "pp estimated" in first.html
    action = next(a for a in first.breakdown_navigation["actions"] if a["state"]["detail"] == "hour:" + hour_key)
    drilled = render(tmp_path, action)
    hour_detail = drilled.html.split('<h3>Hour detail', 1)[1].split('<details><summary>All interval', 1)[0]
    assert "pp estimated" in hour_detail and "Capture-causal" in hour_detail


@pytest.mark.parametrize("kwargs", [{"unknown": True}, {"full": True}])
def test_real_cycle_unknown_or_full_stays_unavailable(tmp_path, kwargs):
    path = calibrated_home(tmp_path, **kwargs)
    report = render(tmp_path)
    with open_ledger(path, read_only=True) as connection:
        key = connection.execute("select cache_key from rendered_reports where cache_key like 'breakdown:%:metadata'").fetchone()[0]
        basis = load(connection, key)["ranges"]["cycle"]["partition_basis"]
        assert load(connection, key[:-len("metadata")] + basis + ":summary")["calibration"]["value"] is None
    assert "pp estimated" not in report.html.split('<section class="section usage-breakdown"', 1)[1]


@pytest.mark.parametrize("zone_name,day", [("Pacific/Chatham", "2026-09-27"),
    ("Pacific/Chatham", "2026-04-05"), ("America/Toronto", "2026-11-01")])
def test_utc_sampled_causal_hour_membership_includes_closing_boundary(zone_name, day):
    zone = ZoneInfo(zone_name)
    hours = local_hours(day, zone)
    start, end = hours[0]["start"], hours[-1]["end"]
    records = []
    at = start
    while at <= end:
        records.append(UsageRecord(datetime.fromtimestamp(at, UTC), TokenUsage(1,0,0,0,0,1),
            "task", Path("synthetic"), "root", "gpt-6.1-sol", project_key="p", project_label="P"))
        at += 60
    info, data = aggregate(value_records(records), zone, {"cycle": None, "paces": []},
        start=start, end=end, complete=True, causal=True)
    assert info["total"]["tokens"] == len(records)-1
    assert list(k for k in data if k.startswith("day:")) == ["day:"+day]
    rows = data["day:"+day]["rows"]
    for hour in hours:
        expected = sum(hour["start"] < r.timestamp.timestamp() <= hour["end"] for r in records)
        assert sum(r["tokens"] for r in rows if r["hour"] == hour["key"]) == expected


def test_receipt_policy_is_bounded_and_expired_or_fabricated_proofs_reject(tmp_path):
    path = breakdown_home(tmp_path)
    state = {"basis": "selected", "view": "hour", "metric": "cost", "group": "model", "day": "2026-10-09", "detail": ""}
    actions = [{"scope": f"{i:064x}", "state": state} for i in range(RECEIPT_MAX_SCOPES+2)]
    with open_ledger(path, read_only=True) as connection:
        revision = int(connection.execute("select value from ledger_meta where key='ledger_revision'").fetchone()[0])
    store(path, revision, {RECEIPT_PREFIX+a["scope"]: receipt([a]) for a in actions})
    with open_ledger(path) as connection:
        assert connection.execute("select count(*) from rendered_reports where cache_key like 'breakdown-issued:%'").fetchone()[0] == RECEIPT_MAX_SCOPES
        assert issued_action(connection, json.dumps(actions[-1]), load) == actions[-1]
        with pytest.raises(ValueError, match="Unissued"):
            issued_action(connection, json.dumps(actions[0]), load)
        with pytest.raises(ValueError, match="Unissued"):
            issued_action(connection, json.dumps({**actions[-1], "state": {**state, "day": "2099-01-01"}}), load)
        prune_receipts(connection, now=datetime.now(UTC)+timedelta(hours=25))
        assert connection.execute("select count(*) from rendered_reports where cache_key like 'breakdown-issued:%'").fetchone()[0] == 0
        with pytest.raises(ValueError, match="Unissued"):
            issued_action(connection, json.dumps(actions[-1]), load)
