"""Compare post-capture reports on disposable copies with synthetic mutations.

No live captures, task-body reads or quota RPCs. Source ledger is opened read-only.
"""
import argparse
import cProfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter, process_time
from unittest.mock import patch

from benchmark_capture_load import copy_ledger


def add_event(connection, stamp):
    source = connection.execute("""select e.* from ledger_usage_events e
        join ledger_generations g using(generation_id) where g.status='trusted'
        order by e.timestamp_us desc, e.event_id desc limit 1""").fetchone()
    if source is None:
        raise ValueError("Benchmark requires trusted usage events")
    row = dict(source)
    row.pop("event_id")
    row.update(timestamp=stamp.isoformat(), timestamp_us=round(stamp.timestamp()*1e6),
        input_tokens=1000, cached_input_tokens=900, cache_write_input_tokens=0,
        output_tokens=100, reasoning_output_tokens=20, total_tokens=1100)
    row["source_record_index"] = connection.execute("""select max(source_record_index)+1
        from ledger_usage_events where generation_id=?""", (row["generation_id"],)).fetchone()[0]
    connection.execute(f"insert into ledger_usage_events ({','.join(row)}) values ({','.join('?' for _ in row)})", tuple(row.values()))


def measure_batch_insert(connection, stamp, *, count=10000):
    """Measure capture-style append writes in one transaction on this copy."""
    row = dict(connection.execute("""select e.* from ledger_usage_events e
        join ledger_generations g using(generation_id) where g.status='trusted' limit 1""").fetchone())
    row.pop("event_id")
    start = connection.execute("select max(source_record_index)+1 from ledger_usage_events where generation_id=?",
        (row["generation_id"],)).fetchone()[0]
    values = []
    for i in range(count):
        at = stamp+timedelta(microseconds=i)
        record = dict(row, timestamp=at.isoformat(), timestamp_us=round(at.timestamp()*1e6), source_record_index=start+i)
        values.append(tuple(record.values()))
    sql = f"insert into ledger_usage_events ({','.join(row)}) values ({','.join('?' for _ in row)})"
    wall, cpu = perf_counter(), process_time()
    connection.execute("begin immediate")
    connection.executemany(sql, values)
    connection.commit()
    return dict(events=count, seconds=perf_counter()-wall, cpu_seconds=process_time()-cpu)


def measure(args):
    import codex_usage.breakdown_reports as breakdown
    import codex_usage.allowance_queries as allowance
    from codex_usage.agent_paths import ledger_database_path
    from codex_usage.agent_reports import render_ledger_report
    from codex_usage.allowance_models import QuotaObservation
    from codex_usage.allowance_probe import QuotaRead
    from codex_usage.allowance_queries import allowance_status
    from codex_usage.allowance_store import store_observations, store_read
    from codex_usage.ledger_schema import increment_ledger_revision, open_ledger
    breakdown.BREAKDOWN_REVISION = 10000
    path = ledger_database_path(args.home)
    now = datetime.fromisoformat(args.now)
    with open_ledger(path) as connection:
        latest = connection.execute("select max(timestamp_us) from ledger_usage_events").fetchone()[0]
        quota = connection.execute("select max(last_timestamp) from quota_observations").fetchone()[0]
        now = max(now, datetime.fromtimestamp(latest/1e6, UTC), datetime.fromisoformat(quota)) + timedelta(seconds=60)
        status = allowance_status(connection, now=now)
        anchors = [QuotaObservation(**{k: b[k] for k in QuotaObservation.__dataclass_fields__}) for b in status["active_buckets"]]
        if not anchors:
            raise ValueError("Benchmark requires captured quota anchors")
        connection.execute("delete from rendered_reports")
        connection.execute("delete from allowance_report_cache")
        connection.execute("delete from speed_html_cache")
        if connection.execute("select 1 from sqlite_master where name='allowance_window_cache'").fetchone():
            connection.execute("delete from allowance_window_cache")
        connection.commit()
    results = []
    for scenario in ("initial fill", "revision only", "appended usage and quota", "late usage", "late quota"):
        write_wall, write_cpu = perf_counter(), process_time()
        with open_ledger(path) as connection:
            if scenario == "appended usage and quota":
                now += timedelta(seconds=60)
                add_event(connection, now)
                store_read(connection, QuotaRead(now.isoformat(), status["plan"], tuple(
                    replace(p, timestamp=now.isoformat(), used_percent=min(100, p.used_percent+1)) for p in anchors)), None)
            elif scenario == "late usage":
                earliest = connection.execute("select min(timestamp_us) from ledger_usage_events").fetchone()[0]
                add_event(connection, datetime.fromtimestamp(earliest/1e6, UTC)+timedelta(seconds=1))
            elif scenario == "late quota":
                row = connection.execute("select * from quota_observations order by timestamp,rowid limit 1").fetchone()
                point = QuotaObservation(**{k: row[k] for k in QuotaObservation.__dataclass_fields__})
                store_observations(connection, [replace(point, used_percent=(point.used_percent+1) % 100)],
                    source_key="synthetic-benchmark", provenance="recovered")
            increment_ledger_revision(connection)
            connection.commit()
        write_wall, write_cpu = perf_counter()-write_wall, process_time()-write_cpu
        wall, cpu = perf_counter(), process_time()
        fits = 0
        original = allowance.estimate_window
        def counted(*args, **kwargs):
            nonlocal fits
            fits += 1
            return original(*args, **kwargs)
        profile = cProfile.Profile(timer=process_time) if args.profile_scenario == scenario else None
        if profile:
            profile.enable()
        with patch.object(allowance, "estimate_window", counted):
            report = render_ledger_report(args.home, range_name="today", project_keys=[], theme="night",
                timezone_name="America/Toronto", now=now)
        if profile:
            profile.disable()
            args.output.parent.mkdir(parents=True, exist_ok=True)
            profile.dump_stats(str(args.output.with_suffix(".prof")))
        elapsed, elapsed_cpu = perf_counter()-wall, process_time()-cpu
        with open_ledger(path, read_only=True) as connection:
            cache_bytes = connection.execute("select max(length(report_json)) from allowance_report_cache").fetchone()[0]
        results.append(dict(scenario=scenario, seconds=elapsed, cpu_seconds=elapsed_cpu, account_cache_bytes=cache_bytes,
            mutation_seconds=write_wall, mutation_cpu_seconds=write_cpu, window_fits=fits,
            html_sha256=hashlib.sha256(report.html.encode()).hexdigest(), cache_hit=report.cache_hit))
    with open_ledger(path) as connection:
        results[0]["batch_insert"] = measure_batch_insert(connection, now+timedelta(hours=1))
    print(json.dumps(results))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--baseline-source", type=Path)
    parser.add_argument("--now", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("output/performance/capture-load/history-reuse.json"))
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--profile-scenario", choices=("initial fill", "revision only", "appended usage and quota", "late usage", "late quota"))
    args = parser.parse_args()
    if args.measure:
        measure(args)
        return
    if not args.ledger or not args.baseline_source or args.repeats < 1:
        parser.error("--ledger, --baseline-source and positive --repeats required")
    repo = Path(__file__).resolve().parents[1]
    evidence = {"baseline_source": str(args.baseline_source.resolve()), "fixed_clock_floor": args.now,
        "scope": "frozen ledger, synthetic mutations, full HTML parity; no live capture or native painting", "results": []}
    with TemporaryDirectory(prefix="allowance-reuse-") as raw:
        root = Path(raw)
        frozen = root / "input.sqlite3"
        copy_ledger(args.ledger, frozen)
        for repeat in range(args.repeats):
            pair = {}
            sources = [("baseline", args.baseline_source.resolve()), ("candidate", repo / "src")]
            for label, source in (sources if repeat % 2 == 0 else reversed(sources)):
                home = root / f"{label}-{repeat}"
                copy_ledger(frozen, home / ".codex-usage/usage-ledger.sqlite3")
                environment = dict(os.environ, PYTHONPATH=str(source), CODEX_HOME=str(home))
                command = [sys.executable, str(Path(__file__).resolve()), "--measure", "--home", str(home), "--now", args.now]
                if args.profile_scenario:
                    command.extend(["--profile-scenario", args.profile_scenario, "--output",
                        str(args.output.resolve().with_name(f"{args.output.stem}-{label}-{repeat}.json"))])
                pair[label] = json.loads(subprocess.check_output(command, env=environment, cwd=root, text=True))
                print(repeat, label, [(r["scenario"], round(r["seconds"], 3)) for r in pair[label]], flush=True)
            for old, new in zip(pair["baseline"], pair["candidate"], strict=True):
                assert old["html_sha256"] == new["html_sha256"], old["scenario"]
            evidence["results"].append(pair)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2)+"\n")


if __name__ == "__main__":
    main()
