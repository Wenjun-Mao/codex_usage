"""Composition, chronological identities and strict snapshot navigation contracts."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from codex_usage.aggregation import value_records
from codex_usage.agent_reports import render_ledger_report
from codex_usage.breakdown_aggregation import aggregate, local_hours, ranked_projects, total
from codex_usage.breakdown_evidence import interval_calibration, prepare_evidence
from codex_usage.breakdown_reports import load
from codex_usage.allowance_queries import allowance_status
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_store import store_read
from codex_usage.ledger_schema import increment_ledger_revision, open_ledger
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.speed_reports import render_speed_report

from runpy import run_path

_fixture = run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "usage_breakdown_fixture.py"))
AT, breakdown_home = _fixture["AT"], _fixture["breakdown_home"]


def render(home, **kwargs):
    return render_ledger_report(home, range_name="all", project_keys=[], theme="day",
                               timezone_name="UTC", now=AT, **kwargs)


def action(report, **changes):
    nav = report.breakdown_navigation
    desired = {**nav["state"], **changes}
    return next(a for a in nav["actions"] if a["state"] == desired)


@pytest.mark.parametrize("zone_name,day", [
    ("America/Toronto", "2026-03-08"), ("America/Toronto", "2026-11-01"),
    ("Australia/Lord_Howe", "2026-10-04"), ("Australia/Lord_Howe", "2026-04-05"),
    ("Pacific/Chatham", "2026-09-27"), ("Pacific/Chatham", "2026-04-05"),
])
def test_utc_sampling_proves_occurrence_membership_and_bounds(zone_name, day):
    zone = ZoneInfo(zone_name)
    hours = local_hours(day, zone)
    assert len({h["key"] for h in hours}) == len(hours)
    assert all(a["end"] == b["start"] for a, b in zip(hours, hours[1:]))
    assert all(h["start"] < h["end"] for h in hours)
    instant = datetime.fromtimestamp(hours[0]["start"], UTC)
    stop = datetime.fromtimestamp(hours[-1]["end"], UTC)
    records = []
    while instant < stop:
        records.append(UsageRecord(instant, TokenUsage(1, 0, 0, 0, 0, 1), "task", Path("synthetic"), "root", "gpt-6.1-sol", project_key="p", project_label="P"))
        instant += timedelta(minutes=1)
    result, partitions = aggregate(value_records(records), zone, {"cycle": None, "paces": []},
        start=hours[0]["start"], end=hours[-1]["end"], complete=True)
    assert result["total"]["tokens"] == len(records)
    rows = partitions["day:" + day]["rows"]
    for h in hours:
        observed = [r for r in records if h["start"] <= r.timestamp.timestamp() < h["end"]]
        assert next(r["tokens"] for r in rows if r["hour"] == h["key"]) == len(observed)
        identities = {(r.timestamp.astimezone(zone).hour, r.timestamp.astimezone(zone).utcoffset()) for r in observed}
        assert len(identities) == 1
    if zone_name == "Pacific/Chatham" and day == "2026-09-27":
        assert any(h["label"].startswith("03:45") for h in hours)
        assert len({h["start"] for h in hours}) == len(hours)


def test_free_review_unknown_pricing_and_exact_additive_other():
    records = [UsageRecord(AT, TokenUsage(100, 50, 0, 20, 0, 120), "task", Path("synthetic"),
               "root", model, project_key=str(p), project_label=f"Project {p}")
               for p in range(13) for model in ("gpt-6.1-sol", "codex-auto-review", "unknown-synthetic")]
    valued = value_records(records)
    info, partitions = aggregate(valued, UTC, {"cycle": None, "paces": []},
                                 start=AT.timestamp(), end=AT.timestamp() + 1, complete=True)
    assert info["total"]["cost"] == pytest.approx(sum(v.summary.cost.total_usd for v in valued))
    assert info["total"]["unknown"] + info["total"]["api_excluded"] == sum(v.summary.cost.unpriced_tokens for v in valued)
    review = next(r for r in partitions["day:2026-10-09"]["rows"] if r["model"] == "codex-auto-review")
    assert review["tokens"] == 120 and review["api_excluded"] == 120 and review["unknown"] == 0
    assert review["allowance_cost"] == review["allowance_unknown"] == review["credits"] == review["credit_unknown"] == 0
    for metric in ("tokens", "cost"):
        ranked = ranked_projects(info["projects"], metric)
        assert len(ranked) == 11 and len(ranked[-1][1]["members"]) == 3
        assert total(v for _, p in ranked for v in p["models"].values()) == pytest.approx(info["total"])


def test_warm_all_controls_have_no_history_decode_fitting_pricing_or_sources(tmp_path, monkeypatch):
    breakdown_home(tmp_path)
    first = render(tmp_path)
    assert first.breakdown_navigation["state"]["basis"] == "cycle"
    base = render_speed_report(tmp_path, range_name="all", project_keys=[], theme="day", timezone_name="UTC", now=AT)
    assert first.html.replace(first.html[first.html.index('<style>\n    .usage-breakdown'):first.html.index('<section class="section observed-speed"')], "") == base.html
    def forbidden(*args, **kwargs):
        raise AssertionError("warm control performed historical work")
    for name in ("codex_usage.breakdown_reports.prepare", "codex_usage.breakdown_reports.value_records",
                 "codex_usage.breakdown_reports.query_ledger_records", "codex_usage.allowance_queries.load_quota_evidence",
                 "codex_usage.allowance_index._decode_cached_report", "codex_usage.allowance_estimation.estimate_window",
                 "codex_usage.agent_reports.materialize_ledger", "codex_usage.pricing.estimate_cost"):
        monkeypatch.setattr(name, forbidden)
    assert render(tmp_path).html == first.html
    current = first
    for changes in ({"metric": "tokens"}, {"view": "project"}, {"metric": "cost"},
                    {"view": "hour"}, {"group": "project"}, {"day": "2026-10-08"},
                    {"day": "2026-10-09"}, {"basis": "selected", "day": "2026-10-09", "detail": ""}):
        requested = action(current, **changes)
        current = render(tmp_path, breakdown_action=json.dumps(requested))
        assert current.breakdown_navigation["state"] == requested["state"]
    project_action = next(a for a in current.breakdown_navigation["actions"] if a["state"]["detail"].startswith("project:"))
    current = render(tmp_path, breakdown_action=json.dumps(project_action))
    assert "Project hourly detail" in current.html
    hour_action = next(a for a in current.breakdown_navigation["actions"] if a["state"]["detail"].startswith("hour:"))
    assert "Hour detail" in render(tmp_path, breakdown_action=json.dumps(hour_action)).html


def test_command_shape_scope_stale_generation_and_no_resurrection(tmp_path):
    path = breakdown_home(tmp_path)
    first = render(tmp_path)
    requested = action(first, metric="tokens")
    for bad in ({**requested, "extra": True}, {**requested, "scope": "wrong"},
                {**requested, "state": {**requested["state"], "day": "2099-01-01"}}, []):
        with pytest.raises(ValueError):
            render(tmp_path, breakdown_action=json.dumps(bad))
    with open_ledger(path) as connection:
        connection.execute("update ledger_generations set status='superseded' where status='trusted'")
        increment_ledger_revision(connection)
        connection.commit()
    with pytest.raises(ValueError, match="Stale"):
        render(tmp_path, breakdown_action=json.dumps(requested))
    fresh = render(tmp_path)
    assert "Interval totals: 0 tokens" in fresh.html


def test_cycle_live_expiry_multi_series_slot_identity_and_rebase(tmp_path):
    path = breakdown_home(tmp_path)
    first = render(tmp_path)
    expired = render_ledger_report(tmp_path, range_name="all", project_keys=[], theme="day", timezone_name="UTC", now=AT + timedelta(hours=2))
    assert expired.breakdown_navigation["state"]["basis"] == "selected"
    assert "stale" in expired.html
    with open_ledger(path) as connection:
        status = allowance_status(connection, now=AT)
        bucket = status["active_buckets"][0]
        point = QuotaObservation(**bucket)
        rebase = replace(point, timestamp=(AT + timedelta(minutes=1)).isoformat(), resets_at=point.resets_at + 3600)
        store_read(connection, QuotaRead(rebase.timestamp, "pro", (rebase,)), None)
        increment_ledger_revision(connection)
        connection.commit()
        report = {"status": allowance_status(connection, now=AT + timedelta(minutes=1)), "paces": []}
        evidence = prepare_evidence(connection, report, AT + timedelta(minutes=1))
        assert evidence["cycle"]["boundary"] == "deadline rebase"
        assert evidence["cycle"]["start"] == rebase.timestamp
        other = replace(rebase, limit_id="other", slot="primary")
        store_read(connection, QuotaRead(rebase.timestamp, "pro", (rebase, other)), None)
        connection.commit()
        report["status"] = allowance_status(connection, now=AT + timedelta(minutes=1))
        assert prepare_evidence(connection, report, AT + timedelta(minutes=1))["cycle"] is None
    assert first.breakdown_navigation["state"]["basis"] == "cycle", "slot moves cannot split weekly identity"


def test_expired_deadline_and_duplicate_slot_aliases_are_not_nominal_cycles(tmp_path):
    path = breakdown_home(tmp_path)
    with open_ledger(path) as connection:
        bucket = allowance_status(connection, now=AT)["active_buckets"][0]
        point = QuotaObservation(**bucket)
        store_read(connection, QuotaRead(AT.isoformat(), "pro", (point, replace(point, slot="secondary"))), None)
        increment_ledger_revision(connection)
        connection.commit()
    assert render(tmp_path).breakdown_navigation["state"]["basis"] == "cycle"
    with open_ledger(path) as connection:
        point = replace(point, timestamp=(AT + timedelta(minutes=1)).isoformat(), resets_at=int((AT + timedelta(minutes=5)).timestamp()))
        store_read(connection, QuotaRead(point.timestamp, "pro", (point,)), None)
        increment_ledger_revision(connection)
        connection.commit()
    first = render_ledger_report(tmp_path, range_name="all", project_keys=[], theme="day", timezone_name="UTC", now=AT + timedelta(minutes=1))
    requested = action(first, metric="tokens")
    later = AT + timedelta(minutes=6)
    expired = render_ledger_report(tmp_path, range_name="all", project_keys=[], theme="day", timezone_name="UTC", now=later)
    assert expired.breakdown_navigation["state"]["basis"] == "selected"
    assert "deadline elapsed" in expired.html
    with pytest.raises(ValueError):
        render_ledger_report(tmp_path, range_name="all", project_keys=[], theme="day", timezone_name="UTC", now=later, breakdown_action=json.dumps(requested))


def test_transition_selection_and_coverage_remain_baseline_accounting(tmp_path):
    path = breakdown_home(tmp_path)
    with open_ledger(path) as connection:
        source = connection.execute("select project_key from ledger_projects where label='project-00'").fetchone()[0]
        connection.execute("""insert into ledger_transitions(owner_task_id,source_key,source_label,target_key,target_label,
            effective_from,confidence,evidence_json,task_ids_json) values ('synthetic-0',?,'project-00',
            'transition-target','Transition target',?,100,'[]','["synthetic-0"]')""", (source, (AT - timedelta(days=1)).isoformat()))
        increment_ledger_revision(connection)
        connection.commit()
    selected = render_ledger_report(tmp_path, range_name="all", project_keys=["transition-target"], theme="day", timezone_name="UTC", now=AT)
    assert "Transition target" in selected.html and "34% used" in selected.html
    disabled = render_ledger_report(tmp_path, range_name="all", project_keys=["transition-target"], theme="day", timezone_name="UTC", now=AT, auto_transitions=False)
    assert "Interval totals: 0 tokens" in disabled.html
    with open_ledger(path) as connection:
        connection.execute("update ledger_sources set is_stale=1")
        increment_ledger_revision(connection)
        connection.commit()
    partial = render(tmp_path)
    assert "Partial local baseline" in partial.html and "Incomplete ledger coverage" in partial.html


def test_positive_exact_hour_estimates_survive_composition_without_api_review_pricing():
    start = AT.replace(hour=11).timestamp()
    end = AT.timestamp()
    record = UsageRecord(AT - timedelta(minutes=30), TokenUsage(100, 0, 0, 0, 0, 100), "task", Path("synthetic"), "root", "gpt-6.1-sol", project_key="p", project_label="P")
    valued = value_records([record])
    cost = valued[0].summary.cost.total_usd
    reference = {"value": 100, "confidence": "Low/provisional", "available_at": AT.isoformat(), "plan": "pro", "end": AT.isoformat()}
    evidence = {"cycle": {"start": datetime.fromtimestamp(start, UTC).isoformat(), "end": AT.isoformat(), "plan": "pro", "full_at": None, "limit_id": "codex", "duration_minutes": 10080},
                "paces": [[{"method": "calibrated cost", "reference": reference, "anchor": end, "span_seconds": 3600, "cost": cost, "limit_id": "codex", "duration_minutes": 10080}]]}
    _, partitions = aggregate(valued, UTC, evidence, start=start, end=end, complete=True)
    calibration = partitions["day:2026-10-09"]["calibrations"][datetime.fromtimestamp(start, UTC).isoformat()]
    assert calibration["value"] == 100 and "retrospective" in calibration["reference_kind"]


def test_exact_interval_causal_calibration_and_cutoffs():
    start, end = AT.timestamp() - 3600, AT.timestamp()
    cycle = {"start": datetime.fromtimestamp(start, UTC).isoformat(), "end": AT.isoformat(), "plan": "pro", "full_at": None, "limit_id": "codex", "duration_minutes": 10080}
    ref = {"value": 100, "confidence": "Low/provisional", "available_at": AT.isoformat(), "plan": "pro", "end": AT.isoformat()}
    pace = {"method": "calibrated cost", "reference": ref, "anchor": end, "span_seconds": 3600, "cost": 5, "limit_id": "codex", "duration_minutes": 10080}
    evidence = {"cycle": cycle, "paces": [[pace]]}
    assert interval_calibration(evidence, start, end, 5, 0, True)["value"] == 100
    for field, mismatch in (("limit_id", "another-series"), ("duration_minutes", 300)):
        original = pace[field]
        pace[field] = mismatch
        assert interval_calibration(evidence, start, end, 5, 0, True)["value"] is None
        pace[field] = original
    for s, e, cost, unknown, complete in ((start+1, end, 5, 0, True), (start, end, 5, 1, True),
                                          (start, end, 5, 0, False), (start, end, 6, 0, True)):
        assert interval_calibration(evidence, s, e, cost, unknown, complete)["value"] is None
    ref["available_at"] = (AT + timedelta(seconds=1)).isoformat()
    assert interval_calibration(evidence, start, end, 5, 0, True)["value"] is None
    ref["available_at"] = AT.isoformat()
    cycle["full_at"] = end
    assert "cutoff" in interval_calibration(evidence, start, end, 5, 0, True)["reason"]


def test_account_meter_unfiltered_and_cache_partitioned(tmp_path):
    path = breakdown_home(tmp_path)
    render(tmp_path)
    with open_ledger(path, read_only=True) as connection:
        project = connection.execute("select project_key from ledger_projects limit 1").fetchone()[0]
        keys = [r[0] for r in connection.execute("select cache_key from rendered_reports where cache_key like 'breakdown:%'")]
        assert any(":day:" in k for k in keys) and any(":project:" in k for k in keys)
        metadata = load(connection, next(k for k in keys if k.endswith(":metadata")))
        assert "points" not in metadata["evidence"]
    filtered = render_ledger_report(tmp_path, range_name="all", project_keys=[project], theme="day", timezone_name="UTC", now=AT)
    assert "34% used" in filtered.html and "account-wide" in filtered.html
