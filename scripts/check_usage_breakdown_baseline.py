"""Read-only live SQLite snapshot to a disposable home; never report on live state."""
import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import render_ledger_report
from codex_usage.aggregation import resolve_report_range, summarize_valued_records
from codex_usage.breakdown_reports import load
from codex_usage.ledger_materialization import materialize_ledger
from codex_usage.ledger_queries import query_ledger_status
from codex_usage.ledger_schema import open_ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("output/playwright/usage-breakdown/private-baseline.json"))
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()
    evidence = {"private_baseline": not args.synthetic, "synthetic_only": args.synthetic,
        "live_access": "none; supplied synthetic ledger only" if args.synthetic else "SQLite mode=ro backup only; no report/capture on live home"}
    with TemporaryDirectory(prefix="breakdown-baseline-") as raw:
        home = Path(raw)
        copy = ledger_database_path(home)
        copy.parent.mkdir(parents=True, mode=0o700)
        started = perf_counter()
        with sqlite3.connect(args.ledger.resolve().as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(copy) as target:
            source.backup(target)
        copy.chmod(0o600)
        evidence["snapshot_copy_seconds"] = perf_counter() - started
        now = datetime.now(UTC)
        with open_ledger(copy) as connection:
            # Discard only disposable render data on the disposable copy, so
            # cold preparation is measured rather than borrowing live HTML.
            connection.execute("delete from rendered_reports")
            connection.execute("delete from speed_html_cache")
            connection.commit()
        def render(action=None):
            return render_ledger_report(home, range_name="all", project_keys=[], theme="day",
                timezone_name="UTC", now=now, breakdown_action=json.dumps(action) if action else None)
        started = perf_counter()
        first = render()
        evidence["cold_all_report_seconds"] = perf_counter() - started
        with open_ledger(copy, read_only=True) as connection:
            key = connection.execute("select cache_key from rendered_reports where cache_key like 'breakdown:%:metadata'").fetchone()[0]
            metadata = load(connection, key)
            evidence["cold_derived_preparation_seconds"] = metadata["cold_seconds"]
            status = query_ledger_status(connection)
            materialized = materialize_ledger(connection, resolve_report_range("all", UTC, now=now), [], UTC, status, auto_transitions=True)
            oracle = summarize_valued_records(materialized.valued)
            actual = load(connection, key[:-len("metadata")] + "selected:summary")["total"]
            assert abs(actual["cost"] - oracle.cost.total_usd) <= max(1e-9, abs(oracle.cost.total_usd) * 1e-12)
            assert actual["tokens"] == oracle.usage.total_tokens
            assert actual["unknown"] + actual["api_excluded"] == oracle.cost.unpriced_tokens
            assert abs(actual["credits"] - oracle.credits.total_credits) <= max(1e-9, abs(oracle.credits.total_credits) * 1e-12)
            assert actual["credit_unknown"] == oracle.credits.unpriced_tokens
            evidence["monetary_token_credit_parity"] = True
            evidence["ledger_revision"] = status.revision
            evidence["local_coverage_complete"] = status.coverage.complete
        def forbidden(*args, **kwargs):
            raise AssertionError("warm controls performed historical work")
        times = []
        with patch("codex_usage.breakdown_reports.prepare", forbidden), patch("codex_usage.allowance_index._decode_cached_report", forbidden), patch("codex_usage.agent_reports.materialize_ledger", forbidden), patch("codex_usage.breakdown_reports.query_ledger_records", forbidden):
            started = perf_counter()
            assert render().html == first.html
            evidence["warm_all_report_seconds"] = perf_counter() - started
            current = first
            for changes in ({"metric": "tokens"}, {"view": "project"}, {"metric": "credits"}, {"metric": "cost"}, {"view": "hour"}, {"group": "project"}):
                desired = {**current.breakdown_navigation["state"], **changes}
                action = next(a for a in current.breakdown_navigation["actions"] if a["state"] == desired)
                started = perf_counter()
                current = render(action)
                times.append(perf_counter() - started)
            for action in (a for a in first.breakdown_navigation["actions"] if a["state"]["basis"].startswith("window:")):
                started = perf_counter()
                render(action)
                times.append(perf_counter()-started)
        evidence["warm_navigation_seconds"] = times
        evidence["warm_history_fits_repricing_materializations"] = 0
        evidence["html_bytes"] = len(first.html.encode())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
