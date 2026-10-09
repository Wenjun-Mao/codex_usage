"""Controlled release/candidate timings on identical disposable ledger snapshots."""
import argparse
from contextlib import ExitStack
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch


def measure(args):
    from codex_usage.agent_paths import ledger_database_path
    from codex_usage.agent_reports import render_ledger_report
    from codex_usage.ledger_schema import open_ledger
    import codex_usage.agent_reports as reports
    import codex_usage.speed_reports as speed
    components = {}
    work_counts = {}
    def timed(module, name, label, stack):
        original = getattr(module, name)
        def run(*values, **kwargs):
            started = perf_counter()
            try:
                result = original(*values, **kwargs)
                if name in {"query_ledger_records", "value_records"}:
                    work_counts[label] = work_counts.get(label, 0)+len(result)
                return result
            finally:
                components[label] = components.get(label, 0) + perf_counter() - started
        stack.enter_context(patch.object(module, name, run))
    with open_ledger(ledger_database_path(args.home)) as connection:
        for table in ("rendered_reports", "speed_html_cache", "allowance_report_cache"):
            connection.execute(f"delete from {table}")
        connection.commit()
    with ExitStack() as stack:
        timed(speed, "render_speed_report", "speed_and_base_inclusive", stack)
        timed(reports, "_render_base_ledger_report", "base_report_inclusive", stack)
        timed(reports, "materialize_ledger", "base_materialization", stack)
        timed(reports, "indexed_allowance_report", "base_allowance_preparation", stack)
        if args.candidate:
            import codex_usage.breakdown_reports as breakdown
            import codex_usage.report_usage_breakdown as renderer
            timed(breakdown, "prepare", "derived_preparation", stack)
            for name in ("prepare_evidence", "query_ledger_records", "value_records", "aggregate"):
                timed(breakdown, name, "derived_" + name, stack)
            timed(renderer, "render_breakdown", "derived_final_render", stack)
            timed(breakdown, "store", "derived_cache_write", stack)
            import codex_usage.breakdown_evidence as evidence_module
            for name in ("prepare_balances", "observed_windows"):
                if hasattr(evidence_module, name):
                    timed(evidence_module, name, "derived_"+name, stack)
        def render(action=None):
            kwargs = {"range_name": args.range, "project_keys": [], "theme": "day",
                "timezone_name": "UTC", "now": datetime.fromisoformat(args.now)}
            if action is not None:
                kwargs["breakdown_action"] = json.dumps(action)
            return render_ledger_report(args.home, **kwargs)
        started = perf_counter()
        cold = render()
        result = {"cold_seconds": perf_counter()-started, "cold_components_seconds": dict(components),
            "cold_component_record_counts": dict(work_counts), "html_bytes": len(cold.html.encode()), "revision": cold.ledger_revision}
        components.clear()
        work_counts.clear()
        started = perf_counter()
        warm = render()
        result["warm_seconds"] = perf_counter()-started
        result["warm_components_seconds"] = dict(components)
        result["warm_component_record_counts"] = dict(work_counts)
        assert warm.html == cold.html
        if args.candidate:
            current = cold
            times = []
            for changes in ({"metric": "tokens"}, {"view": "project"}, {"metric": "cost"}, {"view": "hour"}, {"group": "project"}):
                desired = {**current.breakdown_navigation["state"], **changes}
                action = next(a for a in current.breakdown_navigation["actions"] if a["state"] == desired)
                started = perf_counter()
                current = render(action)
                times.append(perf_counter()-started)
            result["warm_control_seconds"] = times
            window_times = []
            for action in (a for a in cold.breakdown_navigation["actions"] if a["state"]["basis"].startswith("window:")):
                started = perf_counter()
                render(action)
                window_times.append(perf_counter()-started)
            result["warm_window_seconds"] = window_times
            result["warm_derived_prepare_calls"] = components.get("derived_preparation", 0)
        # Monetary markup before/after insertion must be byte-identical against
        # the actual release, not a candidate's own accounting implementation.
        html = cold.html
        if args.candidate:
            first = html.index('<style>\n    .usage-breakdown')
            last = html.index('<section class="section observed-speed"')
            html = html[:first] + html[last:]
        result["base_html_sha256"] = hashlib.sha256(html.encode()).hexdigest()
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output/playwright/usage-breakdown/controlled-perf.json"))
    parser.add_argument("--release", default="v2.11.1")
    parser.add_argument("--accepted", help="Optional accepted candidate ref for a third paired observation")
    parser.add_argument("--synthetic", action="store_true", help="Label a supplied synthetic ledger explicitly")
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--candidate", action="store_true")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--range")
    parser.add_argument("--now")
    args = parser.parse_args()
    if args.measure:
        measure(args)
        return
    if args.ledger is None:
        parser.error("--ledger is required; live access is read-only backup only")
    repo = Path(__file__).resolve().parents[1]
    release = subprocess.check_output(["git", "rev-parse", args.release], cwd=repo, text=True).strip()
    evidence = {"release": release, "candidate_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "candidate_working_tree": True, "synthetic_only": args.synthetic,
        "live_access": "none; supplied synthetic ledger only" if args.synthetic else "one SQLite mode=ro backup; no live report or capture",
        "cache_protocol": "identical pre-existing cost index; discard rendered/speed/allowance report caches on each copy",
        "component_contract": "inclusive nested times; do not sum overlapping base subcomponents",
        "observations_only": True, "results": {}}
    source_files = sorted((repo / "src/codex_usage").glob("*.py"))
    evidence["candidate_python_source_sha256"] = hashlib.sha256(b"".join(
        p.name.encode()+b"\0"+p.read_bytes() for p in source_files)).hexdigest()
    with TemporaryDirectory(prefix="breakdown-comparison-") as raw:
        root = Path(raw)
        snapshot = root / "snapshot.sqlite3"
        with sqlite3.connect(args.ledger.resolve().as_uri()+"?mode=ro", uri=True) as source, sqlite3.connect(snapshot) as target:
            source.backup(target)
        snapshot.chmod(0o600)
        with sqlite3.connect(snapshot) as connection:
            count, first, last = connection.execute("select count(*),min(timestamp_us),max(timestamp_us) from ledger_usage_events").fetchone()
            evidence["source_shape"] = {"usage_events": count, "usage_span_days": (last-first)/86400e6 if count else 0,
                "projects": connection.execute("select count(*) from ledger_projects").fetchone()[0],
                "weekly_observations": connection.execute("select count(*) from quota_observations where duration_minutes=10080").fetchone()[0]}
        authorities = {"candidate": repo}
        refs = {"release": release}
        if args.accepted:
            refs["accepted"] = subprocess.check_output(["git", "rev-parse", args.accepted], cwd=repo, text=True).strip()
            evidence["accepted"] = refs["accepted"]
        for name, ref in refs.items():
            authority = root / name
            authority.mkdir()
            archive = subprocess.check_output(["git", "archive", ref, "src"], cwd=repo)
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(authority, filter="data")
            authorities[name] = authority
        now = datetime.now(UTC).isoformat()
        for report_range in ("today", "all"):
            observations = {}
            for name in ("release", *( ["accepted"] if args.accepted else []), "candidate"):
                home = root / f"{report_range}-{name}"
                copy = home / ".codex-usage/usage-ledger.sqlite3"
                copy.parent.mkdir(parents=True, mode=0o700)
                with sqlite3.connect(snapshot) as source, sqlite3.connect(copy) as target:
                    source.backup(target)
                copy.chmod(0o600)
                command = [sys.executable, str(Path(__file__).resolve()), "--measure", "--home", str(home), "--range", report_range, "--now", now]
                if name != "release":
                    command.append("--candidate")
                env = dict(os.environ, PYTHONPATH=str(authorities[name] / "src"),
                    HOME=str(root / "isolated-home"), CODEX_HOME=str(home))
                observations[name] = json.loads(subprocess.check_output(command, env=env, cwd=root, text=True))
            assert observations["release"]["revision"] == observations["candidate"]["revision"]
            assert observations["release"]["base_html_sha256"] == observations["candidate"]["base_html_sha256"], report_range
            if args.accepted:
                assert observations["release"]["base_html_sha256"] == observations["accepted"]["base_html_sha256"], report_range
            observations["base_html_parity"] = True
            evidence["results"][report_range] = observations
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2)+"\n")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
