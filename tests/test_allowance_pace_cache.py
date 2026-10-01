"""Presentation boundaries invalidate HTML, never the capture-anchored fit."""
from datetime import UTC, datetime, timedelta

import codex_usage.allowance_queries as queries
from codex_usage.agent_capture import capture_once
from codex_usage.agent_reports import render_ledger_report
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead


def test_views_reuse_rates_and_expiry_refreshes_html_without_reads_or_fit(tmp_path, monkeypatch):
    home = tmp_path / "codex"
    (home / "sessions").mkdir(parents=True)
    base = datetime(2026, 9, 30, 12, tzinfo=UTC)
    reset = int((base + timedelta(hours=3)).timestamp())
    for minutes, used in ((0, 95), (15, 97), (30, 99)):
        stamp = (base + timedelta(minutes=minutes)).isoformat()
        read = QuotaRead(stamp, "pro", (QuotaObservation(stamp, "codex", "primary", "pro", used, 300, reset),))
        monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance", lambda _, read=read: read)
        capture_once(home, request_kind="manual", max_workers=1)
    anchor = base + timedelta(minutes=30)

    def render(now=anchor, **options):
        return render_ledger_report(home, range_name=options.pop("range_name", "all"),
                                    project_keys=options.pop("project_keys", []), theme=options.pop("theme", "day"),
                                    timezone_name="America/Toronto", now=now, **options)

    first = render()
    assert "would run out around" in first.html

    def forbidden(*args, **kwargs):
        raise AssertionError("warm view reconstructed, repriced, captured or probed")

    monkeypatch.setattr(queries, "_build_from_costs", forbidden)
    monkeypatch.setattr("codex_usage.allowance_index._build_from_costs", forbidden)
    monkeypatch.setattr("codex_usage.allowance_index._price_missing_events", forbidden)
    monkeypatch.setattr("codex_usage.allowance_pace.fit_paces", forbidden)
    monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance", forbidden)
    monkeypatch.setattr("codex_usage.agent_capture.capture_once", forbidden)
    # Also enforce no JSONL access, even in a newly selected date/project view.
    from pathlib import Path
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path.suffix != ".jsonl"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    assert render(anchor + timedelta(minutes=1)).cache_hit
    view = render(theme="night", range_name="today", project_keys=["other"])
    assert not view.cache_hit and "would run out around" in view.html
    expired = render(anchor + timedelta(minutes=8))
    assert not expired.cache_hit and "Forecast awaiting fresh capture" in expired.html
    assert "would run out around" not in expired.html
    assert render(anchor + timedelta(minutes=9)).cache_hit
    assert not render(anchor + timedelta(minutes=30)).cache_hit  # Daily freshness boundary
    assert not render(anchor + timedelta(minutes=61)).cache_hit  # Existing meter boundary


def test_partial_response_does_not_borrow_missing_previous_bucket(tmp_path, monkeypatch):
    from codex_usage.agent_paths import ledger_database_path
    from codex_usage.allowance_queries import build_allowance_report
    from codex_usage.ledger_schema import open_ledger

    home = tmp_path / "codex"
    (home / "sessions").mkdir(parents=True)
    base = datetime(2026, 9, 30, 12, tzinfo=UTC)
    for minutes, used in ((0, 10), (15, 11), (30, 12)):
        stamp = (base + timedelta(minutes=minutes)).isoformat()
        point = QuotaObservation(stamp, "codex", "primary", "pro", used, 300, int(base.timestamp())+7200)
        buckets = (point, QuotaObservation(stamp, "other", "secondary", "pro", used, 10080, point.resets_at)) if minutes < 30 else (point,)
        read = QuotaRead(stamp, "pro", buckets, diagnostics="partial" if minutes == 30 else "")
        monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance", lambda _, read=read: read)
        capture_once(home, request_kind="manual", max_workers=1)
    with open_ledger(ledger_database_path(home), read_only=True) as connection:
        report = build_allowance_report(connection)
    assert len(report["paces"]) == len(report["status"]["active_buckets"]) == 1
    assert report["paces"][0][0]["rate"] == 4
