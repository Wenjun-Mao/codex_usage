"""Disposable synthetic allowance benchmark; never opens an installed ledger.

Run with uv run python scripts/benchmark_allowance_pace.py. Timings are local
Python timings, excluding extension/browser transport. JSON contains separated
quota reconstruction, continuity, rate/projection, allowance pricing and report
stages. No wall-clock timing assertions are used as CI gates.
"""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

import codex_usage.allowance_index as index
import codex_usage.allowance_pace as pace
import codex_usage.allowance_queries as queries
from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import PRICING_REVISION, render_ledger_report
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_store import store_read
from codex_usage.ledger_schema import increment_ledger_revision, ledger_revision, open_ledger


def timed(function, *args, **kwargs):
    start = perf_counter()
    result = function(*args, **kwargs)
    return result, (perf_counter() - start) * 1000


def main():
    stages = {}
    phases = {}
    counts = {"allowance_prices": 0, "fits": 0, "evidence_loads": 0}

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
        anchor = base + timedelta(days=7, hours=23, minutes=45)
        rows = [{"timestamp": base.isoformat(), "type": "session_meta", "payload": {"id": "fixture", "cwd": "/synthetic"}},
                {"timestamp": base.isoformat(), "type": "turn_context", "payload": {"model": "gpt-5.6-sol"}}]
        for i in range(10000):
            rows.append({"timestamp": (base + timedelta(minutes=i)).isoformat(), "type": "event_msg",
                         "payload": {"type": "token_count", "info": {"total_token_usage": {
                             "input_tokens": (i+1)*100, "total_tokens": (i+1)*100}}}})
        (sessions / "rollout-fixture.jsonl").write_text('\n'.join(map(json.dumps, rows))+'\n')
        with patch("codex_usage.allowance_capture.probe_allowance", return_value=QuotaRead(base.isoformat(), diagnostics="synthetic")):
            _, rebuild_ms = timed(capture_once, home, request_kind="manual", max_workers=1)
        ledger = ledger_database_path(home)
        points = [QuotaObservation((base+timedelta(minutes=i*15)).isoformat(), "codex", "primary", "pro",
                                   (i % 96)*.8, 1440, int((base+timedelta(days=i//96+1)).timestamp()), 3)
                  for i in range(768)]
        with open_ledger(ledger) as connection:
            run_id = connection.execute("select max(run_id) from capture_runs").fetchone()[0]
            for point in points:
                store_read(connection, QuotaRead(point.timestamp, "pro", (point,)), run_id)
            increment_ledger_revision(connection)
            connection.commit()

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
            phase["rates_projection_ms"] = phase.get("evidence_plus_fit_ms", 0) - phase.get("continuity_selection_ms", 0)
            phases[name] = {"timings": phase, "additional_counts": {k: counts[k] - before[k] for k in counts}}
            return result

        with patch.object(queries, "load_quota_evidence", instrument("quota_evidence_loading_ms", queries.load_quota_evidence, "evidence_loads")), \
             patch.object(pace, "active_evidence", instrument("continuity_selection_ms", pace.active_evidence)), \
             patch.object(pace, "fit_paces", instrument("evidence_plus_fit_ms", pace.fit_paces, "fits")), \
             patch.object(index, "estimate_cost", instrument("allowance_pricing_ms", index.estimate_cost, "allowance_prices")):
            report = measure("first_allowance_report", build)
            first_counts = dict(counts)
            def render(**kw):
                return render_ledger_report(home, range_name="all", project_keys=kw.pop("project_keys", []),
                                            theme=kw.pop("theme", "day"), timezone_name="UTC", now=anchor, **kw)
            measure("first_html_report", render)
            measure("warm_same_view", render)
            measure("warm_changed_view", render, theme="night", project_keys=["other"])
            assert counts == first_counts, "warm views must not reprice allowance or reconstruct/refit quota"
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
                store_read(connection, QuotaRead(updated.timestamp, "pro", (updated,)), run_id)
                increment_ledger_revision(connection)
                connection.commit()
            before = counts["allowance_prices"]
            measure("quota_update_report", build)
            assert counts["allowance_prices"] == before
            measure("simulated_upgrade_allowance_repricing_report", build, "synthetic-upgrade-pricing")
            assert counts["allowance_prices"] - before == 10000
        print(json.dumps({"synthetic_events": 10000, "quota_points": len(points), "first_counts": first_counts,
                          "warm_additional_counts": {key: 0 for key in counts},
                          "dollar_and_indexed_full_preservation": "exact equality", "initial_capture_rebuild_ms": rebuild_ms,
                          "phases": phases,
                          "scope": "local Python only; no UI/HTTP transport; per-phase instrumentation; existing language valuation is part of HTML totals"}, indent=2))


if __name__ == "__main__":
    main()
