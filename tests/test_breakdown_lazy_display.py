"""Lazy views retain the eager reducer's exact output and boundary semantics."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import random
from runpy import run_path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from codex_usage import breakdown_reports as reports
from codex_usage.agent_reports import render_ledger_report
from codex_usage.allowance_credits import CreditBalance
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_store import store_read
from codex_usage.breakdown_display import display_partitions
from codex_usage.breakdown_readings import display_day, partition_readings
from codex_usage.ledger_schema import increment_ledger_revision, open_ledger

fixture = run_path(str(Path(__file__).resolve().parents[1] / "scripts/usage_breakdown_fixture.py"))
AT, breakdown_home = fixture["AT"], fixture["breakdown_home"]


@pytest.mark.parametrize("kind", ["weekly", "balance"])
@pytest.mark.parametrize("zone", ["UTC", "America/Toronto", "Pacific/Chatham"])
@pytest.mark.parametrize("start", [datetime(2026, 10, 28, tzinfo=UTC), datetime(2026, 3, 4, tzinfo=UTC)])
def test_each_lazy_day_equals_full_history_with_conflicts_gaps_and_dst(kind, zone, start):
    timezone = ZoneInfo(zone)
    points = []
    for i in range(800):
        # Equal timestamps, missing days, nonchronological input, plan changes,
        # invalid balances, resets, small corrections and multiple series.
        at = start + timedelta(hours=i // 2 + (48 if i > 300 else 0))
        if i % 3:
            at = at.astimezone(ZoneInfo("Asia/Kolkata"))
        point = {"timestamp": at.isoformat(), "plan": "pro" if i % 43 else "plus"}
        if kind == "weekly":
            point.update(limit_id="codex" if i % 7 else "review", slot="primary",
                duration_minutes=10080 if i % 11 else 300, used_percent=i % 100,
                resets_at=int((start + timedelta(days=7 * (i // 100 + 1))).timestamp()),
                reset_credits=i // 40, provenance="Live probe")
        else:
            point.update(balance=str(1000 - i) if i % 17 else None,
                unlimited=i % 19 == 0, diagnostic="invalid" if i % 23 == 0 else "",
                change="-1" if i % 31 else None, origin=(at - timedelta(hours=1)).isoformat())
        points.append(point)
    points.extend(deepcopy(points[:20]))
    random.Random(7).shuffle(points)
    original = deepcopy(points)
    expected = display_partitions(points, kind, timezone)
    days, extent, partitions = partition_readings(points, kind, timezone)
    assert len(days) > 10 and extent[0] < extent[1]
    assert all("-display:" not in key for key in partitions)
    for key, value in expected.items():
        assert display_day(key, timezone, partitions.get) == value
    assert points == original


def test_cross_midnight_and_sparse_series_neighbors_are_not_lost():
    points = [dict(timestamp=at, limit_id=limit, slot="secondary", plan="pro",
        used_percent=used, duration_minutes=10080, resets_at=42) for at, limit, used in (
        ("2026-10-01T23:59:00+00:00", "codex", 99),
        ("2026-10-02T00:00:00+00:00", "codex", 0),
        ("2026-10-02T12:00:00+00:00", "codex", 50),
        ("2026-10-08T00:00:00+00:00", "codex", 49),
        ("2026-10-01T12:00:00+00:00", "review", 100),
        ("2026-10-08T00:00:00+00:00", "review", 0))]
    _, _, partitions = partition_readings(points, "weekly", UTC)
    for name, expected in display_partitions(points, "weekly", UTC).items():
        assert display_day(name, UTC, partitions.get) == expected
    assert display_day("meter-display:2026-10-03", UTC, partitions.get) == {"count": 0, "points": []}
    assert all(p.get("_boundary") for p in
        display_day("meter-display:2026-10-08", UTC, partitions.get)["points"])


def render(home, range_name="today", **kwargs):
    return render_ledger_report(home, range_name=range_name, project_keys=kwargs.pop("project_keys", []),
        theme="night", timezone_name=kwargs.pop("timezone_name", "UTC"), now=AT, **kwargs)


def test_report_prepares_only_requested_days_and_caches_each_overlay(tmp_path):
    breakdown_home(tmp_path, extended=True, days=12)
    with patch.object(reports, "display_day", wraps=reports.display_day) as display:
        first = render(tmp_path)
        assert [c.args[0] for c in display.call_args_list] == ["meter-display:2026-10-09"]
        display.reset_mock()
        assert render(tmp_path).html == first.html
        assert display.call_count == 0
        render(tmp_path, "yesterday")
        assert [c.args[0] for c in display.call_args_list] == ["meter-display:2026-10-08"]
        display.reset_mock()
        action = next(a for a in first.breakdown_navigation["actions"] if a["state"]["overlay"] == "balance")
        balance = render(tmp_path, breakdown_action=json.dumps(action))
        assert [c.args[0] for c in display.call_args_list] == ["balance-display:2026-10-09"]
        display.reset_mock()
        assert render(tmp_path, breakdown_action=json.dumps(action)).html == balance.html
        assert display.call_count == 0


def test_late_historical_reading_rebuilds_context_under_new_revision(tmp_path):
    path = breakdown_home(tmp_path, extended=True)
    before = render(tmp_path, "yesterday")
    late = AT - timedelta(days=1, hours=1)
    with open_ledger(path) as connection:
        point = QuotaObservation(late.isoformat(), "codex", "secondary", "pro", 2, 10080, 42)
        store_read(connection, QuotaRead(late.isoformat(), "pro", (point,),
            credits=CreditBalance("19.000000000000000001", True, False)), None)
        increment_ledger_revision(connection)
        connection.commit()
    with patch.object(reports, "display_day", wraps=reports.display_day) as display:
        after = render(tmp_path, "yesterday")
        assert display.call_count == 1 and not after.cache_hit
    assert after.breakdown_navigation["scope"] != before.breakdown_navigation["scope"]
    with open_ledger(path, read_only=True) as connection:
        rows = connection.execute("select html from rendered_reports where cache_key like 'breakdown-account:%:meter-display:2026-10-08'")
        assert any(any(p["timestamp"] == late.isoformat() and p.get("_boundary")
            for p in json.loads(row[0])["points"]) for row in rows)


def test_lazy_display_write_rejects_capture_advancement(tmp_path):
    path = breakdown_home(tmp_path, extended=True)
    first = render(tmp_path)
    original = reports.display_day
    def advancing(*args):
        data = original(*args)
        with open_ledger(path) as writer:
            increment_ledger_revision(writer)
            writer.commit()
        return data
    with patch.object(reports, "display_day", advancing):
        pinned = render(tmp_path, "yesterday")
    assert pinned.ledger_revision == first.ledger_revision
    with open_ledger(path, read_only=True) as connection:
        assert not connection.execute("select 1 from rendered_reports where cache_key like '%:meter-display:2026-10-08'").fetchone()
    current = render(tmp_path, "yesterday")
    assert current.ledger_revision > pinned.ledger_revision


def test_display_cache_shared_across_projects_ranges_but_not_timezones(tmp_path):
    path = breakdown_home(tmp_path, extended=True)
    render(tmp_path)
    with patch.object(reports, "display_day", side_effect=AssertionError("Account display rebuilt for project")):
        render(tmp_path, project_keys=["nonexistent"])
    with patch.object(reports, "display_day", wraps=reports.display_day) as display:
        render(tmp_path, timezone_name="America/Toronto")
        assert [c.args[0] for c in display.call_args_list] == ["meter-display:2026-10-09"]
        display.reset_mock()
        render(tmp_path, "all")
        assert display.call_count > 0
        assert "meter-display:2026-10-09" not in [c.args[0] for c in display.call_args_list]
    with open_ledger(path, read_only=True) as connection:
        assert connection.execute("select count(*) from rendered_reports where cache_key like 'breakdown-account:%:meter-display:2026-10-09'").fetchone()[0] == 2
