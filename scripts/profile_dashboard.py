"""Profile dashboard CPU work on a read-only backup of an explicit ledger."""
import argparse
import cProfile
from datetime import datetime
import io
import json
from pathlib import Path
import pstats
import sqlite3
from tempfile import TemporaryDirectory
from time import perf_counter, process_time

from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import PRICING_REVISION, render_ledger_report
from codex_usage.allowance_index import indexed_allowance_report
from codex_usage.ledger_queries import query_ledger_status
from codex_usage.ledger_schema import open_ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--now", required=True)
    parser.add_argument("--no-profile", action="store_true", help="Measure wall/CPU time without profiler overhead")
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
        with open_ledger(path, read_only=True) as connection:
            status = query_ledger_status(connection)
            wall, cpu = perf_counter(), process_time()
            indexed_allowance_report(connection, path, revision=status.revision,
                pricing_revision=PRICING_REVISION, coverage_complete=status.coverage.complete)
            observations.append({"operation": "prime monetary index", "wall_seconds": perf_counter() - wall,
                "cpu_seconds": process_time() - cpu})
        with open_ledger(path) as connection:
            connection.execute("delete from rendered_reports")
            connection.execute("delete from speed_html_cache")
            connection.commit()
        for index, range_name in enumerate(args.ranges):
            profile = cProfile.Profile(timer=process_time)
            wall, cpu = perf_counter(), process_time()
            if not args.no_profile:
                profile.enable()
            report = render_ledger_report(home, range_name=range_name, project_keys=[], theme="night",
                timezone_name="America/Toronto", now=datetime.fromisoformat(args.now))
            if not args.no_profile:
                profile.disable()
            item = {"operation": range_name, "wall_seconds": perf_counter() - wall,
                "cpu_seconds": process_time() - cpu, "cache_hit": report.cache_hit,
                "html_bytes": len(report.html.encode())}
            if not args.no_profile:
                stats = io.StringIO()
                pstats.Stats(profile, stream=stats).strip_dirs().sort_stats("cumulative").print_stats(45)
                item["profile"] = stats.getvalue()
                profile.dump_stats(str(args.output / f"{index}-{range_name}.prof"))
            observations.append(item)
            print(json.dumps({k: v for k, v in item.items() if k != "profile"}), flush=True)
            if not args.no_profile:
                print(item["profile"], flush=True)
    (args.output / "evidence.json").write_text(json.dumps({"private_input": True,
        "input_access": "SQLite mode=ro backup only; all report writes use temporary copy",
        "timings_include_profiler_overhead": not args.no_profile, "results": observations}, indent=2) + "\n")


if __name__ == "__main__":
    main()
