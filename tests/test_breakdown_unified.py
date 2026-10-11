"""Unified calendar state, point identities, bounded reads and reversible drills."""
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from runpy import run_path
from unittest.mock import patch

import pytest

from codex_usage.agent_reports import render_ledger_report
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_store import store_read
from codex_usage.breakdown_display import identity, reduce_points
from codex_usage.breakdown_commands import BreakdownScopeExpired, receipt, RECEIPT_PREFIX
from codex_usage.breakdown_reports import load
from codex_usage.breakdown_state import validate_state
from codex_usage.ledger_schema import open_ledger, increment_ledger_revision

fixture = run_path(str(Path(__file__).resolve().parents[1] / "scripts/usage_breakdown_fixture.py"))
AT, breakdown_home = fixture["AT"], fixture["breakdown_home"]


def render(home, action=None, **kwargs):
    return render_ledger_report(home, range_name=kwargs.pop("range_name", "30d"), project_keys=[],
        theme="day", timezone_name="UTC", now=AT, breakdown_action=json.dumps(action) if action else None, **kwargs)


def move(home, report, **changes):
    desired = {**report.breakdown_navigation["state"], **changes}
    return render(home, next(a for a in report.breakdown_navigation["actions"] if a["state"] == desired))


@pytest.mark.parametrize("range_name,grain", [("today", "hourly"), ("yesterday", "hourly"),
    ("7d", "daily"), ("30d", "daily"), ("month", "daily"), ("all", "daily"), ("custom", "daily")])
def test_range_authority_defaults_and_one_plot(tmp_path, range_name, grain):
    breakdown_home(tmp_path)
    dates = {"start_date": "2026-09-01", "end_date": "2026-10-09"} if range_name == "custom" else {}
    report = render(tmp_path, range_name=range_name, **dates)
    state = report.breakdown_navigation["state"]
    assert state["basis"] == "selected" and state["grain"] == grain and state["overlay"] == "weekly"
    section = report.html.split('<section class="section usage-breakdown"', 1)[1].split('<section class="section observed-speed"', 1)[0]
    assert section.count("<svg") == 1 and section.count('aria-label="Time axis"') == 1
    assert "Current observed window" not in section and "Full-range daily context" not in section
    if range_name == "30d":
        assert "Selected range: 2026-09-10 to 2026-10-09" in section
    if range_name == "custom":
        assert "Selected range: 2026-09-01 to 2026-10-09" in section


def test_day_drill_daily_return_clears_dependent_detail_and_restores_domain(tmp_path):
    breakdown_home(tmp_path, days=12)
    first = render(tmp_path)
    drill = next(a for a in first.breakdown_navigation["actions"] if a["state"]["detail"] == "day:2026-10-01")
    hourly = render(tmp_path, drill)
    assert hourly.breakdown_navigation["state"]["grain"] == "hourly" and "Exact detail" in hourly.html
    daily = move(tmp_path, hourly, grain="daily", detail="")
    assert daily.breakdown_navigation["state"]["detail"] == ""
    assert "Exact detail" not in daily.html
    assert "Selected range: 2026-09-10 to 2026-10-09" in daily.html
    assert "Daily selected range" in daily.html


def test_same_slot_conflicts_preserve_every_raw_observation(tmp_path):
    path = breakdown_home(tmp_path)
    with open_ledger(path) as connection:
        for plan, used, duration in (("pro", 61, 10080), ("plus", 62, 10080), ("pro", 63, 300)):
            p = QuotaObservation(AT.isoformat(), "conflicting", "primary", plan, used, duration, int((AT+timedelta(days=4)).timestamp()))
            store_read(connection, QuotaRead(AT.isoformat(), plan, (p,)), None)
        increment_ledger_revision(connection)
        connection.commit()
    first = render(tmp_path)
    exact = move(tmp_path, first, detail="readings:2026-10-09")
    assert all(f"{float(used)!r}% used" in exact.html for used in (61, 62, 63))
    assert "Conflicting account readings" in first.html
    with open_ledger(path, read_only=True) as connection:
        key = connection.execute("select cache_key from rendered_reports where cache_key like 'breakdown:%:metadata'").fetchone()[0]
        raw = load(connection, load(connection, key)["account_prefix"] + "meter:2026-10-09")
        conflict = [p for p in raw if p["limit_id"] == "conflicting"]
        assert len(conflict) == len({identity(p) for p in conflict}) == 3


def test_visible_project_legend_and_stable_colors(tmp_path):
    breakdown_home(tmp_path, projects=13)
    first = move(tmp_path, render(tmp_path), group="project")
    section = first.html.split('<div class="ub-legend">', 1)[1].split('</div>', 1)[0]
    assert section.count("<span>") == 11 and "Other" in section
    assert "project-12" not in section
    second = move(tmp_path, first, grain="hourly", detail="")
    assert section == second.html.split('<div class="ub-legend">', 1)[1].split('</div>', 1)[0]
    third = move(tmp_path, second, metric="credits")
    assert third.breakdown_navigation["state"]["grain"] == "hourly" and third.breakdown_navigation["state"]["overlay"] == "weekly"


def test_usage_key_precedes_plot_and_account_key_is_separate(tmp_path):
    breakdown_home(tmp_path)
    report = render(tmp_path)
    section = report.html.split('<section class="section usage-breakdown"', 1)[1].split('<section class="section observed-speed"', 1)[0]
    assert section.count('<div class="ub-legend">') == 1
    assert section.index('<div class="ub-legend">') < section.index('<svg')
    assert "Weekly allowance remaining · account-wide · right axis" in section
    assert 'class="ub-legend ub-meter-legend"' in section


def test_free_auto_review_explanation_stays_in_folded_scope_evidence(tmp_path):
    breakdown_home(tmp_path)
    report = render(tmp_path)
    section = report.html.split('<section class="section usage-breakdown"', 1)[1]
    disclosure = section.split('<summary>Scope and continuity evidence</summary>', 1)[1].split('</details>', 1)[0]
    assert "codex-auto-review approval checks are free for ChatGPT subscription use" in disclosure
    assert "zero estimated credits, with tokens retained and API-excluded" in disclosure
    assert "Earlier review pricing remains unknown" in disclosure
    assert "<details open><summary>Scope and continuity evidence" not in section


def test_historical_only_project_evidence_never_issues_calendar_drill(tmp_path):
    path = breakdown_home(tmp_path, projects=2, days=2)
    with open_ledger(path) as connection:
        historical = connection.execute("select project_key from ledger_projects where label='project-01'").fetchone()[0]
        connection.execute("""delete from ledger_usage_events where timestamp >= '2026-10-09'
            and context_id in (select c.context_id from ledger_contexts c
                join ledger_projects p using(project_id) where p.project_key=?)""", (historical,))
        increment_ledger_revision(connection)
        connection.commit()

    def today(action=None):
        return render(tmp_path, action, range_name="today")

    first = today()
    found = False
    for action in first.breakdown_navigation["actions"]:
        if not action["state"]["detail"].startswith("evidence:"):
            continue
        inspected = today(action)
        if 'project-01 · No selected-range usage' not in inspected.html:
            continue
        found = True
        assert not any(a["state"]["project"] == historical for a in inspected.breakdown_navigation["actions"])
        assert "Selected range: 2026-10-09 to 2026-10-09" in inspected.html
        assert inspected.breakdown_navigation["state"]["basis"] == "selected"
        valid = next(a for a in inspected.breakdown_navigation["actions"] if a["state"]["project"])
        drilled = today(valid)
        assert "Usage detail: project-00" in drilled.html
        assert "Selected range: 2026-10-09 to 2026-10-09" in drilled.html
        forged = {**valid, "state": {**valid["state"], "project": historical}}
        with pytest.raises(ValueError):
            today(forged)
        break
    assert found, "Retained Oct8-only usage must appear in a historical evidence interval"


def test_native_synthetic_environment_excludes_inherited_credentials(tmp_path, monkeypatch):
    import sys
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    from check_usage_breakdown_webview import synthetic_host_environment
    source = {"PATH": "/usr/bin", "LANG": "en_US.UTF-8", "OPENAI_API_KEY": "private",
        "CODEX_HOME": "/live", "NODE_OPTIONS": "--require private", "HTTP_PROXY": "private"}
    environment = synthetic_host_environment(tmp_path, tmp_path / "codex", tmp_path / "rpc", tmp_path / "fixture", source)
    assert environment["PATH"] == "/usr/bin"
    assert environment["CODEX_HOME"] == str(tmp_path / "codex")
    assert not {"OPENAI_API_KEY", "NODE_OPTIONS", "HTTP_PROXY"} & environment.keys()
    assert "check_usage_breakdown_webview" in sys.modules


def test_dense_actual_points_and_boundaries_are_not_averaged():
    start = AT.timestamp()
    points = [{"timestamp": (AT+timedelta(seconds=i)).isoformat(), "limit_id": "codex",
        "slot": "primary", "plan": "pro", "duration_minutes": 10080,
        "used_percent": i/2000, "resets_at": int(start+200000), "provenance": "synthetic"}
        for i in range(158249)]
    reduced = reduce_points(points, "weekly", start, start+158250, detect_boundaries=True)
    assert len(reduced) <= 720
    assert all(identity(p) in {identity(points[int(datetime.fromisoformat(p["timestamp"]).timestamp()-start)])} for p in reduced)
    assert reduced[0]["timestamp"] == points[0]["timestamp"] and reduced[-1]["timestamp"] == points[-1]["timestamp"]
    points[80000] = {**points[80000], "used_percent": 1}
    points.append({**points[80000], "plan": "plus", "used_percent": 2})
    reduced = reduce_points(points, "weekly", start, start+158250, detect_boundaries=True)
    assert any(p["plan"] == "plus" for p in reduced)
    assert any(p["timestamp"] == points[79999]["timestamp"] for p in reduced)
    assert any(p["timestamp"] == points[80000]["timestamp"] and p["plan"] == "pro" for p in reduced)


def test_hourly_reads_only_seven_day_project_partitions(tmp_path):
    breakdown_home(tmp_path, days=30)
    first = render(tmp_path)
    selected = next(a for a in first.breakdown_navigation["actions"] if a["state"]["project"])
    current = render(tmp_path, selected)
    original = load
    reads = []
    def track(connection, key):
        reads.append(key)
        return original(connection, key)
    with patch("codex_usage.breakdown_reports.load", track):
        move(tmp_path, current, grain="hourly", detail="")
    days = [k for k in reads if ":day:" in k and ":project:" in k]
    assert len(days) <= 7
    assert not any(":selected:project:" in k for k in reads)


def test_old_issued_schema_is_typed_expiry_not_reinterpreted(tmp_path):
    path = breakdown_home(tmp_path)
    old = {"scope": "b"*64, "state": {"basis": "cycle", "view": "hour", "metric": "cost", "group": "model", "day": "2026-10-09", "detail": ""}}
    with open_ledger(path) as connection:
        connection.execute("insert into rendered_reports values (?,?,?,?,?)", (RECEIPT_PREFIX+old["scope"], 0, "test", datetime.now(UTC).isoformat(), json.dumps(receipt([old]))))
        connection.commit()
    with pytest.raises(BreakdownScopeExpired):
        render(tmp_path, old)
    for changed in ({"basis": "cycle"}, {"grain": "weekly"}, {"overlay": "both"}, {"extra": ""}):
        with pytest.raises(ValueError):
            validate_state({**render(tmp_path).breakdown_navigation["state"], **changed})
