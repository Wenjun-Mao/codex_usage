"""Profile dashboard CPU work on a read-only backup of an explicit ledger."""
import argparse
import cProfile
from contextlib import contextmanager, ExitStack
from datetime import datetime
import io
import hashlib
import json
from pathlib import Path
import pstats
import sqlite3
import sys
from tempfile import TemporaryDirectory
from time import perf_counter, process_time
from unittest.mock import patch

from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import PRICING_REVISION, render_ledger_report
from codex_usage.allowance_index import indexed_allowance_report
from codex_usage.ledger_queries import query_ledger_status
from codex_usage.ledger_schema import increment_ledger_revision, open_ledger
from collector_benchmark_guard import audit_guard


@contextmanager
def phase_timings(enabled):
    """Observe coarse boundaries without per-event profiler overhead."""
    phases = {}
    if not enabled:
        yield phases
        return
    from codex_usage import allowance_history_reports, allowance_index, ledger_materialization, project_economics

    def observe(name, function):
        def measured(*args, **kwargs):
            wall, cpu = perf_counter(), process_time()
            try:
                return function(*args, **kwargs)
            finally:
                row = phases.setdefault(name, dict(calls=0, wall_seconds=0.0, cpu_seconds=0.0))
                row['calls'] += 1
                row['wall_seconds'] += perf_counter()-wall
                row['cpu_seconds'] += process_time()-cpu
        return measured

    with ExitStack() as stack:
        for module, name in ((allowance_index, 'encode_report'),
                             (ledger_materialization, 'value_records'),
                             (project_economics, '_turn_metrics'),
                             (allowance_history_reports, '_decode_cached_report')):
            stack.enter_context(patch.object(module, name, observe(name, getattr(module, name))))
        yield phases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--now", required=True)
    parser.add_argument("--no-profile", action="store_true", help="Measure wall/CPU time without profiler overhead")
    parser.add_argument("--phase-timings", action="store_true",
                        help="Observe encoding, batch pricing and turn costs; diagnostic samples only")
    parser.add_argument('--history-details', type=int, default=0, choices=range(13),
                        help='Also measure up to 12 distinct issued period-detail pages of the last range')
    parser.add_argument("--account-mode", choices=("prime", "revision", "empty"), default="prime",
                        help="Keep priming explicit; revision measures an unprimed post-revision load")
    parser.add_argument("--output", type=Path, default=Path("output/performance/dashboard-profile"))
    parser.add_argument("--ranges", nargs="+", default=["today", "yesterday", "7d", "30d", "all", "today", "yesterday"])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    observations = []
    with TemporaryDirectory(prefix="dashboard-profile-") as raw:
        home = Path(raw) / "codex"
        path = ledger_database_path(home)
        path.parent.mkdir(parents=True, mode=0o700)
        with sqlite3.connect(args.ledger.resolve().as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(path) as target:
            source.backup(target)
        path.chmod(0o600)
        sys.addaudithook(audit_guard(Path(raw), report=True))
        if args.account_mode == "prime":
            with open_ledger(path, read_only=True) as connection:
                status = query_ledger_status(connection)
                wall, cpu = perf_counter(), process_time()
                indexed_allowance_report(connection, path, revision=status.revision,
                    pricing_revision=PRICING_REVISION, coverage_complete=status.coverage.complete)
                observations.append({"operation": "prime monetary index", "wall_seconds": perf_counter() - wall,
                    "cpu_seconds": process_time() - cpu})
        with open_ledger(path) as connection:
            if args.account_mode != "prime":
                increment_ledger_revision(connection)
            if args.account_mode == "empty":
                for table in ("allowance_report_cache", "allowance_event_costs", "allowance_window_cache"):
                    if connection.execute("select 1 from sqlite_master where name=?", (table,)).fetchone():
                        connection.execute(f"delete from {table}")
            connection.execute("delete from rendered_reports")
            connection.execute("delete from speed_html_cache")
            connection.commit()
        def measure(range_name, *, action=None, label=None):
            index = len(observations)
            label = label or range_name
            profile = cProfile.Profile(timer=process_time)
            wall, cpu = perf_counter(), process_time()
            if not args.no_profile:
                profile.enable()
            with phase_timings(args.phase_timings) as phases:
                report = render_ledger_report(home, range_name=range_name, project_keys=[], theme="night",
                    timezone_name="America/Toronto", now=datetime.fromisoformat(args.now),
                    allowance_action=json.dumps(action) if action is not None else None)
            if not args.no_profile:
                profile.disable()
            item = {"operation": label, "wall_seconds": perf_counter() - wall,
                "cpu_seconds": process_time() - cpu, "cache_hit": report.cache_hit,
                "html_bytes": len(report.html.encode())}
            from benchmark_collector import allowance_scope_html
            item['html_sha256'] = hashlib.sha256(report.html.encode()).hexdigest()
            item['allowance_scope_html_sha256'] = hashlib.sha256(
                allowance_scope_html(report.html, report.allowance_navigation).encode()).hexdigest()
            if args.phase_timings:
                item['phases'] = phases
            if not args.no_profile:
                stats = io.StringIO()
                pstats.Stats(profile, stream=stats).strip_dirs().sort_stats("cumulative").print_stats(45)
                item["profile"] = stats.getvalue()
                profile.dump_stats(str(args.output / f"{index}-{range_name}.prof"))
            observations.append(item)
            print(json.dumps({k: v for k, v in item.items() if k != "profile"}), flush=True)
            if not args.no_profile:
                print(item["profile"], flush=True)
            return report

        for range_name in args.ranges:
            report = measure(range_name)
        actions = [a for a in (report.allowance_navigation or {}).get('actions', [])
                   if a['state']['kind'] == 'periods'][:args.history_details]
        for index, action in enumerate(actions):
            measure(args.ranges[-1], action=action, label=f'history detail {index+1}')
    (args.output / "evidence.json").write_text(json.dumps({"private_input": True,
        "input_access": "SQLite mode=ro backup only; all report writes use temporary copy",
        "account_mode": args.account_mode,
        "phase_instrumentation": args.phase_timings,
        "timings_include_profiler_overhead": not args.no_profile, "results": observations}, indent=2) + "\n")


if __name__ == "__main__":
    main()
