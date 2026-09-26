"""The full ledger estimator is the oracle for the disposable cost index."""
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta

import codex_usage.allowance_index as allowance_index
from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_rebuild import rebuild_stale_source_slice
from codex_usage.agent_reports import render_ledger_report
from codex_usage.allowance_index import indexed_allowance_report
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_queries import build_allowance_report
from codex_usage.allowance_store import store_observations
from codex_usage.ledger_schema import increment_ledger_revision, ledger_revision, open_ledger


def _session(path, totals):
    rows = [
        {"timestamp": "2026-09-02T10:00:00Z", "type": "session_meta",
         "payload": {"id": "task-1", "cwd": "/fixture/project"}},
        {"timestamp": "2026-09-02T10:00:01Z", "type": "turn_context",
         "payload": {"model": "gpt-5.6-sol"}},
    ]
    rows.extend({"timestamp": f"2026-09-02T10:00:{index + 2:02d}Z",
                 "type": "event_msg", "payload": {"type": "token_count", "info": {
                     "total_token_usage": {"input_tokens": total, "total_tokens": total}}}}
                for index, total in enumerate(totals))
    path.write_text("\n".join(map(json.dumps, rows)) + "\n")


def _point(second, used, *, reset=None):
    stamp = (datetime(2026, 9, 2, 10, tzinfo=UTC) + timedelta(seconds=second)).isoformat()
    return QuotaObservation(stamp, "codex", "primary", "pro", used, 300, reset)


def _compare(ledger, *, pricing="p1", coverage=True):
    with open_ledger(ledger, read_only=True) as connection:
        connection.execute("begin")
        oracle = build_allowance_report(connection, coverage_complete=coverage)
        indexed = indexed_allowance_report(
            connection, ledger, revision=ledger_revision(connection),
            pricing_revision=pricing, coverage_complete=coverage,
        )
    # Probe age advances between the two calculations. All retained evidence
    # and the reported status fields themselves have the same source query.
    oracle["status"].pop("probe_age_seconds")
    indexed["status"].pop("probe_age_seconds")
    assert indexed == oracle
    return indexed


def test_index_matches_oracle_across_append_replacement_recovery_pricing_and_reset(
    tmp_path, monkeypatch,
):
    home = tmp_path / ".codex"
    directory = home / "sessions" / "2026" / "09" / "02"
    directory.mkdir(parents=True)
    session = directory / "rollout-task-1.jsonl"
    _session(session, [100])
    monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance",
                        lambda *_: QuotaRead("2026-09-02T10:00:00+00:00", diagnostics="test"))
    assert capture_once(home, request_kind="manual", max_workers=1).outcome == "success"
    ledger = ledger_database_path(home)
    with open_ledger(ledger) as connection:
        store_observations(connection, [_point(0, 10), _point(2, 20),
                                        _point(4, 30), _point(6, 40), _point(8, 50)],
                           source_key="read:test", provenance="live")
        increment_ledger_revision(connection)
        connection.commit()
    _compare(ledger)
    with open_ledger(ledger) as connection:
        assert connection.execute("select count(*) from allowance_event_costs").fetchone()[0] == 1

    priced_calls = []
    original_price = allowance_index.estimate_cost

    def count_price(*args, **kwargs):
        priced_calls.append(1)
        return original_price(*args, **kwargs)

    monkeypatch.setattr(allowance_index, "estimate_cost", count_price)

    # Append retains the trusted generation; only the new event is priced.
    with session.open("a") as handle:
        handle.write(json.dumps({"timestamp": "2026-09-02T10:00:03Z", "type": "event_msg",
                                 "payload": {"type": "token_count", "info": {
                                     "total_token_usage": {"input_tokens": 150,
                                                           "total_tokens": 150}}}}) + "\n")
    assert capture_once(home, request_kind="manual", max_workers=1).outcome == "success"
    _compare(ledger)
    assert len(priced_calls) == 1
    with open_ledger(ledger) as connection:
        assert connection.execute("select count(*) from allowance_event_costs").fetchone()[0] == 2

    # Rewriting the source supersedes its generation, so its old prices must
    # not enter any cumulative window cost.
    replacement = tmp_path / "replacement.jsonl"
    _session(replacement, [300])
    os.replace(replacement, session)
    assert capture_once(home, request_kind="manual", max_workers=1).outcome == "success"
    rebuilt = rebuild_stale_source_slice(home, "task-1", max_bytes=64 * 1024)
    while not rebuilt.complete:
        rebuilt = rebuild_stale_source_slice(home, "task-1", max_bytes=64 * 1024)
    _compare(ledger)
    assert len(priced_calls) == 2
    with open_ledger(ledger) as connection:
        store_observations(connection, [_point(9, 2, reset=1790000000),
                                        _point(10, 8, reset=1790000000)],
                           source_key="recovery:test", provenance="recovered")
        increment_ledger_revision(connection)
        connection.commit()
    reset_report = _compare(ledger)
    assert len(reset_report["windows"]) >= 2
    with open_ledger(ledger) as connection:
        store_observations(connection, [_point(4, 31)],
                           source_key="correction:test", provenance="live")
        increment_ledger_revision(connection)
        connection.commit()
    _compare(ledger)
    _compare(ledger, coverage=False)
    _compare(ledger, pricing="p2")
    assert len(priced_calls) == 3
    with open_ledger(ledger) as connection:
        assert {row[0] for row in connection.execute(
            "select distinct pricing_revision from allowance_event_costs")} == {"p2:allowance-index-1"}


def test_read_only_pre_migration_report_uses_full_estimator(tmp_path):
    ledger = tmp_path / "ledger.sqlite3"
    with open_ledger(ledger) as connection:
        connection.execute("drop table allowance_report_cache")
        connection.execute("drop table allowance_event_costs")
        connection.execute("update ledger_meta set value = '3' where key = 'schema_version'")
        connection.commit()
    with open_ledger(ledger, read_only=True) as connection:
        connection.execute("begin")
        assert indexed_allowance_report(connection, ledger, revision=ledger_revision(connection),
                                        pricing_revision="p1", coverage_complete=True) == build_allowance_report(connection)
    with open_ledger(ledger) as connection:
        assert connection.execute("select value from ledger_meta where key='schema_version'").fetchone()[0] == '4'


def test_schema_3_migration_preserves_events_and_backs_up_prior_ledger(tmp_path):
    home = tmp_path / ".codex"
    directory = home / "sessions" / "2026" / "09" / "02"
    directory.mkdir(parents=True)
    _session(directory / "rollout-task-1.jsonl", [100])
    assert capture_once(home, request_kind="manual", max_workers=1).outcome == "success"
    ledger = ledger_database_path(home)
    with sqlite3.connect(ledger) as connection:
        expected_events = connection.execute(
            "select count(*) from ledger_usage_events"
        ).fetchone()[0]
        expected_sources = connection.execute(
            "select count(*) from ledger_sources"
        ).fetchone()[0]
        connection.execute("drop table allowance_report_cache")
        connection.execute("drop table allowance_event_costs")
        connection.execute(
            "update ledger_meta set value = '3' where key = 'schema_version'"
        )
    with open_ledger(ledger) as connection:
        assert connection.execute(
            "select value from ledger_meta where key = 'schema_version'"
        ).fetchone()[0] == "4"
        assert connection.execute(
            "select count(*) from ledger_usage_events"
        ).fetchone()[0] == expected_events
        assert connection.execute(
            "select count(*) from ledger_sources"
        ).fetchone()[0] == expected_sources
        assert connection.execute(
            "select name from sqlite_master where name = 'allowance_event_costs'"
        ).fetchone() is not None
        assert connection.execute(
            "select name from sqlite_master where name = 'allowance_report_cache'"
        ).fetchone() is not None
    backups = list(ledger.parent.glob(f"{ledger.name}.schema-3-backup-*"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute(
            "select value from ledger_meta where key = 'schema_version'"
        ).fetchone()[0] == "3"
        assert connection.execute(
            "select count(*) from ledger_usage_events"
        ).fetchone()[0] == expected_events


def test_conflicting_same_timestamp_quota_samples_keep_first_inserted(tmp_path):
    ledger = tmp_path / "ledger.sqlite3"
    with open_ledger(ledger) as connection:
        store_observations(connection, [_point(0, 20)],
                           source_key="first", provenance="live")
        store_observations(connection, [_point(0, 70)],
                           source_key="second", provenance="live")
        store_observations(connection, [_point(1, 80)],
                           source_key="later", provenance="live")
        increment_ledger_revision(connection)
        connection.commit()
    report = _compare(ledger)
    assert len(report["windows"]) == 1
    assert [point["used_percent"] for point in report["windows"][0]["points"]] == [20, 80]
    with open_ledger(ledger, read_only=True) as connection:
        assert [row[0] for row in connection.execute(
            "select used_percent from quota_observations order by timestamp, rowid"
        )] == [20, 70, 80]


def test_uncached_views_reuse_account_wide_allowance_result(tmp_path, monkeypatch):
    home = tmp_path / ".codex"
    directory = home / "sessions" / "2026" / "09" / "02"
    directory.mkdir(parents=True)
    _session(directory / "rollout-task-1.jsonl", [100])
    monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance",
                        lambda *_: QuotaRead("2026-09-02T10:00:00+00:00", diagnostics="test"))
    assert capture_once(home, request_kind="manual", max_workers=1).outcome == "success"
    ledger = ledger_database_path(home)
    with open_ledger(ledger) as connection:
        store_observations(connection, [_point(0, 10), _point(2, 20)],
                           source_key="fixture", provenance="live")
        increment_ledger_revision(connection)
        connection.commit()

    calls = {"price": 0, "events": 0, "windows": 0}

    def count(name, original):
        def counted(*args, **kwargs):
            calls[name] += 1
            return original(*args, **kwargs)
        return counted

    monkeypatch.setattr(allowance_index, "_price_missing_events",
                        count("price", allowance_index._price_missing_events))
    monkeypatch.setattr(allowance_index, "estimate_cost",
                        count("events", allowance_index.estimate_cost))
    monkeypatch.setattr(allowance_index, "_build_from_costs",
                        count("windows", allowance_index._build_from_costs))
    for range_name, projects, theme in (
        ("all", [], "day"), ("today", ["other"], "night"),
        ("month", [], "day"),
    ):
        report = render_ledger_report(home, range_name=range_name,
                                      project_keys=projects, theme=theme,
                                      timezone_name="UTC")
        assert not report.cache_hit
    assert calls == {"price": 1, "events": 1, "windows": 1}
    with open_ledger(ledger, read_only=True) as connection:
        assert connection.execute("select count(*) from allowance_report_cache").fetchone()[0] == 1
