"""Synthetic period history checks; optional real-engine layout verification."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import os
from zoneinfo import ZoneInfo

import pytest

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_display_history import display_history
from codex_usage.allowance_preparation import AllowancePreparation
from codex_usage.allowance_queries import _build_from_costs, allowance_status
from codex_usage.allowance_store import store_observations
from codex_usage.ledger_schema import increment_ledger_revision, ledger_revision, open_ledger
from codex_usage.report_allowance import allowance_css, render_allowance_section
from codex_usage.report_theme import report_css


def synthetic_report(tmp_path):
    at = datetime(2026, 11, 1, 3, 30, tzinfo=UTC)
    reset = int((at + timedelta(hours=8)).timestamp())
    points = [QuotaObservation((at + timedelta(minutes=i)).isoformat(), "codex", "primary", "pro",
                               10 + i / 4, 300, reset, 2) for i in range(125)]
    # The estimator does not cut on a clock rebase without a meter drop.
    points += [replace(points[-1], timestamp=(at + timedelta(hours=3)).isoformat(), used_percent=45,
                       resets_at=reset + 120)]
    points += [replace(points[-1], timestamp=(at + timedelta(hours=4)).isoformat(), used_percent=50),
               replace(points[-1], timestamp=(at + timedelta(hours=4)).isoformat(), used_percent=55)]
    points += [replace(points[-1], timestamp=(at + timedelta(hours=5)).isoformat(), used_percent=60),
               replace(points[-1], timestamp=(at + timedelta(hours=6)).isoformat(), used_percent=5, reset_credits=1)]
    with open_ledger(tmp_path / "synthetic.sqlite3") as connection:
        store_observations(connection, points, source_key="synthetic", provenance="live")
        status = allowance_status(connection)
        status.update(active_buckets=[points[-1].to_dict()], plan="pro", probe_status="fresh",
                      last_probe_at=points[-1].timestamp, last_observed_at=points[-1].timestamp)
        preparation = AllowancePreparation(connection)
        # Synthetic priced costs, not a real ledger or private logs.
        costs = [(datetime.fromisoformat(p.timestamp).timestamp(), 1.0, 0) for p in points]
        return _build_from_costs(connection, costs, status=status, preparation=preparation)


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
    report = synthetic_report(tmp_path)
    at = datetime(2026, 10, 14, tzinfo=UTC)
    periods = [QuotaObservation((at + timedelta(minutes=i)).isoformat(), "codex", "primary", "pro",
                               10, 300, None, 100-i) for i in range(40)]
    fragments = [replace(periods[0], timestamp=(at + timedelta(minutes=i)).isoformat(), limit_id="other",
                         used_percent=80 if i % 2 == 0 else 10, reset_credits=None) for i in range(80)]
    points = periods + fragments
    report.update(windows=[], history=[], headline=None, qualified=[], paces=[])
    report["display_history"] = display_history(points, {p: {"Task snapshot"} for p in points}, [], [])
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


@pytest.mark.skipif(os.environ.get("CODEX_ALLOWANCE_DISPLAY_UI") != "1", reason="Opt-in synthetic browser check")
@pytest.mark.parametrize("engine", ["chromium", "firefox", "webkit"])
def test_period_history_browser_layout(tmp_path, engine):
    from playwright.sync_api import sync_playwright

    report = synthetic_report(tmp_path)
    with sync_playwright() as playwright:
        browser = getattr(playwright, engine).launch()
        try:
            page = browser.new_page(java_script_enabled=False)
            for theme in ("day", "night"):
                for width in (360, 1440):
                    page.set_viewport_size({"width": width, "height": 900})
                    page.set_content(f'<!doctype html><html data-codex-theme="{theme}"><style>'
                                     f'{report_css()}{allowance_css()}</style><body>'
                                     f'{render_allowance_section(report, timezone=ZoneInfo("America/Toronto"))}'
                                     '</body></html>')
                    page.get_by_text("Probe, coverage, and allowance history", exact=True).click()
                    period = page.get_by_role("list", name="Allowance period history")
                    assert period.locator(":scope > li").count() == 2
                    uncertain = page.locator(".allowance-uncertain")
                    assert not uncertain.evaluate("e => e.open")
                    period.scroll_into_view_if_needed()
                    page.screenshot(path=str(tmp_path / f"period-history-{engine}-{theme}-{width}-compact.png"))
                    uncertain.locator(":scope > summary").click()
                    assert uncertain.locator(":scope > ol > li").count() == 2
                    assert not page.locator(".allowance-observations").first.is_visible()
                    for summary in page.locator("summary").all():
                        if summary.is_visible() and "Capture details" in summary.inner_text():
                            summary.click()
                    assert page.locator(".allowance-observations tbody tr").count() == 105
                    assert page.locator(".allowance-history-item").evaluate_all(
                        "es => es.every(e => e.scrollWidth <= e.clientWidth + 1)")
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    period.scroll_into_view_if_needed()
                    page.screenshot(path=str(tmp_path / f"period-history-{engine}-{theme}-{width}-detail.png"))
        finally:
            browser.close()
