"""Historical reuse must equal a fresh monetary fit after source mutations."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from runpy import run_path
import sqlite3
from unittest.mock import patch

import pytest

from codex_usage import allowance_queries as queries
from codex_usage.allowance_index import indexed_allowance_report
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_store import store_observations, store_read
from codex_usage.ledger_schema import increment_ledger_revision, ledger_revision, open_ledger

fixture = run_path(str(Path(__file__).resolve().parents[1] / "scripts/usage_breakdown_fixture.py"))
AT, breakdown_home = fixture["AT"], fixture["breakdown_home"]


def compare(path, *, pricing="p1", coverage=True):
    with open_ledger(path, read_only=True) as connection:
        connection.execute("begin")
        status = queries.allowance_status(connection, now=AT)
        expected = queries.build_allowance_report(connection, coverage_complete=coverage, status=status)
        with patch.object(queries, "_fit_window", wraps=queries._fit_window) as build:
            actual = indexed_allowance_report(connection, path, revision=ledger_revision(connection),
                pricing_revision=pricing, coverage_complete=coverage, status=status)
        assert actual == expected
        return actual, [c.args[0].points[0].timestamp for c in build.call_args_list]


@pytest.fixture
def ledger(tmp_path):
    path = breakdown_home(tmp_path, projects=2, days=12, extended=True)
    compare(path)
    return path


def revise(path):
    with open_ledger(path) as connection:
        increment_ledger_revision(connection)
        connection.commit()


def add_event(connection, stamp):
    row = dict(connection.execute("select * from ledger_usage_events order by timestamp_us limit 1").fetchone())
    row.pop("event_id")
    row["timestamp"], row["timestamp_us"] = stamp.isoformat(), round(stamp.timestamp()*1e6)
    row["source_record_index"] = connection.execute("select max(source_record_index)+1 from ledger_usage_events").fetchone()[0]
    connection.execute(f"insert into ledger_usage_events ({','.join(row)}) values ({','.join('?' for _ in row)})", tuple(row.values()))


def point(stamp, used=40, **kwargs):
    return QuotaObservation(stamp.isoformat(), "codex", "primary", kwargs.pop("plan", "pro"), used,
        kwargs.pop("duration", 10080), int((AT+timedelta(days=4)).timestamp()), **kwargs)


def test_revision_only_reuses_all_windows_but_not_stale_status(ledger):
    before, _ = compare(ledger)
    with open_ledger(ledger) as connection:
        store_read(connection, QuotaRead((AT+timedelta(minutes=1)).isoformat(), "pro", diagnostics="new failure"), None)
        increment_ledger_revision(connection)
        connection.commit()
    after, built = compare(ledger)
    assert built == []
    assert after["windows"] == before["windows"]
    assert after["status"]["diagnostics"] == "new failure"


def test_append_rebuilds_active_window_only_and_prunes_old_versions(ledger):
    before, _ = compare(ledger)
    old_start = before["windows"][0]["start"]
    for i in range(1, 5):
        at = AT+timedelta(hours=i)
        with open_ledger(ledger) as connection:
            add_event(connection, at)
            store_read(connection, QuotaRead(at.isoformat(), "pro", (point(at, 40+i),)), None)
            increment_ledger_revision(connection)
            connection.commit()
        after, built = compare(ledger)
        assert built and old_start not in built
        assert after["windows"][0] == before["windows"][0]
        with open_ledger(ledger, read_only=True) as connection:
            assert connection.execute("select count(*) from allowance_window_cache").fetchone()[0] <= 2*len(after["windows"])
            assert connection.execute("select count(*) from allowance_window_dirty").fetchone()[0] == 0


@pytest.mark.parametrize("mutation", ["late_insert", "update", "delete", "generation", "model", "source"])
def test_usage_mutations_match_fresh_pricing_and_prefixes(ledger, mutation):
    before, _ = compare(ledger)
    with open_ledger(ledger) as connection:
        if mutation == "late_insert":
            # Earlier than every window: cancellation must retain exact floats.
            add_event(connection, AT-timedelta(days=20))
        elif mutation == "update":
            connection.execute("update ledger_usage_events set input_tokens=input_tokens+999, total_tokens=total_tokens+999")
        elif mutation == "delete":
            connection.execute("delete from ledger_usage_events where event_id=(select min(event_id) from ledger_usage_events)")
        elif mutation == "generation":
            connection.execute("update ledger_generations set status='superseded' where generation_id=1")
        elif mutation == "model":
            connection.execute("update ledger_models set model_key='new-unknown-model' where model_key='gpt-6.1-sol'")
        else:
            connection.execute("update ledger_sources set source_key='reordered:' || source_key")
        assert connection.execute("select count(*) from allowance_window_dirty").fetchone()[0] <= 2
        increment_ledger_revision(connection)
        connection.commit()
    _, built = compare(ledger)
    assert before["windows"][0]["start"] in built


@pytest.mark.parametrize("mutation", ["late", "conflict", "provenance", "delete", "interior", "compressed"])
def test_late_quota_evidence_and_provenance_do_not_reuse_stale_points(ledger, mutation):
    with open_ledger(ledger) as connection:
        row = connection.execute("select * from quota_observations order by timestamp limit 1 offset 1").fetchone()
        old = QuotaObservation(**{k: row[k] for k in QuotaObservation.__dataclass_fields__})
        if mutation in {"late", "conflict", "compressed"}:
            stamp = old.timestamp if mutation == "conflict" else (AT-timedelta(days=9, hours=1)).isoformat()
            store_observations(connection, [replace(old, timestamp=stamp, used_percent=99)], source_key="late",
                provenance="recovered" if mutation == "compressed" else "parsed")
        elif mutation == "provenance":
            connection.execute("update quota_provenance set provenance='parsed' where observation_key=?", (row["observation_key"],))
        elif mutation == "delete":
            connection.execute("delete from quota_provenance where observation_key=?", (row["observation_key"],))
            connection.execute("delete from quota_observations where observation_key=?", (row["observation_key"],))
        else:
            connection.execute("update quota_observations set used_percent=94 where observation_key=?", (row["observation_key"],))
        increment_ledger_revision(connection)
        connection.commit()
    _, built = compare(ledger)
    assert built


def test_future_identity_and_full_meter_conflict_keep_causal_scope(ledger):
    # The live anchor is earlier than recovered evidence. Full-history identity
    # must not resolve an unknown plan at the capture-causal origin.
    with open_ledger(ledger) as connection:
        connection.execute("update quota_observations set plan='' where limit_id='codex'")
        store_observations(connection, [point(AT+timedelta(hours=1), 45, plan="plus")],
            source_key="future", provenance="parsed")
        increment_ledger_revision(connection)
        connection.commit()
    first, built = compare(ledger)
    assert built
    revise(ledger)
    assert compare(ledger)[1] == []
    with open_ledger(ledger) as connection:
        store_observations(connection, [point(AT, 100, plan="")], source_key="full-conflict", provenance="parsed")
        increment_ledger_revision(connection)
        connection.commit()
    second, built = compare(ledger)
    assert built and first["windows"] != second["windows"]


def test_unchanged_quota_upsert_does_not_invalidate(ledger):
    with open_ledger(ledger) as connection:
        row = connection.execute("""select o.*,p.source_key,p.provenance from quota_observations o
            join quota_provenance p using(observation_key) limit 1""").fetchone()
        observation = QuotaObservation(**{k: row[k] for k in QuotaObservation.__dataclass_fields__})
        # The synthetic fixture hashed integer percentages before SQLite stored
        # them as reals. Replay the original typed observation and source key.
        observation = replace(observation, used_percent=int(observation.used_percent))
        store_observations(connection, [observation], source_key=row["source_key"], provenance=row["provenance"])
        assert connection.execute("select count(*) from allowance_window_dirty").fetchone()[0] == 0
        increment_ledger_revision(connection)
        connection.commit()
    assert compare(ledger)[1] == []


def test_compacted_mixed_offset_interior_and_provenance_are_conservative(ledger):
    # Lexical endpoints are both on Oct 9 in UTC; the interior is Oct 8.
    stamps = ("2026-10-09T01:00:00+00:00", "2026-10-09T02:00:00+13:00", "2026-10-09T03:00:00+00:00")
    points = [replace(point(AT, 34), timestamp=stamp) for stamp in stamps]
    with open_ledger(ledger) as connection:
        store_observations(connection, points, source_key="compressed", provenance="recovered")
        increment_ledger_revision(connection)
        connection.commit()
    compare(ledger)
    with open_ledger(ledger) as connection:
        connection.execute("update quota_provenance set provenance='parsed' where source_key='compressed'")
        dirty = connection.execute("select start,end from allowance_window_dirty where kind='quota'").fetchone()
        assert tuple(dirty) == (-1e300, 1e300)
        increment_ledger_revision(connection)
        connection.commit()
    assert compare(ledger)[1]


@pytest.mark.parametrize("change", ["pricing", "coverage", "trigger", "replaced_trigger", "cache", "dirty", "tracking"])
def test_contract_or_missing_tracking_fails_closed(ledger, change):
    with open_ledger(ledger) as connection:
        if change in {"trigger", "replaced_trigger"}:
            connection.execute("drop trigger allowance_windows_usage_update")
            if change == "replaced_trigger":
                connection.execute("create trigger allowance_windows_usage_update after update on ledger_usage_events begin select 1; end")
            connection.execute("update ledger_usage_events set input_tokens=input_tokens+999, total_tokens=total_tokens+999")
        elif change in {"cache", "dirty", "tracking"}:
            connection.execute("drop table allowance_window_" + change)
        increment_ledger_revision(connection)
        connection.commit()
    _, built = compare(ledger, pricing="p2" if change == "pricing" else "p1", coverage=change != "coverage")
    assert built


@pytest.mark.parametrize("table", ["dirty", "cache", "tracking"])
def test_partial_reset_cached_read_then_capture_recovers_tracking(ledger, table):
    before, _ = compare(ledger)
    with sqlite3.connect(ledger) as connection:
        connection.execute("drop table allowance_window_" + table)
    # Existing complete reports can still satisfy a read without a writer.
    cached, built = compare(ledger)
    assert built == [] and cached == before
    with open_ledger(ledger) as connection:
        at = AT+timedelta(hours=1)
        add_event(connection, at)
        store_read(connection, QuotaRead(at.isoformat(), "pro", (point(at, 45),)), None)
        increment_ledger_revision(connection)
        connection.commit()
    assert compare(ledger)[1]


def test_first_install_retains_independent_price_index(ledger):
    # Simulate a pre-feature ledger with valid event prices and no fits/tracking.
    with sqlite3.connect(ledger) as connection:
        costs = connection.execute("select * from allowance_event_costs order by event_id").fetchall()
        names = [r[0] for r in connection.execute("select name from sqlite_master where type='trigger' and name like 'allowance_windows_%'")]
        for name in names:
            connection.execute("drop trigger " + name)
        for name in ("cache", "dirty", "tracking"):
            connection.execute("drop table allowance_window_" + name)
        connection.execute("delete from allowance_report_cache")
    with patch("codex_usage.allowance_index.estimate_cost", side_effect=AssertionError("First installation repriced history")):
        assert compare(ledger)[1]
    with open_ledger(ledger, read_only=True) as connection:
        assert [tuple(r) for r in connection.execute("select * from allowance_event_costs order by event_id")] == costs
        # Only compact fitted results are retained, never copies of raw readings.
        assert connection.execute("select max(length(report_json)) from allowance_window_cache").fetchone()[0] < 1000


def test_storage_format_change_rebuilds_reports_without_repricing(ledger, monkeypatch):
    from codex_usage import allowance_index
    with open_ledger(ledger, read_only=True) as connection:
        costs = [tuple(r) for r in connection.execute("select * from allowance_event_costs order by event_id")]
    monkeypatch.setattr(allowance_index, "REPORT_CACHE_FORMAT_REVISION", 2)
    with patch.object(allowance_index, "estimate_cost", side_effect=AssertionError("Storage format repriced events")):
        assert compare(ledger)[1]
    with open_ledger(ledger, read_only=True) as connection:
        assert [tuple(r) for r in connection.execute("select * from allowance_event_costs order by event_id")] == costs
        assert all(":cache-format-2" in r[0] for r in connection.execute("select pricing_revision from allowance_report_cache"))


def test_failed_build_rolls_back_reuse_and_retains_invalidation(ledger):
    with open_ledger(ledger) as connection:
        add_event(connection, AT-timedelta(days=20))
        increment_ledger_revision(connection)
        connection.commit()
        before = [tuple(r) for r in connection.execute("select * from allowance_window_cache")]
        dirty = [tuple(r) for r in connection.execute("select * from allowance_window_dirty")]
    with open_ledger(ledger, read_only=True) as connection:
        with patch.object(queries, "_fit_window", side_effect=RuntimeError("synthetic failure")), pytest.raises(RuntimeError):
            indexed_allowance_report(connection, ledger, revision=ledger_revision(connection), pricing_revision="p1", coverage_complete=True)
    with open_ledger(ledger, read_only=True) as connection:
        assert before == [tuple(r) for r in connection.execute("select * from allowance_window_cache")]
        assert dirty == [tuple(r) for r in connection.execute("select * from allowance_window_dirty")]
    assert compare(ledger)[1]


def test_pinned_snapshot_rejects_advanced_writer(ledger):
    with open_ledger(ledger, read_only=True) as connection:
        connection.execute("begin")
        revision = ledger_revision(connection)
        status = queries.allowance_status(connection, now=AT)
        expected = queries.build_allowance_report(connection, status=status)
        with open_ledger(ledger) as writer:
            add_event(writer, AT-timedelta(days=20))
            writer.execute("delete from allowance_report_cache")
            increment_ledger_revision(writer)
            writer.commit()
        # Force this reader past the full-report hit without changing its
        # pinned evidence. The writer revision guard must reject window reuse.
        with patch("codex_usage.allowance_index._revisions", return_value=("p1:allowance-index-2", "new-report")):
            actual = indexed_allowance_report(connection, ledger, revision=revision, pricing_revision="p1", coverage_complete=True, status=status)
        assert actual == expected
    assert compare(ledger)[1]


def test_causal_references_never_materialize_readings_but_keep_identical_fits(ledger):
    from codex_usage.allowance_cost_pace import PaceReferences
    from codex_usage.allowance_windows import segment_windows
    with open_ledger(ledger, read_only=True) as connection:
        points, provenance, _ = queries.load_quota_evidence(connection)
    times = sorted({datetime.fromisoformat(p.timestamp).timestamp() for p in points})
    costs, unpriced = [i*.1 for i in range(len(times)+1)], [0]*(len(times)+1)
    full = queries._cost_windows(points, provenance, times, costs, unpriced, True)
    with patch.object(QuotaObservation, "to_dict", side_effect=AssertionError("Pace reference exported raw readings")):
        compact = queries._cost_windows(points, {}, times, costs, unpriced, True, references_only=True)
    assert compact == [{k: v for k, v in window.items() if k != "points"} for window in full]
    full_references, compact_references = PaceReferences(full), PaceReferences(compact)
    for window in segment_windows(points):
        anchor = window.points[-1]
        assert full_references.select(anchor, window.identity_plan) == compact_references.select(anchor, window.identity_plan)


@pytest.mark.parametrize("plan,duration,reset,credits", [("", None, None, None), ("pro", 10080, 2000000000, 0)])
def test_direct_quota_export_matches_complete_dataclass_contract(plan, duration, reset, credits):
    observation = QuotaObservation(AT.isoformat(), "codex", "secondary", plan, 12.345, duration, reset, credits)
    assert observation.to_dict() == asdict(observation)
