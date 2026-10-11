"""Date switches must not value historical intervals or repeat account preparation."""
from datetime import timedelta
import json
from pathlib import Path
from runpy import run_path
from unittest.mock import patch

import pytest

from codex_usage.agent_reports import render_ledger_report
from codex_usage.aggregation import resolve_report_range
from codex_usage.breakdown_commands import BreakdownScopeExpired
import codex_usage.breakdown_reports as reports
from codex_usage.ledger_schema import increment_ledger_revision, open_ledger

fixture = run_path(str(Path(__file__).resolve().parents[1] / "scripts/usage_breakdown_fixture.py"))
AT, breakdown_home = fixture["AT"], fixture["breakdown_home"]


def render(home, range_name="today", action=None, **kwargs):
    return render_ledger_report(home, range_name=range_name, project_keys=kwargs.pop("keys", []),
        theme=kwargs.pop("theme", "day"), timezone_name=kwargs.pop("timezone", "UTC"),
        now=kwargs.pop("now", AT), breakdown_action=json.dumps(action) if action else None, **kwargs)


def prepared(connection, report):
    for row in connection.execute("select cache_key from rendered_reports where cache_key like 'breakdown:%:metadata'"):
        prefix = row[0][:-len("metadata")]
        if reports.load(connection, prefix + "nav:" + report.breakdown_navigation["scope"]) is not None:
            return prefix, reports.load(connection, row[0])
    raise AssertionError("Missing range preparation")


def test_new_dates_share_account_history_and_never_query_historical_usage(tmp_path):
    path = breakdown_home(tmp_path, days=30, extended=True)
    with patch.object(reports, "prepare_evidence", wraps=reports.prepare_evidence) as account, \
         patch.object(reports, "query_ledger_records", wraps=reports.query_ledger_records) as query, \
         patch.object(reports, "aggregate", wraps=reports.aggregate) as composition:
        first = render(tmp_path)
        yesterday = render(tmp_path, "yesterday")
        render(tmp_path, "7d")
        assert render(tmp_path).html == first.html
        assert render(tmp_path, "yesterday").html == yesterday.html
    assert account.call_count == 1
    assert query.call_count == 0
    assert composition.call_count == 3
    with open_ledger(path, read_only=True) as connection:
        _, initial = prepared(connection, first)
        _, previous = prepared(connection, yesterday)
        assert initial["account_prefix"] == previous["account_prefix"]
        assert initial["history_prefix"] == previous["history_prefix"]
        assert not connection.execute("select 1 from rendered_reports where cache_key like 'breakdown-history:%'").fetchone()


def test_history_inspection_reused_across_ranges_but_not_project_filters(tmp_path):
    path = breakdown_home(tmp_path, days=12, extended=True)
    first = render(tmp_path)
    issued = next(a for a in first.breakdown_navigation["actions"] if a["state"]["detail"].startswith("evidence:"))
    detail = issued["state"]["detail"]
    with patch.object(reports, "prepare_interval", wraps=reports.prepare_interval) as interval, \
         patch.object(reports, "prepare_evidence", wraps=reports.prepare_evidence) as account:
        inspected = render(tmp_path, action=issued)
        assert render(tmp_path, action=issued).html == inspected.html
        previous = render(tmp_path, "yesterday", theme="night")
        previous_action = next(a for a in previous.breakdown_navigation["actions"] if a["state"]["detail"] == detail)
        render(tmp_path, "yesterday", action=previous_action, theme="night")
        assert interval.call_count == 1 and account.call_count == 0
        with open_ledger(path, read_only=True) as connection:
            key = connection.execute("select project_key from ledger_projects order by project_key limit 1").fetchone()[0]
        filtered = render(tmp_path, keys=[key])
        filtered_action = next(a for a in filtered.breakdown_navigation["actions"] if a["state"]["detail"] == detail)
        render(tmp_path, keys=[key], action=filtered_action)
        assert interval.call_count == 2 and account.call_count == 0
    with open_ledger(path, read_only=True) as connection:
        _, initial = prepared(connection, first)
        _, selected = prepared(connection, filtered)
        assert initial["account_prefix"] == selected["account_prefix"]
        assert initial["history_prefix"] != selected["history_prefix"]
        basis = detail[len("evidence:"):]
        original = reports.load(connection, initial["history_prefix"] + basis + ":summary")
        narrow = reports.load(connection, selected["history_prefix"] + basis + ":summary")
        assert original["total"]["tokens"] > narrow["total"]["tokens"]
        assert set(narrow["projects"]) <= {key}


def test_missing_range_preparation_seeks_selected_day_only(tmp_path):
    path = breakdown_home(tmp_path, days=30, extended=True)
    first = render(tmp_path)
    with open_ledger(path) as connection:
        prefix, _ = prepared(connection, first)
        connection.execute("delete from rendered_reports where cache_key like ?", (prefix + "%",))
        connection.commit()
    with patch.object(reports, "query_ledger_records", wraps=reports.query_ledger_records) as query, \
         patch.object(reports, "prepare_evidence", wraps=reports.prepare_evidence) as account:
        rebuilt = render(tmp_path)
    assert rebuilt.html == first.html
    assert query.call_count == 1 and account.call_count == 0
    assert query.call_args.kwargs["bounds"] == resolve_report_range("today", AT.tzinfo, now=AT).bounds


def test_lazy_interval_preserves_chronological_cost_accumulation(tmp_path):
    path = breakdown_home(tmp_path, days=30, extended=True)
    first = render(tmp_path)
    with open_ledger(path, read_only=True) as connection:
        _, metadata = prepared(connection, first)
    windows = metadata["ranges"]
    issued = max((a for a in first.breakdown_navigation["actions"]
        if a["state"]["detail"].startswith("evidence:")), key=lambda a:
        windows[a["state"]["detail"][9:]]["end"] - windows[a["state"]["detail"][9:]]["start"])
    original_query, original_aggregate = reports.valued_query, reports.aggregate
    captured = []
    def source_order(*args, **kwargs):
        values = original_query(*args, **kwargs)
        return sorted(values, key=lambda item: item.record.timestamp, reverse=True)
    def checked(values, *args, **kwargs):
        times = [item.record.timestamp for item in values]
        assert len(times) > 1 and times == sorted(times)
        result = original_aggregate(values, *args, **kwargs)
        captured.append(result[0])
        return result
    with patch.object(reports, "valued_query", source_order), patch.object(reports, "aggregate", checked):
        render(tmp_path, action=issued)
    assert len(captured) == 1


def test_lazy_history_write_rejects_advanced_revision(tmp_path):
    path = breakdown_home(tmp_path, extended=True)
    first = render(tmp_path)
    issued = next(a for a in first.breakdown_navigation["actions"] if a["state"]["detail"].startswith("evidence:"))
    original = reports.prepare_interval
    def advancing(*args, **kwargs):
        data = original(*args, **kwargs)
        with open_ledger(path) as writer:
            increment_ledger_revision(writer)
            writer.commit()
        return data
    with patch.object(reports, "prepare_interval", advancing):
        render(tmp_path, action=issued)
    with open_ledger(path, read_only=True) as connection:
        assert not connection.execute("select 1 from rendered_reports where cache_key like 'breakdown-history:%'").fetchone()
    with pytest.raises(BreakdownScopeExpired):
        render(tmp_path, action=issued)


@pytest.mark.parametrize("changes", [{"timezone": "America/Toronto"}, {"now": AT+timedelta(hours=2)}])
def test_account_cache_does_not_cross_timezone_or_freshness(tmp_path, changes):
    path = breakdown_home(tmp_path)
    first = render(tmp_path)
    with patch.object(reports, "prepare_evidence", wraps=reports.prepare_evidence) as account:
        changed = render(tmp_path, **changes)
    assert account.call_count == 1
    with open_ledger(path, read_only=True) as connection:
        _, initial = prepared(connection, first)
        _, current = prepared(connection, changed)
        assert initial["account_prefix"] != current["account_prefix"]


def test_future_anchor_clock_transition_invalidates_commands(tmp_path):
    breakdown_home(tmp_path)
    future = render(tmp_path, now=AT-timedelta(minutes=1))
    assert "future weekly anchor" in future.html
    action = next(a for a in future.breakdown_navigation["actions"] if a["state"]["metric"] == "tokens")
    with pytest.raises(BreakdownScopeExpired):
        render(tmp_path, action=action)
    assert "future weekly anchor" not in render(tmp_path).html
