"""Avoid repeated presentation work without changing captured accounting."""
from dataclasses import asdict, replace
from datetime import timedelta
import json
from pathlib import Path
from runpy import run_path
from unittest.mock import patch

import codex_usage.agent_reports as base
import codex_usage.breakdown_reports as reports
import codex_usage.pricing_identity as identity
import codex_usage.pricing_schedule as schedule
from codex_usage.ledger_schema import open_ledger
from codex_usage.pricing import API_PRICING_USD_SCHEDULE

fixture = run_path(str(Path(__file__).resolve().parents[1] / "scripts/usage_breakdown_fixture.py"))
AT, breakdown_home = fixture["AT"], fixture["breakdown_home"]


def render(home, range_name="today", **kwargs):
    return base.render_ledger_report(home, range_name=range_name, project_keys=[],
        theme="day", timezone_name="UTC", now=kwargs.pop("now", AT), **kwargs)


def test_schedule_lookup_does_not_hash_rate_entries_and_replacement_is_not_stale():
    schedule._compiled_schedule.cache_clear()
    entries = API_PRICING_USD_SCHEDULE
    with patch.object(schedule.EffectiveModelRate, "__hash__", side_effect=AssertionError("Rate table rehashed")):
        first = schedule.schedule_entry_for_model(entries, "gpt-6.1-sol", AT)
        for _ in range(100):
            assert schedule.schedule_entry_for_model(entries, "gpt-6.1-sol", AT) is first
        modified = tuple(replace(e, rate=replace(e.rate, input_per_1m=999)) for e in entries)
        assert schedule.schedule_entry_for_model(modified, "gpt-6.1-sol", AT).rate.input_per_1m == 999
    assert schedule._compiled_schedule.cache_info().hits >= 100
    assert schedule._compiled_schedule.cache_info().maxsize == 8


def test_pricing_identity_tracks_rates_contracts_and_inclusion_not_package_version(monkeypatch):
    import codex_usage
    original = identity.pricing_revision()
    monkeypatch.setattr(codex_usage, "__version__", "99.0.0")
    assert identity.pricing_revision() == original
    with monkeypatch.context() as changed:
        changed.setattr(identity, "AUTO_REVIEW_FREE_FROM", identity.AUTO_REVIEW_FREE_FROM + timedelta(seconds=1))
        assert identity.pricing_revision() != original
    with monkeypatch.context() as changed:
        entries = identity.API_PRICING_USD_SCHEDULE
        changed.setattr(identity, "API_PRICING_USD_SCHEDULE", (replace(entries[0],
            rate=replace(entries[0].rate, output_per_1m=999)), *entries[1:]))
        assert identity.pricing_revision() != original
    with monkeypatch.context() as changed:
        changed.setattr(identity, "LANGUAGE_ACCOUNTING_REVISION", 999)
        assert identity.pricing_revision() != original


def test_warm_chart_reuses_section_and_single_snapshot_status(tmp_path):
    breakdown_home(tmp_path, extended=True)
    first = render(tmp_path)
    with patch.object(reports, "query_ledger_status", wraps=reports.query_ledger_status) as status, \
         patch("codex_usage.report_usage_breakdown.render_breakdown", side_effect=AssertionError("Chart rebuilt")):
        warm = render(tmp_path)
    assert warm.html == first.html and warm.breakdown_navigation == first.breakdown_navigation
    assert status.call_count == 1
    assert warm.status.plan_allowance["probe_status"] == "fresh"


def test_cold_date_switch_reuses_account_html_not_full_historical_decode(tmp_path):
    breakdown_home(tmp_path, extended=True)
    render(tmp_path)
    with patch.object(base, "indexed_allowance_report", side_effect=AssertionError("Account history decoded")):
        previous = render(tmp_path, "yesterday")
    assert "Plan Allowance" in previous.html


def test_missing_navigation_row_rebuilds_section_and_issues_valid_actions(tmp_path):
    path = breakdown_home(tmp_path, extended=True)
    first = render(tmp_path)
    with open_ledger(path) as connection:
        connection.execute("delete from rendered_reports where cache_key like ?",
            ("%:nav:" + first.breakdown_navigation["scope"],))
        connection.commit()
    rebuilt = render(tmp_path)
    assert rebuilt.html == first.html
    action = next(a for a in rebuilt.breakdown_navigation["actions"] if a["state"]["metric"] == "tokens")
    assert render(tmp_path, breakdown_action=json.dumps(action)).breakdown_navigation["state"]["metric"] == "tokens"


def test_quota_serialization_preserves_exact_fields():
    from codex_usage.allowance_models import QuotaObservation
    point = QuotaObservation(AT.isoformat(), "codex", "secondary", "pro", 1.2345678, 10080, None)
    assert point.to_dict() == asdict(point)


def test_html_fragments_check_revision_inside_one_writer_transaction(tmp_path, monkeypatch):
    path = breakdown_home(tmp_path, extended=True)
    original = base.ledger_revision
    def guarded(connection):
        assert connection.in_transaction
        return original(connection)
    monkeypatch.setattr(base, "ledger_revision", guarded)
    with open_ledger(path, read_only=True) as connection:
        revision = original(connection)
    base._store_cached_reports(path, revision, {"one": "first", "two": "second"})
    with open_ledger(path, read_only=True) as connection:
        assert base._load_cached_report(connection, "one") == "first"
        assert base._load_cached_report(connection, "two") == "second"
    base._store_cached_reports(path, revision - 1, {"stale": "rejected"})
    with open_ledger(path, read_only=True) as connection:
        assert base._load_cached_report(connection, "stale") is None
