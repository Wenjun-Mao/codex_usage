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


def test_warm_html_hits_never_select_or_decode_historical_payload(tmp_path, monkeypatch):
    import json
    from unittest.mock import patch

    import codex_usage.agent_reports as reports
    from codex_usage.agent_paths import ledger_database_path
    from codex_usage.ledger_schema import open_ledger

    home = tmp_path / "codex"
    (home / "sessions").mkdir(parents=True)
    anchor = datetime(2026, 9, 30, 12, tzinfo=UTC)
    stamp = anchor.isoformat()
    point = QuotaObservation(stamp, "codex", "primary", "pro", 80, 300, int(anchor.timestamp())+3600)
    monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance", lambda _: QuotaRead(stamp, "pro", (point,)))
    capture_once(home, request_kind="manual", max_workers=1)

    def render(now=anchor):
        return reports.render_ledger_report(home, range_name="all", project_keys=[], theme="day",
                                            timezone_name="UTC", now=now)

    first = render()
    ledger = ledger_database_path(home)
    with open_ledger(ledger) as connection:
        row = connection.execute("select * from allowance_report_cache where pricing_revision not like '%:pace-state'").fetchone()
        payload = json.loads(row["report_json"])
        payload["synthetic_historical_padding"] = "historical quota payload " * 250000
        connection.execute("update allowance_report_cache set report_json = ? where pricing_revision = ?",
                           (json.dumps(payload), row["pricing_revision"]))
        connection.commit()
    queries_seen = []
    original_open = reports.open_ledger
    original_loads = json.loads

    from contextlib import contextmanager

    @contextmanager
    def tracked_open(*args, **kwargs):
        with original_open(*args, **kwargs) as connection:
            connection.set_trace_callback(queries_seen.append)
            yield connection

    def small_decode(value, *args, **kwargs):
        assert len(value) < 10000, "warm view decoded historical allowance payload"
        return original_loads(value, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("warm HTML lookup loaded full allowance report")

    with patch.object(reports, "open_ledger", tracked_open), patch.object(reports, "indexed_allowance_report", forbidden), patch.object(json, "loads", small_decode):
        warm = render(anchor + timedelta(minutes=1))
    assert warm.cache_hit and warm.html == first.html
    assert all(":pace-state" in sql for sql in queries_seen if "from allowance_report_cache" in sql.lower())
    # A presentation transition may render history once; the subsequent hit
    # still uses only compact clock state and preserves stale-meter labeling.
    expired = render(anchor + timedelta(minutes=31))
    assert not expired.cache_hit and "Forecast awaiting fresh capture" in expired.html
    with patch.object(reports, "indexed_allowance_report", forbidden), patch.object(json, "loads", small_decode):
        assert render(anchor + timedelta(minutes=32)).cache_hit
    stale = render(anchor + timedelta(minutes=61))
    assert not stale.cache_hit and "Last known reading" in stale.html
    with patch.object(reports, "indexed_allowance_report", forbidden), patch.object(json, "loads", small_decode):
        assert render(anchor + timedelta(minutes=62)).cache_hit


def test_compact_cache_key_preserves_snapshot_pricing_and_coverage(tmp_path):
    from codex_usage.allowance_index import cached_allowance_pace
    from codex_usage.ledger_schema import open_ledger
    from codex_usage.allowance_store import store_observations
    import json

    ledger = tmp_path / "ledger.sqlite3"
    point = QuotaObservation(datetime(2026, 9, 30, tzinfo=UTC).isoformat(), "codex", "primary", "pro", 10, 300, None)
    with open_ledger(ledger) as connection:
        store_observations(connection, [point], source_key="fixture", provenance="live")
        from codex_usage.allowance_index import ALLOWANCE_REPORT_REVISION
        connection.execute("insert into allowance_report_cache values (?,?,?,?)",
                           (4, f"p1:allowance-index-2:report-{ALLOWANCE_REPORT_REVISION}:pace-state", 1,
                            json.dumps({"paces": [[{"fixture": True}]]})))
        assert cached_allowance_pace(connection, revision=4, pricing_revision="p1", coverage_complete=True) == {"paces": [[{"fixture": True}]]}
        for revision, pricing, coverage in ((5, "p1", True), (4, "p2", True), (4, "p1", False)):
            assert cached_allowance_pace(connection, revision=revision, pricing_revision=pricing, coverage_complete=coverage) is None
        connection.execute("drop table allowance_report_cache")
        assert cached_allowance_pace(connection, revision=4, pricing_revision="p1", coverage_complete=True) is None
