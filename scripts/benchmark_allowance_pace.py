"""Disposable synthetic allowance benchmark; never opens an installed ledger.

Run with uv run python scripts/benchmark_allowance_pace.py. Timings are local
Python timings, excluding extension/browser transport. JSON contains separated
quota reconstruction, continuity, rate/projection, allowance pricing and report
stages. No wall-clock timing assertions are used as CI gates.
"""
import json
from datetime import UTC, datetime, timedelta
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

import codex_usage.allowance_cost_pace as cost_pace
import codex_usage.allowance_index as index
import codex_usage.allowance_pace as pace
import codex_usage.allowance_queries as queries
from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import PRICING_REVISION, render_ledger_report
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_store import store_read
import codex_usage.allowance_pace_evidence as evidence
from codex_usage.ledger_schema import increment_ledger_revision, ledger_revision, open_ledger


def timed(function, *args, **kwargs):
    start = perf_counter()
    result = function(*args, **kwargs)
    return result, (perf_counter() - start) * 1000


def main():
    stages = {}
    phases = {}
    counts = {"allowance_prices": 0, "fits": 0, "evidence_loads": 0, "preparations": 0, "historical_cache_decodes": 0, "cost_paces": 0, "cost_range_queries": 0, "reference_selections": 0}

    def instrument(name, original, count=None):
        def measured(*args, **kwargs):
            result, elapsed = timed(original, *args, **kwargs)
            stages[name] = stages.get(name, 0) + elapsed
            if count:
                counts[count] += 1
            return result
        return measured

    with TemporaryDirectory(prefix="allowance-pace-benchmark-") as directory:
        home = Path(directory) / "codex"
        sessions = home / "sessions"
        sessions.mkdir(parents=True)
        base = datetime(2026, 9, 23, 12, tzinfo=UTC)
        quota_count = 52000
        anchor = base + timedelta(minutes=(quota_count-1)*15)
        rows = [{"timestamp": base.isoformat(), "type": "session_meta", "payload": {"id": "fixture", "cwd": "/synthetic"}},
                {"timestamp": base.isoformat(), "type": "turn_context", "payload": {"model": "gpt-5.6-sol"}}]
        for i in range(10000):
            rows.append({"timestamp": (base + timedelta(seconds=i*(anchor-base).total_seconds()/9999)).isoformat(), "type": "event_msg",
                         "payload": {"type": "token_count", "info": {"total_token_usage": {
                             "input_tokens": (i+1)*100, "total_tokens": (i+1)*100}}}})
        (sessions / "rollout-fixture.jsonl").write_text('\n'.join(map(json.dumps, rows))+'\n')
        with patch("codex_usage.allowance_capture.probe_allowance", return_value=QuotaRead(base.isoformat(), diagnostics="synthetic")):
            _, rebuild_ms = timed(capture_once, home, request_kind="manual", max_workers=1)
        ledger = ledger_database_path(home)
        points = [QuotaObservation((base+timedelta(minutes=i*15)).isoformat(), "codex", "primary" if i % 2 == 0 else "secondary", "pro",
                                   (i % 96)*.8, 1440 if i % 2 == 0 else 10080, int((base+timedelta(days=i//96+1)).timestamp()), 3)
                  for i in range(quota_count)]
        with open_ledger(ledger) as connection:
            run_id = connection.execute("select max(run_id) from capture_runs").fetchone()[0]
            for point in points:
                store_read(connection, QuotaRead(point.timestamp, "pro", (point,)), run_id)
            anchors = [replace(points[-2], timestamp=anchor.isoformat()), points[-1]]
            store_read(connection, QuotaRead(anchor.isoformat(), "pro", tuple(anchors)), run_id)
            increment_ledger_revision(connection)
            connection.commit()
        points.append(anchors[0])

        def build(pricing=PRICING_REVISION):
            with open_ledger(ledger, read_only=True) as connection:
                connection.execute("begin")
                return index.indexed_allowance_report(connection, ledger, revision=ledger_revision(connection),
                                                      pricing_revision=pricing, coverage_complete=True)

        def measure(name, function, *args, **kwargs):
            stages.clear()
            before = dict(counts)
            result, elapsed = timed(function, *args, **kwargs)
            phase = dict(stages)
            phase["total_ms"] = elapsed
            phase["rates_projection_ms"] = phase.get("evidence_plus_fit_ms", 0) - phase.get("continuity_selection_ms", 0) + phase.get("calibrated_paces_ms", 0) + phase.get("reference_preparation_ms", 0)
            phases[name] = {"timings": phase, "additional_counts": {k: counts[k] - before[k] for k in counts}}
            return result

        with patch.object(index, "_decode_cached_report", instrument("historical_cache_decode_ms", index._decode_cached_report, "historical_cache_decodes")), \
             patch.object(index, "_decode_cached_pace", instrument("compact_cache_decode_ms", index._decode_cached_pace)), \
             patch.object(evidence, "prepare_pace_evidence", instrument("causal_preparation_ms", evidence.prepare_pace_evidence, "preparations")), \
             patch.object(queries, "load_quota_evidence", instrument("quota_evidence_loading_ms", queries.load_quota_evidence, "evidence_loads")), \
             patch.object(cost_pace.PaceReferences, "__init__", instrument("reference_preparation_ms", cost_pace.PaceReferences.__init__)), \
             patch.object(cost_pace, "calibrated_paces", instrument("calibrated_paces_ms", cost_pace.calibrated_paces, "cost_paces")), \
             patch.object(cost_pace.CostPrefix, "period", instrument("cost_range_queries_ms", cost_pace.CostPrefix.period, "cost_range_queries")), \
             patch.object(cost_pace.PaceReferences, "select", instrument("reference_selection_ms", cost_pace.PaceReferences.select, "reference_selections")), \
             patch.object(pace, "active_evidence", instrument("continuity_selection_ms", pace.active_evidence)), \
             patch.object(pace, "fit_paces", instrument("evidence_plus_fit_ms", pace.fit_paces, "fits")), \
             patch.object(index, "estimate_cost", instrument("allowance_pricing_ms", index.estimate_cost, "allowance_prices")):
            report = measure("first_allowance_report", build)
            assert any(p["method"] == "calibrated cost" and p["rate"] > 0 for row in report["paces"] for p in row)
            first_counts = dict(counts)
            def render(**kw):
                return render_ledger_report(home, range_name="all", project_keys=kw.pop("project_keys", []),
                                            theme=kw.pop("theme", "day"), timezone_name="UTC", now=anchor, **kw)
            measure("first_html_report", render)
            measure("warm_same_view", render)
            measure("uncached_changed_view", render, theme="night", project_keys=["other"])
            # An uncached changed view renders the history. Only a warm HTML
            # hit must avoid reading/decoding that historical payload entirely.
            for name in ("first_html_report", "warm_same_view", "uncached_changed_view"):
                assert all(phases[name]["additional_counts"][key] == 0
                           for key in ("allowance_prices", "fits", "evidence_loads", "preparations", "cost_paces", "cost_range_queries", "reference_selections"))
            assert phases["warm_same_view"]["additional_counts"]["historical_cache_decodes"] == 0
            with open_ledger(ledger, read_only=True) as connection:
                sizes = {"compact" if row[0].endswith(":pace-state") else "historical": row[1]
                         for row in connection.execute("select pricing_revision,length(cast(report_json as blob)) from allowance_report_cache")}
            prepared = measure("standalone_preparation", evidence.prepare_pace_evidence, points, points)
            for number, endpoint in enumerate(anchors):
                measure(f"prepared_origin_fit_{number}", pace.fit_paces, prepared, endpoint)
            measure("prepared_earlier_origin_fit", pace.fit_paces, prepared, points[-5])
            long_cycle = [replace(p, limit_id="long-cycle", duration_minutes=10080,
                                  used_percent=10+i/2000, resets_at=None)
                          for i, p in enumerate(points[:quota_count])]
            cycle_prepared = measure("long_cycle_preparation", evidence.prepare_pace_evidence,
                                     long_cycle, {long_cycle[-1]})
            cycle_result = measure("long_cycle_origin_fit", pace.fit_paces,
                                   cycle_prepared, long_cycle[-1])[2]
            assert cycle_result["observations"] == quota_count
            assert cycle_result["span_seconds"] > 86400
            assert cycle_result["rate"] == cycle_result["movement"] / (cycle_result["span_seconds"] / 3600)
            with open_ledger(ledger, read_only=True) as connection:
                connection.execute("begin")
                oracle = queries.build_allowance_report(connection)
            for key in ("windows", "qualified", "headline", "headline_previous", "history", "paces"):
                assert report[key] == oracle[key]
            # Removing pace evaluation proves the full monetary path is unchanged.
            with patch.object(pace, "fit_paces", return_value=[]), open_ledger(ledger, read_only=True) as connection:
                old = queries.build_allowance_report(connection)
            for key in ("windows", "qualified", "headline", "headline_previous", "history"):
                assert report[key] == old[key]
            with open_ledger(ledger) as connection:
                latest = points[-1]
                updated = QuotaObservation((anchor+timedelta(minutes=15)).isoformat(), latest.limit_id, latest.slot,
                                           latest.plan, 77, latest.duration_minutes, latest.resets_at)
                store_read(connection, QuotaRead(updated.timestamp, "pro", (updated, replace(anchors[1], timestamp=updated.timestamp))), run_id)
                increment_ledger_revision(connection)
                connection.commit()
            before = counts["allowance_prices"]
            measure("quota_update_report", build)
            assert counts["allowance_prices"] == before
            event = {"timestamp": (anchor+timedelta(minutes=15)).isoformat(), "type": "event_msg",
                     "payload": {"type": "token_count", "info": {"total_token_usage": {
                         "input_tokens": 1000100, "total_tokens": 1000100}}}}
            with (sessions / "rollout-fixture.jsonl").open("a") as handle:
                handle.write(json.dumps(event)+'\n')
            with patch("codex_usage.allowance_capture.probe_allowance", return_value=QuotaRead(updated.timestamp, "pro", (updated,))):
                measure("synthetic_event_update_capture", capture_once, home, request_kind="manual", max_workers=1)
            before = counts["allowance_prices"]
            measure("event_update_report", build)
            assert counts["allowance_prices"] - before == 1
            before = counts["allowance_prices"]
            measure("simulated_upgrade_allowance_repricing_report", build, "synthetic-upgrade-pricing")
            assert counts["allowance_prices"] - before == 10001
        print(json.dumps({"synthetic_events": 10000, "quota_points": len(points), "active_buckets": len(anchors), "first_counts": first_counts,
                          "cache_payload_bytes": sizes,
                          "dollar_and_indexed_full_preservation": "exact equality", "initial_capture_rebuild_ms": rebuild_ms,
                          "phases": phases,
                          "scope": "local Python only; no UI/HTTP transport; per-phase instrumentation; existing language valuation is part of HTML totals"}, indent=2))


if __name__ == "__main__":
    main()
