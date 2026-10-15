"""Mandatory period-history evidence, numerical parity and warm-work checks."""
from copy import deepcopy
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from release_tooling_support import load_tool
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_store import store_observations
from codex_usage.ledger_schema import increment_ledger_revision, ledger_revision, open_ledger
from codex_usage.report_allowance import render_allowance_section

fixtures = load_tool("allowance_period_fixture")
synthetic_report = fixtures.allowance_period_fixture


def test_local_dst_dates_bounded_captures_and_single_fit_claim(tmp_path):
    report = synthetic_report(tmp_path)
    former = deepcopy({key: report[key] for key in ("windows", "history", "headline", "paces")})
    markup = render_allowance_section(report, timezone=ZoneInfo("America/Toronto"))
    assert "Observed 2026-10-31 to 2026-11-01" in markup
    assert "Uncertain readings (4)" in markup
    assert "Most recent 100 of 125 exact captures shown" in markup
    assert "EDT" in markup and "EST" in markup
    assert "UTC: 2026-11-01T" in markup
    assert "Live probe" in markup and "Reset credits" in markup
    assert "Uncertain / cross-boundary fits (1)" in markup
    assert markup.count('class="allowance-fit"') == len(report["windows"])
    assert "No observations captured yet" not in markup
    assert "deadline rebase" in markup and "observation conflict" in markup
    assert "Current" in markup and "Actual start not established" in markup
    assert "Coverage ended" in markup
    assert former == {key: report[key] for key in former}


def test_presentation_preserves_former_numerical_outputs_and_one_raw_load(tmp_path, monkeypatch):
    import codex_usage.allowance_display_history as display
    import codex_usage.allowance_queries as queries

    original = synthetic_report(tmp_path)
    calls = []
    load = queries.load_quota_evidence

    def counted(connection):
        calls.append(1)
        return load(connection)

    monkeypatch.setattr(queries, "load_quota_evidence", counted)
    monkeypatch.setattr(display, "display_history", lambda *_: {})
    former = synthetic_report(tmp_path)
    assert len(calls) == 1
    for key in ("windows", "qualified", "headline", "headline_previous", "history", "paces", "credits"):
        assert original[key] == former[key]


def test_many_same_day_periods_and_fragments_have_bounded_details_and_full_counts(tmp_path):
    report = fixtures.dense_period_fixture(tmp_path)
    markup = render_allowance_section(report)
    assert "41 observed periods; newest 12 shown" in markup
    assert "Uncertain readings (79)" in markup
    assert "40 fragments; newest 12 shown" in markup
    assert markup.count('class="allowance-history-item"') == 24
    assert markup.count('class="allowance-observations"') == 24


def test_warm_report_does_not_reload_regroup_refit_or_reprice(tmp_path, monkeypatch):
    import codex_usage.allowance_display_history as display
    import codex_usage.allowance_index as index
    import codex_usage.allowance_queries as queries

    path = tmp_path / "warm.sqlite3"
    with open_ledger(path) as connection:
        stamp = datetime(2026, 10, 14, tzinfo=UTC).isoformat()
        store_observations(connection, [QuotaObservation(stamp, "codex", "primary", "pro", 10, 300, None)],
                           source_key="synthetic", provenance="live")
        increment_ledger_revision(connection)
        connection.commit()

    def report():
        with open_ledger(path, read_only=True) as connection:
            return index.indexed_allowance_report(connection, path, revision=ledger_revision(connection),
                                                  pricing_revision="synthetic", coverage_complete=True)

    cold = report()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Warm report performed historical work")

    monkeypatch.setattr(queries, "load_quota_evidence", forbidden)
    monkeypatch.setattr(queries, "estimate_window", forbidden)
    monkeypatch.setattr(display, "display_history", forbidden)
    monkeypatch.setattr(index, "estimate_cost", forbidden)
    warm = report()
    assert cold == warm
