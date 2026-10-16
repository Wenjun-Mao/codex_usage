"""Historical portions, prospective balance adjacency and zero warm work."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
from runpy import run_path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from codex_usage.agent_reports import render_ledger_report
from codex_usage.allowance_credits import CreditBalance, credit_history
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_store import store_read
from codex_usage.breakdown_balances import prepare_balances, balance_partitions
from codex_usage.breakdown_reports import load
from codex_usage.report_breakdown_balances import balances
from codex_usage.ledger_schema import open_ledger, increment_ledger_revision

fixture = run_path(str(Path(__file__).resolve().parents[1] / "scripts/usage_breakdown_fixture.py"))
AT, breakdown_home = fixture["AT"], fixture["breakdown_home"]


def render(home, action=None, *, now=AT, keys=None):
    return render_ledger_report(home, range_name="all", project_keys=keys or [], theme="day",
        timezone_name="UTC", now=now, breakdown_action=json.dumps(action) if action else None)


def read(connection, at, credit, *, plan="pro", used=100, deadline=None):
    point = QuotaObservation(at.isoformat(), "codex", "primary", plan, used, 10080,
        deadline or int((AT+timedelta(days=4)).timestamp()))
    store_read(connection, QuotaRead(at.isoformat(), plan, (point,), credits=credit), None)


def test_full_retained_balances_not_bounded_ui_and_reset_continuity(tmp_path):
    path = breakdown_home(tmp_path)
    with open_ledger(path) as connection:
        for i in range(110):
            read(connection, AT+timedelta(hours=i), CreditBalance(
                format(Decimal("100.000000000000000001")-i*Decimal(".1"), "f"), True, False),
                used=100 if i < 50 else 0,
                deadline=int((AT+timedelta(hours=50 if i < 50 else 218)).timestamp()))
        points = prepare_balances(connection)
        assert len(credit_history(connection)["observations"]) == 100
        assert len(points) == 117
        assert points[-1]["change"] == "-0.100000000000000000"
        assert points[57]["change"] == "-0.100000000000000000", "quota reset must not break balance adjacency"
        assert points[7]["change"] is None, "old missing-read placeholder breaks delta"


@pytest.mark.parametrize("middle", [None, CreditBalance(diagnostic="invalid_credit_balance"),
    CreditBalance("90", True, True)])
def test_missing_invalid_unlimited_break_both_adjacent_deltas(tmp_path, middle):
    with open_ledger(breakdown_home(tmp_path)) as connection:
        for i, credit in enumerate((CreditBalance("100", True, False), middle, CreditBalance("80", True, False))):
            read(connection, AT+timedelta(hours=i), credit)
        points = prepare_balances(connection)
        assert points[-2]["change"] is points[-1]["change"] is None


def test_plans_increases_exact_endpoints_and_boundary_crossing(tmp_path):
    with open_ledger(breakdown_home(tmp_path)) as connection:
        opening = AT-timedelta(hours=14)
        for at, credit, plan in ((opening, "10.000000000000000001", "pro"),
            (AT, "9.999999999999999999", "pro"), (AT+timedelta(hours=1), "20", "pro"),
            (AT+timedelta(hours=2), "19", "plus"), (AT+timedelta(hours=3), "18", "")):
            read(connection, at, CreditBalance(credit, True, False), plan=plan)
        points = prepare_balances(connection)[-5:]
    assert points[1]["change"] == "-0.000000000000000002"
    assert points[2]["change"] == "10.000000000000000001"
    assert points[3]["change"] is points[4]["change"] is None
    partition = balance_partitions(points, UTC)
    assert points[1] in partition["balance:2026-10-08"] and points[1] in partition["balance:2026-10-09"]
    rendered = balances(points, AT.timestamp()-3600, AT.timestamp()+7200, UTC)
    assert opening.isoformat()+" to "+AT.isoformat() in rendered
    assert "boundary-crossing, unallocatable" in rendered
    assert "Net decrease -0.000000000000000002" in rendered
    assert "Increase +10.000000000000000001" in rendered


def test_dated_scopes_stale_anchor_and_original_event_membership(tmp_path):
    path = breakdown_home(tmp_path, extended=True, days=12)
    first = render(tmp_path)
    with open_ledger(path, read_only=True) as connection:
        key = connection.execute("select cache_key from rendered_reports where cache_key like 'breakdown:%:metadata'").fetchone()[0]
        metadata = load(connection, key)
        assert len(metadata["evidence"]["windows"]) == 2
        for basis, window in metadata["evidence"]["windows"].items():
            assert "projects" not in metadata["ranges"][basis] and "daily" not in metadata["ranges"][basis]
            issued = next(a for a in first.breakdown_navigation["actions"] if a["state"]["detail"] == "evidence:" + basis)
            render(tmp_path, issued)
            info = load(connection, metadata["history_prefix"] + basis + ":summary")
            lo, hi = (round(datetime.fromisoformat(window[k]).timestamp()*1e6) for k in ("start", "end"))
            tokens = connection.execute("select sum(total_tokens) from ledger_usage_events where timestamp_us>? and timestamp_us<=?", (lo, hi)).fetchone()[0] or 0
            assert info["total"]["tokens"] == tokens
            assert info["causal"]
        assert "balances" not in metadata["evidence"]
    stale = render(tmp_path, now=AT+timedelta(hours=2))
    actions = [a for a in stale.breakdown_navigation["actions"] if a["state"]["basis"].startswith("window:")]
    assert len(actions) == 0 and stale.breakdown_navigation["state"]["basis"] == "selected"
    assert "observed continuity fragment" not in stale.html
    audit = next(a for a in stale.breakdown_navigation["actions"] if a["state"]["detail"].startswith("evidence:"))
    historical = render(tmp_path, audit, now=AT+timedelta(hours=2))
    assert "scheduled reset" in historical.html
    assert "codex / pro" in historical.html and "observed continuity fragment" in historical.html
    with pytest.raises(ValueError, match="expired"):
        render(tmp_path, next(a for a in first.breakdown_navigation["actions"] if a["state"]["metric"] == "credits"), now=AT+timedelta(hours=2))


def test_zero_warm_historical_work_all_windows_metrics_groups_drills(tmp_path):
    breakdown_home(tmp_path, extended=True, days=12)
    first = render(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("historical work during warm navigation")
    from contextlib import ExitStack
    with ExitStack() as stack:
        for name in ("breakdown_reports.prepare", "breakdown_reports.value_records", "breakdown_reports.query_ledger_records",
            "allowance_queries.load_quota_evidence", "allowance_index._decode_cached_report", "allowance_estimation.estimate_window",
            "agent_reports.materialize_ledger", "pricing.estimate_cost", "allowance_preparation.prepare_pace_evidence",
            "breakdown_evidence.prepare_balances", "breakdown_preparation.balance_partitions"):
            stack.enter_context(patch("codex_usage."+name, forbidden))
        from codex_usage.breakdown_reports import load as original_load
        reads = []
        def bounded_load(connection, key):
            reads.append(key)
            return original_load(connection, key)
        stack.enter_context(patch("codex_usage.breakdown_reports.load", bounded_load))
        current = first
        for issued in [a for a in first.breakdown_navigation["actions"] if a["state"]["detail"].startswith("day:")]:
            current = render(tmp_path, issued)
            for metric in ("credits", "tokens", "cost"):
                for view in ("project", "time"):
                    for key, value in (("metric", metric), ("view", view), ("group", "project")):
                        if key != "group" or current.breakdown_navigation["state"]["view"] == "time":
                            reads.clear()
                            action = next(a for a in current.breakdown_navigation["actions"] if a["state"] == {**current.breakdown_navigation["state"], key: value})
                            current = render(tmp_path, action)
                            summaries = [k for k in reads if k.endswith(":summary") and k.startswith("breakdown:")]
                            assert len(summaries) == 1 and issued["state"]["basis"] in summaries[0]
            for changes in ({"grain": "hourly", "detail": ""}, {"overlay": "balance"}):
                action = next(a for a in current.breakdown_navigation["actions"] if a["state"] == {**current.breakdown_navigation["state"], **changes})
                current = render(tmp_path, action)
            for predicate in (lambda s: bool(s["project"]), lambda s: s["detail"].startswith("hour:")):
                current = render(tmp_path, next(a for a in current.breakdown_navigation["actions"] if predicate(a["state"])))
        current = render(tmp_path, next(a for a in current.breakdown_navigation["actions"] if a["state"]["detail"] == "readings:" + current.breakdown_navigation["state"]["day"]))
        assert "Exact balances and net-change intervals" in current.html


def test_balances_independent_of_project_selection(tmp_path):
    breakdown_home(tmp_path, extended=True)
    unfiltered = render(tmp_path)
    filtered = render(tmp_path, keys=["nonexistent-synthetic"])
    def block(report, keys):
        report = render(tmp_path, next(a for a in report.breakdown_navigation["actions"] if a["state"]["overlay"] == "balance"), keys=keys)
        report = render(tmp_path, next(a for a in report.breakdown_navigation["actions"] if a["state"]["detail"] == "readings:" + report.breakdown_navigation["state"]["day"]), keys=keys)
        return report.html.split("<summary>Exact balances and net-change intervals", 1)[1].split("</details>", 1)[0]
    assert block(unfiltered, []) == block(filtered, ["nonexistent-synthetic"])


@pytest.mark.parametrize("zone", ["America/Toronto", "Pacific/Chatham"])
def test_balance_intervals_partition_local_dst_days_without_delta_allocation(tmp_path, zone):
    with open_ledger(breakdown_home(tmp_path)) as connection:
        for at, value in ((datetime(2026,11,1,3,tzinfo=UTC), "2"), (datetime(2026,11,2,8,tzinfo=UTC), "1")):
            read(connection, at, CreditBalance(value, True, False))
        points = prepare_balances(connection)[-2:]
    partitions = balance_partitions(points[1:], ZoneInfo(zone))
    for rows in partitions.values():
        assert rows[-1]["change"] == "-1" and rows[-1]["origin"] == points[0]["timestamp"]


def test_no_current_and_ambiguous_conflict_portions_remain_accessible(tmp_path):
    path = breakdown_home(tmp_path, extended=True)
    with open_ledger(path) as connection:
        read(connection, AT, None, plan="plus", used=75)
        increment_ledger_revision(connection)
        connection.commit()
    first = render(tmp_path)
    assert first.breakdown_navigation["state"]["basis"] == "selected"
    assert "Scope and continuity evidence" not in first.html
    actions = [a for a in first.breakdown_navigation["actions"] if a["state"]["basis"].startswith("window:")]
    assert not actions
    with open_ledger(path, read_only=True) as connection:
        key = connection.execute("select cache_key from rendered_reports where cache_key like 'breakdown:%:metadata'").fetchone()[0]
        windows = load(connection, key)["evidence"]["windows"]
        conflicts = [w for w in windows.values() if w["ambiguous"]]
        assert conflicts and all(w["plan"] == "" for w in conflicts), "do not choose a plan for conflicting captures"
    audits = [a for a in first.breakdown_navigation["actions"]
              if a["state"]["detail"] in {"evidence:" + k for k, w in windows.items() if w["ambiguous"]}]
    assert audits
    for audit in audits:
        inspected = render(tmp_path, audit)
        assert inspected.breakdown_navigation["state"] == audit["state"]
        assert "observation conflict" in inspected.html


def test_mixed_offsets_and_equivalent_instants_never_create_false_debit(tmp_path):
    with open_ledger(breakdown_home(tmp_path)) as connection:
        for stamp, value in (("2026-10-09T12:00:00+00:00", "100"),
            ("2026-10-09T08:30:00-04:00", "99"),
            ("2026-10-09T13:30:00+01:00", "98"),
            ("2026-10-09T13:00:00+00:00", "97")):
            read(connection, datetime.fromisoformat(stamp), CreditBalance(value, True, False))
        points = prepare_balances(connection)[-4:]
    assert points[1]["change"] == "-1"
    assert points[2]["change"] is None and points[2]["reason"] == "nonchronological captures"
    assert points[3]["change"] == "-1"


def test_large_balance_small_episode_visible_and_spanning_state():
    points = [{"timestamp": (AT+timedelta(hours=i)).isoformat(), "origin": (AT+timedelta(hours=i-1)).isoformat() if i else None,
        "balance": str(62500-i*250), "change": "-250" if i else None,
        "plan": "pro", "unlimited": False, "diagnostic": "", "reason": "first capture"} for i in range(3)]
    document = balances(points, AT.timestamp(), AT.timestamp()+7200, UTC)
    assert "balance 62000 credits" in document and "balance 62500 credits" in document
    assert "<svg" not in document
    assert "Net decrease -250" in document
    spanning = balances(points[1:], AT.timestamp()+600, AT.timestamp()+3000, UTC)
    assert "No in-domain balance captures" in spanning and "boundary-crossing, unallocatable" in spanning
    assert "no captures or spanning evidence" in balances([], AT.timestamp(), AT.timestamp()+3000, UTC)


@pytest.mark.parametrize("unlimited", [False, True])
def test_unknown_or_unlimited_raw_captures_are_not_zero_or_absent(unlimited):
    points = [{"timestamp": AT.isoformat(), "origin": None, "balance": None,
        "change": None, "plan": "pro", "unlimited": unlimited, "diagnostic": "",
        "reason": "first retained capture"}]
    document = balances(points, AT.timestamp()-1, AT.timestamp()+1, UTC)
    assert "No finite valid balances among in-domain captures" in document
    assert "No in-domain balance captures" not in document
    assert "<svg" not in document
    assert "<span>0</span>" not in document and "observed range 0 to 0" not in document
    assert "Unknown: first retained capture" in document
    assert ("Unlimited" if unlimited else "balance Unknown") in document


def test_singleton_midnight_scope_and_localized_picker_summary(tmp_path):
    path = breakdown_home(tmp_path)
    local_midnight = datetime(2026,10,9,tzinfo=ZoneInfo("America/Toronto"))
    with open_ledger(path) as connection:
        read(connection, local_midnight, None, plan="plus")
        increment_ledger_revision(connection)
        connection.commit()
    def local_render(action=None):
        return render_ledger_report(tmp_path, range_name="all", project_keys=[], theme="day",
            timezone_name="America/Toronto", now=AT,
            breakdown_action=json.dumps(action) if action else None)
    first = local_render()
    historical = next(a for a in first.breakdown_navigation["actions"] if a["state"]["detail"].startswith("day:") and a["state"]["day"] == "2026-10-09")
    with open_ledger(path, read_only=True) as connection:
        key = connection.execute("select cache_key from rendered_reports where cache_key like 'breakdown:%:metadata'").fetchone()[0]
        metadata = load(connection, key)
        singleton = next((basis, window) for basis, window in metadata["evidence"]["windows"].items() if window["start"] == window["end"])
        info = metadata["ranges"][singleton[0]]
        assert info["latest_day"] == info["min_date"] == info["max_date"] == "2026-10-09"
    report = local_render(historical)
    assert "Selected range: 2026-10-05 to 2026-10-09" in report.html
    older = next(a for a in first.breakdown_navigation["actions"] if a["state"]["detail"].startswith("day:") and a["state"]["day"] == "2026-10-08")
    assert "Selected range: 2026-10-05 to 2026-10-09" in local_render(older).html


def test_backwards_origin_across_days_keeps_actual_raw_capture(tmp_path):
    with open_ledger(breakdown_home(tmp_path)) as connection:
        for stamp, value in (("2026-10-10T01:00:00+00:00", "100"), ("2026-10-09T23:00:00+00:00", "99")):
            read(connection, datetime.fromisoformat(stamp), CreditBalance(value, True, False))
        point = prepare_balances(connection)[-1]
    assert point["change"] is None and point["reason"] == "nonchronological captures"
    for zone_name, day in (("UTC", "2026-10-09"), ("Asia/Tokyo", "2026-10-10")):
        zone = ZoneInfo(zone_name)
        partition = balance_partitions([point], zone)["balance:"+day]
        start = datetime.fromisoformat(day).replace(tzinfo=zone).timestamp()
        stop = (datetime.fromisoformat(day).replace(tzinfo=zone)+timedelta(days=1)).timestamp()
        document = balances(partition, start, stop, zone)
        assert "balance 99 credits" in document and "<svg" not in document
        assert "nonchronological captures" in document and "No in-domain" not in document
        assert 'stroke-dasharray="3 3"' not in document


def test_history_not_valued_until_inspected_and_current_alias_reuses_composition(tmp_path):
    path = breakdown_home(tmp_path, extended=True, days=30)
    import codex_usage.breakdown_reports as reports
    with patch.object(reports, "query_ledger_records", wraps=reports.query_ledger_records) as queries, \
         patch.object(reports, "value_records", wraps=reports.value_records) as valuations, \
         patch.object(reports, "aggregate", wraps=reports.aggregate) as aggregates:
        first = render_ledger_report(tmp_path, range_name="today", project_keys=[], theme="day", timezone_name="UTC", now=AT)
    assert queries.call_count == valuations.call_count == 0
    assert aggregates.call_count == 1
    with open_ledger(path, read_only=True) as connection:
        key = connection.execute("select cache_key from rendered_reports where cache_key like 'breakdown:%:metadata'").fetchone()[0]
        metadata = load(connection, key)
        assert metadata["ranges"]["cycle"]["partition_basis"].startswith("window:")
        assert not connection.execute("select 1 from rendered_reports where cache_key=?", (key[:-len("metadata")]+"cycle:summary",)).fetchone()
        assert not connection.execute("select 1 from rendered_reports where cache_key like 'breakdown-history:%'").fetchone()
    basis = metadata["ranges"]["cycle"]["partition_basis"]
    issued = next(a for a in first.breakdown_navigation["actions"] if a["state"]["detail"] == "evidence:" + basis)
    with patch.object(reports, "query_ledger_records", wraps=reports.query_ledger_records) as queries, \
         patch.object(reports, "value_records", wraps=reports.value_records) as valuations:
        def today():
            return render_ledger_report(tmp_path, range_name="today", project_keys=[], theme="day",
                timezone_name="UTC", now=AT, breakdown_action=json.dumps(issued))
        inspected = today()
        assert today().html == inspected.html
    assert queries.call_count == valuations.call_count == 1
    bounds = queries.call_args.kwargs["bounds"]
    assert bounds.start_us == round(metadata["ranges"][basis]["start"]*1e6)+1
    assert bounds.end_us == round(metadata["ranges"][basis]["end"]*1e6)+1


@pytest.mark.parametrize("reset_hour", [0, 6, 12])
def test_balance_interval_not_cut_at_quota_reset(tmp_path, reset_hour):
    with open_ledger(breakdown_home(tmp_path)) as connection:
        read(connection, AT, CreditBalance("62500.000000000000000001", True, False),
            deadline=int((AT+timedelta(hours=reset_hour)).timestamp()))
        read(connection, AT+timedelta(hours=12), CreditBalance("62000.000000000000000001", True, False),
            used=0, deadline=int((AT+timedelta(days=7)).timestamp()))
        point = prepare_balances(connection)[-1]
    assert point["change"] == "-500.000000000000000000"
    assert point["origin"] == AT.isoformat()
    document = balances([point], AT.timestamp()+3600, AT.timestamp()+36000, UTC)
    assert "boundary-crossing, unallocatable" in document
    assert AT.isoformat()+" to "+(AT+timedelta(hours=12)).isoformat() in document


def test_original_historical_opening_excluded_and_closing_event_included(tmp_path):
    path = breakdown_home(tmp_path, extended=True, days=12)
    start, end = AT-timedelta(days=10), AT-timedelta(days=8)
    with open_ledger(path) as connection:
        first = connection.execute("select event_id,total_tokens from ledger_usage_events order by timestamp_us limit 1").fetchone()
        last = connection.execute("select event_id,total_tokens from ledger_usage_events order by timestamp_us desc limit 1").fetchone()
        for event, at in ((first, start), (last, end)):
            connection.execute("update ledger_usage_events set timestamp=?,timestamp_us=? where event_id=?", (at.isoformat(), round(at.timestamp()*1e6), event[0]))
        expected = connection.execute("select sum(total_tokens) from ledger_usage_events where timestamp_us>? and timestamp_us<=?", (round(start.timestamp()*1e6),round(end.timestamp()*1e6))).fetchone()[0]
        increment_ledger_revision(connection)
        connection.commit()
    first_report = render(tmp_path)
    with open_ledger(path, read_only=True) as connection:
        key = connection.execute("select cache_key from rendered_reports where cache_key like 'breakdown:%:metadata'").fetchone()[0]
        metadata = load(connection, key)
        windows = metadata["evidence"]["windows"]
        basis = next(b for b,w in windows.items() if w["start"] == start.isoformat())
        issued = next(a for a in first_report.breakdown_navigation["actions"] if a["state"]["detail"] == "evidence:" + basis)
        render(tmp_path, issued)
        summary = load(connection, metadata["history_prefix"]+basis+":summary")
        assert summary["total"]["tokens"] == expected
        rows = [r for day in summary["daily"] for r in load(connection, metadata["history_prefix"]+basis+":day:"+day)["rows"]]
        assert sum(r["tokens"] for r in rows) == expected
        assert last[1] > 0 and first[1] > 0


def test_credit_ranking_known_free_zero_unknown_and_included_usage():
    from codex_usage.aggregation import value_records
    from codex_usage.breakdown_aggregation import aggregate, ranked_projects, total
    from codex_usage.models import UsageRecord, TokenUsage
    records = [UsageRecord(AT, TokenUsage(100,0,0,0,0,100), "task", Path("synthetic"), "root", model,
        project_key=key, project_label=key) for key, model in
        (("free", "codex-auto-review"), ("unknown", "unknown-synthetic"), ("included", "gpt-6.1-sol"))]
    info, _ = aggregate(value_records(records), UTC, {"cycle": None, "paces": []}, start=AT.timestamp(), end=AT.timestamp()+1, complete=True)
    ranked = ranked_projects(info["projects"], "credits")
    assert [key for key,_ in ranked] == ["included", "free", "unknown"]
    values = {key: total(project["models"].values()) for key, project in ranked}
    assert values["included"]["credits"] > 0
    assert values["free"]["credits"] == values["free"]["credit_unknown"] == 0
    assert values["unknown"]["credits"] == 0 and values["unknown"]["credit_unknown"] == 100


def test_latest_unavailable_read_does_not_hide_retained_weekly_portions(tmp_path):
    path = breakdown_home(tmp_path, extended=True)
    with open_ledger(path) as connection:
        store_read(connection, QuotaRead((AT+timedelta(minutes=1)).isoformat(), "pro", ()), None)
        increment_ledger_revision(connection)
        connection.commit()
    first = render(tmp_path, now=AT+timedelta(minutes=1))
    assert first.breakdown_navigation["state"]["basis"] == "selected"
    actions = [a for a in first.breakdown_navigation["actions"] if a["state"]["basis"].startswith("window:")]
    assert len(actions) == 0
    assert all(render(tmp_path, action, now=AT+timedelta(minutes=1)).breakdown_navigation["state"] == action["state"] for action in actions)


@pytest.mark.parametrize("keys", [[], ["nonexistent-synthetic"]])
def test_selected_month_opens_actual_latest_day_not_calendar_end(tmp_path, keys):
    path = breakdown_home(tmp_path, extended=True)
    def month(action=None):
        return render_ledger_report(tmp_path, range_name="month", project_keys=keys, theme="day",
            timezone_name="UTC", now=AT, breakdown_action=json.dumps(action) if action else None)
    first = month()
    selected = next(a for a in first.breakdown_navigation["actions"] if a["state"]["basis"] == "selected")
    assert selected["state"]["day"] == "2026-10-09"
    assert month(selected).breakdown_navigation["state"]["day"] == "2026-10-09"
    with open_ledger(path, read_only=True) as connection:
        key = connection.execute("select cache_key from rendered_reports where cache_key like 'breakdown:%:metadata'").fetchone()[0]
        info = load(connection, key)["ranges"]["selected"]
        assert info["min_date"] == "2026-10-01" and info["max_date"] == "2026-10-31"


def test_empty_selected_calendar_uses_bounded_clock_fallback(tmp_path):
    with open_ledger(breakdown_home(tmp_path)) as connection:
        for table in ("quota_provenance", "quota_observations", "credit_observations", "quota_reads"):
            connection.execute("delete from "+table)
        increment_ledger_revision(connection)
        connection.commit()
    report = render_ledger_report(tmp_path, range_name="month", project_keys=["nonexistent"], theme="day", timezone_name="UTC", now=AT)
    assert report.breakdown_navigation["state"]["day"] == "2026-10-09"
    past = render_ledger_report(tmp_path, range_name="custom", start_date="2026-09-15", end_date="2026-09-20",
        project_keys=["nonexistent"], theme="day", timezone_name="UTC", now=AT)
    assert past.breakdown_navigation["state"]["day"] == "2026-09-20"
