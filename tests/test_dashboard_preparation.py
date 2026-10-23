"""Exact accounting and independently owned preparation invalidation."""
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime, timedelta
import json
import pickle
import sqlite3
from unittest.mock import patch

import pytest

from codex_usage import allowance_prepared_cache as cache
from codex_usage.agent_activity import LedgerTask, build_agent_activity
from codex_usage.agent_daily_activity import build_daily_activity
from codex_usage.aggregation import UsageSummary, value_records
from codex_usage.allowance_history_navigation import navigation
from codex_usage.allowance_history_overview import decode_overview, encode_overview
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_preparation import AllowancePreparation
from codex_usage.dashboard_preparation_tracking import token
from codex_usage.ledger_queries import query_ledger_records
from codex_usage.ledger_schema import increment_ledger_revision, open_ledger
from codex_usage.ledger_writer_contract import authorize_writer_connection
from codex_usage.models import TokenUsage
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.report_allowance_history import period_history
from codex_usage.summary_accumulator import SummaryAccumulator
from test_allowance_window_cache import AT, breakdown_home, compare


def test_accumulator_preserves_every_component_and_sequential_float_bits(tmp_path):
    path = breakdown_home(tmp_path, extended=True)
    with open_ledger(path, read_only=True) as connection:
        values = list(value_records(query_ledger_records(connection)))
    rows = [v.summary for v in values]
    # Include partial unknown components and cancellation-sensitive input.
    rows += [UsageSummary(TokenUsage(**{f.name: i for f in fields(TokenUsage)}),
        CostBreakdown(**{f.name: amount if f.type == 'float' else i for f in fields(CostBreakdown)}), i,
        CreditBreakdown(**{f.name: amount if f.type == 'float' else i for f in fields(CreditBreakdown)}))
        for i, amount in enumerate((1e16, 1.0, -1e16, -0.0, 1e-14))]
    expected = UsageSummary(TokenUsage(), CostBreakdown(), 0, CreditBreakdown())
    actual = SummaryAccumulator()
    for row in rows:
        expected = expected.add(row)
        actual.add(row)
    assert actual.freeze() == expected
    assert json.dumps(asdict(actual.freeze())) == json.dumps(asdict(expected))


def test_daily_path_matches_full_export_including_missing_parent_cycles_and_dst(tmp_path):
    from zoneinfo import ZoneInfo
    path = breakdown_home(tmp_path, extended=True)
    with open_ledger(path, read_only=True) as connection:
        records = query_ledger_records(connection)
    tasks = {"cycle-a": LedgerTask("cycle-a", "cycle-b", "subagent", "A"),
             "cycle-b": LedgerTask("cycle-b", "cycle-a", "subagent", "B"),
             "missing": LedgerTask("missing", "not-present", "subagent", "Missing")}
    # Include the repeated Toronto hour and the preceding local midnight.
    dst = datetime(2026, 11, 1, 3, 30, tzinfo=UTC)
    records += [replace(records[0], session_id=task, usage_role="subagent",
                        timestamp=dst+timedelta(hours=i)) for i, task in enumerate(tasks)]
    records.append(replace(records[-1], timestamp=dst+timedelta(hours=3)))
    for timezone in (UTC, ZoneInfo("America/Toronto")):
        full = build_agent_activity(records, tasks, timezone)
        daily = build_daily_activity(records, tasks, timezone)
        assert daily.totals == full.totals and daily.daily_rows == full.daily_rows
        assert not hasattr(daily, "agent_day_rows")


def test_observation_memos_do_not_change_evidence_or_copy_identity():
    point = QuotaObservation(AT.isoformat(), "codex", "primary", "pro", 12.0, 10080, None)
    raw = asdict(point)
    assert hash(point) == hash(tuple(raw.values()))
    assert point.timestamp_seconds == AT.timestamp()
    assert asdict(point) == raw and point.to_dict() == raw
    copied = pickle.loads(pickle.dumps(point))
    assert copied == point and hash(copied) == hash(point)
    assert copied.timestamp_seconds == point.timestamp_seconds
    later = replace(point, timestamp=(AT+timedelta(seconds=1)).isoformat())
    assert later.timestamp_seconds == point.timestamp_seconds+1


def prepare(path):
    with open_ledger(path, read_only=True) as connection:
        connection.execute("begin")
        result = AllowancePreparation(connection)
        result.pace({("codex", 10080)})
        return result.raw


def test_usage_only_reuses_quota_but_legacy_connection_quota_write_invalidates(tmp_path):
    path = breakdown_home(tmp_path, extended=True)
    first = prepare(path)
    with open_ledger(path) as writer:
        writer.execute("update ledger_usage_events set total_tokens=total_tokens+1")
        increment_ledger_revision(writer)
        writer.commit()
    with patch("codex_usage.allowance_queries.load_quota_evidence", side_effect=AssertionError("Expanded unchanged quota")):
        assert prepare(path) is first
    # No current collector hook: SQLite-native triggers still invalidate.
    with sqlite3.connect(path) as old_writer:
        authorize_writer_connection(old_writer)
        old_writer.execute("update quota_observations set used_percent=used_percent+0.01")
    second = prepare(path)
    assert second is not first and second[0] != first[0]


@pytest.mark.parametrize("damage", ["trigger", "table", "epoch"])
def test_tracking_repair_changes_identity_and_does_not_reuse_old_preparation(tmp_path, damage):
    path = breakdown_home(tmp_path, extended=True)
    first = prepare(path)
    with sqlite3.connect(path) as writer:
        authorize_writer_connection(writer)
        if damage == "trigger":
            writer.execute("drop trigger dashboard_preparation_quota_observations_update")
            writer.execute("update quota_observations set used_percent=used_percent+0.01")
        elif damage == "table":
            writer.execute("drop table dashboard_preparation_state")
        else:
            writer.execute("update dashboard_preparation_state set epoch='replacement'")
    with open_ledger(path):
        pass
    assert prepare(path) is not first


def test_rollback_never_publishes_uncommitted_raw_evidence(tmp_path):
    path = breakdown_home(tmp_path, extended=True)
    first = prepare(path)
    with open_ledger(path) as writer:
        writer.execute("update quota_observations set used_percent=90")
        assert AllowancePreparation(writer).raw[0] != first[0]
        writer.rollback()
        writer.execute("update quota_observations set used_percent=80")
        writer.commit()
    assert {p.used_percent for p in prepare(path)[0]} == {80}


def test_cache_retains_only_one_bounded_preparation(tmp_path, monkeypatch):
    path = breakdown_home(tmp_path, extended=True)
    cache.clear()
    monkeypatch.setattr(cache, "MAX_POINTS", 1)
    prepare(path)
    assert cache._raw is None and cache._series == {}


def test_compact_overview_renders_every_page_identically_and_omits_interior_captures(tmp_path):
    path = breakdown_home(tmp_path, extended=True)
    report, _ = compare(path)
    overview = decode_overview(encode_overview(report))
    assert len(overview["display_history"]["captures"]) < len(report["display_history"]["captures"])
    for page in range(max(1, (len(report["reset_history"]["periods"])+11)//12)):
        nav = navigation(report, "scope")
        state = dict(nav["state"], period_page=page)
        nav = navigation(report, "scope", state)
        assert navigation(overview, "scope", state) == nav
        assert period_history(overview, UTC, nav=nav) == period_history(report, UTC, nav=nav)


def test_counter_repair_does_not_consume_fit_invalidation(tmp_path):
    path = breakdown_home(tmp_path, extended=True)
    compare(path)
    with open_ledger(path) as writer:
        writer.execute("update quota_observations set used_percent=used_percent+0.01")
        expected = [tuple(row) for row in writer.execute("select * from allowance_window_dirty")]
        writer.execute("drop trigger dashboard_preparation_quota_reads_insert")
        writer.commit()
    with open_ledger(path) as writer:
        assert token(writer) is not None
        assert [tuple(row) for row in writer.execute("select * from allowance_window_dirty")] == expected


def test_overview_reset_subset_uses_its_own_capture_endpoints(tmp_path):
    from codex_usage.allowance_probe import QuotaRead
    from codex_usage.allowance_store import store_read
    path = tmp_path / "ledger.sqlite3"
    with open_ledger(path) as writer:
        for hour, used, deadline in ((0, 4, 6), (.5, 2, None), (1, 0, None), (2, 1, 8)):
            at = AT+timedelta(hours=hour)
            point = QuotaObservation(at.isoformat(), "codex", "secondary", "pro", used, 10080,
                int((AT+timedelta(hours=deadline)).timestamp()) if deadline is not None else None)
            store_read(writer, QuotaRead(at.isoformat(), "pro", (point,)), None)
        increment_ledger_revision(writer)
        writer.commit()
    report, _ = compare(path)
    overview = decode_overview(encode_overview(report))
    nav = navigation(report, "scope")
    assert period_history(overview, UTC, nav=nav) == period_history(report, UTC, nav=nav)


@pytest.mark.parametrize("payload", ["{", "{}", '{"display_history": {}}', "invalid-cross-reference"])
def test_invalid_overview_falls_back_to_exact_cache(tmp_path, payload):
    from codex_usage.agent_reports import PRICING_REVISION, render_ledger_report
    from codex_usage.allowance_index import _revisions
    path = breakdown_home(tmp_path, extended=True)
    def render(range_name):
        return render_ledger_report(tmp_path, range_name=range_name, project_keys=[], theme="day",
                                    timezone_name="UTC", now=AT)
    render("today")
    with open_ledger(path) as writer:
        if payload == "invalid-cross-reference":
            row = writer.execute("select report_json from allowance_report_cache where pricing_revision=?",
                (_revisions(PRICING_REVISION)[1] + ":history-overview-1",)).fetchone()
            data = json.loads(row[0])
            for history in data.values():
                history["cross_boundary_fit_indices"] = ["not-an-index"]
            payload = json.dumps(data)
        writer.execute("update allowance_report_cache set report_json=? where pricing_revision=?",
                       (payload, _revisions(PRICING_REVISION)[1] + ":history-overview-1"))
        writer.commit()
    assert "Allowance history" in render("yesterday").html
