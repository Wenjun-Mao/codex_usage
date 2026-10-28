"""Paired source-backed capture/report measurements on owned disposable inputs."""
import argparse
import cProfile
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import hashlib
import gc
from importlib.metadata import distributions
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import statistics
import subprocess
import sys
import sysconfig
import tempfile
from time import perf_counter, process_time
from unittest.mock import patch
from urllib.parse import quote, unquote

from collector_benchmark_guard import audit_guard


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def allowance_scope_html(html, navigation):
    """Normalize only validated issued scope hashes changed by a codec revision."""
    from codex_usage.allowance_history_navigation import validate_action

    def normalized(match):
        actions = json.loads(unquote(match[1]))
        if not isinstance(actions, list) or len(actions) != 1:
            raise ValueError("Invalid benchmark allowance action")
        action = validate_action(actions[0])
        if navigation is None or action not in navigation['actions'] or action['scope'] != navigation['scope']:
            raise ValueError("Benchmark allowance link was not issued")
        if quote(json.dumps(actions, separators=(',', ':')), safe='') != match[1]:
            raise ValueError("Noncanonical benchmark allowance action")
        target = dict(action, scope='0'*64)
        return 'command:codexUsage.navigateAllowanceHistory?' + quote(json.dumps([target], separators=(',', ':')), safe='')

    return re.sub(r'command:codexUsage.navigateAllowanceHistory\?([^"<>\s]+)', normalized, html)


def measure(args):
    home = args.home.resolve()
    os.environ.update(HOME=str(home.parent), CODEX_HOME=str(home), CODEX_USAGE_DATA_DIR=str(home))
    temporary = home.parent / 'temp'
    temporary.mkdir(mode=0o700, exist_ok=True)
    os.environ['TMPDIR'] = os.environ['TEMP'] = os.environ['TMP'] = str(temporary)
    tempfile.tempdir = str(temporary)
    sys.dont_write_bytecode = True
    sys.addaudithook(audit_guard(home.parent, report=args.mode == "report"))
    if args.mode == 'wal-cleanup':
        from wal_maintenance_benchmark import measure as measure_wal
        measure_wal(args)
        return
    from codex_usage.agent_capture import capture_once
    from codex_usage.agent_paths import ledger_database_path
    from codex_usage.agent_reports import render_ledger_report
    from codex_usage.allowance_probe import QuotaRead
    from codex_usage.ledger_queries import query_ledger_records
    from codex_usage.ledger_schema import increment_ledger_revision, open_ledger
    rows = []
    writer_samples = []
    quota_eviction_seconds = None

    @contextmanager
    def measured_writer(*values, **options):
        started = perf_counter()
        with open_ledger(*values, **options) as connection:
            entered = perf_counter()
            try:
                yield connection
            finally:
                writer_samples.append({"admission_seconds": entered-started,
                    "held_seconds": perf_counter()-entered,
                    "wal_bytes_before_reader_close": sum(p.stat().st_size
                        for p in Path(values[0]).parent.glob(Path(values[0]).name + "-wal"))})

    # The report's source remains unchanged; observe only its cache publisher.
    if args.mode == "report":
        import codex_usage.allowance_index as index
        index.open_ledger = measured_writer

    def timed(name, operation):
        writer_samples.clear()
        collections, gc_started, gc_elapsed = [0, 0, 0], {}, [0.0]
        def observe_gc(phase, info):
            generation = info["generation"]
            if phase == "start":
                gc_started[generation] = perf_counter()
            elif generation in gc_started:
                gc_elapsed[0] += perf_counter()-gc_started.pop(generation)
                collections[generation] += 1
        if args.trace_gc:
            gc.callbacks.append(observe_gc)
        profiler = cProfile.Profile() if args.profile else None
        wall, cpu = perf_counter(), process_time()
        if profiler:
            profiler.enable()
        try:
            result = operation()
        finally:
            if args.trace_gc:
                gc.callbacks.remove(observe_gc)
        if profiler:
            profiler.disable()
            profiler.dump_stats(str(home.parent / (name.replace(" ", "-")+".prof")))
        item = {"operation": name, "wall_seconds": perf_counter()-wall,
                "parent_cpu_seconds": process_time()-cpu}
        if writer_samples:
            item["allowance_writers"] = list(writer_samples)
        if args.trace_gc:
            item.update(gc_seconds=gc_elapsed[0], gc_collections=collections)
        if hasattr(result, "stats"):
            assert result.outcome == "success", result.error
            assert result.stats.pending_files == 0 and result.stats.file_errors == 0
            assert result.stats.worker_serial_fallbacks == 0
            assert result.stats.worker_infrastructure_errors == 0
            item["work"] = {key: getattr(result.stats, key) for key in (
                "files_parsed", "files_appended", "source_bytes_read", "pending_files", "pending_bytes")}
            with open_ledger(ledger_database_path(home), read_only=True) as connection:
                records = query_ledger_records(connection)
                item["records_sha256"] = digest([asdict(record) for record in records])
                item["events"] = len(records)
        else:
            if hasattr(result, "html"):
                item.update(cache_hit=result.cache_hit, html_sha256=hashlib.sha256(result.html.encode()).hexdigest(),
                            html_bytes=len(result.html.encode()))
                if args.allow_allowance_scope_difference:
                    normalized = allowance_scope_html(result.html, result.allowance_navigation)
                    item['allowance_scope_html_sha256'] = hashlib.sha256(normalized.encode()).hexdigest()
            else:
                item.update(csv_sha256=hashlib.sha256(result.csv.encode()).hexdigest(), csv_rows=result.row_count)
        if args.mode == "report":
            path = ledger_database_path(home)
            with open_ledger(path, read_only=True) as connection:
                item["derived_bytes"] = connection.execute("select coalesce(sum(length(html)),0) from rendered_reports").fetchone()[0]
                item["allowance_payload_bytes"] = connection.execute(
                    "select coalesce(sum(length(report_json)),0) from allowance_report_cache").fetchone()[0]
                if connection.execute("select 1 from sqlite_master where name='history_preparation_cache'").fetchone():
                    item["history_reuse_bytes"] = connection.execute(
                        "select coalesce(sum(length(cast(payload as blob))),0) from history_preparation_cache").fetchone()[0]
                    item["quota_journal_rows"] = connection.execute(
                        "select count(*) from dashboard_preparation_quota_changes").fetchone()[0]
            item["sqlite_bytes"] = sum(p.stat().st_size for p in path.parent.glob(path.name + "*"))
            try:
                import resource
                item["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
            except ImportError:
                item["peak_rss_bytes"] = None
        rows.append(item)
        return result

    if args.mode == "capture":
        from observed_speed_fixture import AT, TOKENS, append_rows, response, write_source
        project = home.parent / "synthetic-project"
        (project / ".git").mkdir(parents=True, exist_ok=True)
        (project / ".git/config").write_text('[remote "origin"]\nurl = https://example.invalid/synthetic.git\n')
        files = [write_source(home, task=f"benchmark-{i:02}", count=1000,
                  cwd=str(project), at=AT-timedelta(days=i % 2)) for i in range(12)]
        with patch("codex_usage.allowance_capture.probe_allowance",
                   return_value=QuotaRead("2026-10-16T00:00:00Z", diagnostics="benchmark_excluded")):
            timed("cold capture", lambda: capture_once(home, request_kind="benchmark", max_workers=args.workers, auto_transitions=False))
            no_op = timed("unchanged capture", lambda: capture_once(home, request_kind="benchmark", max_workers=args.workers, auto_transitions=False))
            assert no_op.stats.source_bytes_read == 0
            for i, path in enumerate(files):
                append_rows(path, response(1000, at=AT-timedelta(days=i % 2), response_id=f"append-{i}"))
            timed("tiny append", lambda: capture_once(home, request_kind="benchmark", max_workers=args.workers, auto_transitions=False))
            for i, path in enumerate(files):
                for j in range(1001, 1101):
                    append_rows(path, response(j, at=AT-timedelta(days=i % 2), response_id=f"append-{i}-{j}"))
            timed("larger append", lambda: capture_once(home, request_kind="benchmark", max_workers=args.workers, auto_transitions=False))
        with open_ledger(ledger_database_path(home), read_only=True) as connection:
            totals = connection.execute("select count(*),sum(total_tokens) from ledger_usage_events").fetchone()
            assert tuple(totals) == (13212, TOKENS.total_tokens*13212)
    else:
        with open_ledger(ledger_database_path(home)) as connection:
            increment_ledger_revision(connection)
            if args.account_mode == "empty":
                for table in ("allowance_report_cache", "allowance_event_costs", "allowance_window_cache"):
                    connection.execute(f"delete from {table}")
            connection.execute("delete from rendered_reports")
            connection.execute("delete from speed_html_cache")
            connection.commit()
        now = datetime.fromisoformat(args.now)
        def render(range_name="today", **kwargs):
            projects = kwargs.pop("project_keys", [])
            theme = kwargs.pop("theme", "night")
            return render_ledger_report(home, range_name=range_name,
                project_keys=projects, theme=theme, timezone_name="America/Toronto",
                now=now, **kwargs)
        sequence = (("first Today after revision", "today"), ("switch Yesterday", "yesterday"),
                    ("cached Today", "today")) if args.workload == "standard" else (
                    ("first Today after revision", "today"), ("first 30d", "30d"),
                    ("cached Today", "today"), ("cached 30d", "30d"))
        for name, range_name in sequence:
            timed(name, lambda r=range_name: render(r))
        if args.workload == "export-followup":
            from codex_usage.agent_reports import export_agent_activity_csv
            from zoneinfo import ZoneInfo
            if args.clear_quota_before_export:
                from codex_usage import allowance_prepared_cache
                started = perf_counter()
                allowance_prepared_cache.clear()
                quota_eviction_seconds = perf_counter() - started
            local_date = now.astimezone(ZoneInfo("America/Toronto")).date()
            for number in range(3):
                timed(f"30d CSV {number+1}", lambda: export_agent_activity_csv(home, range_name="custom",
                    start_date=(local_date-timedelta(days=29)).isoformat(), end_date=local_date.isoformat(),
                    project_keys=[], timezone_name="America/Toronto"))
        if args.workload in {"dashboard", "dashboard-extended", "dashboard-csv"}:
            from dataclasses import replace
            from benchmark_allowance_reuse import add_event
            from codex_usage.allowance_models import QuotaObservation
            from codex_usage.allowance_queries import allowance_status
            from codex_usage.allowance_store import store_read
            now += timedelta(minutes=1)
            wall = perf_counter()
            with open_ledger(ledger_database_path(home)) as connection:
                admitted = perf_counter()
                status = allowance_status(connection, now=now)
                anchors = [QuotaObservation(**{k: b[k] for k in QuotaObservation.__dataclass_fields__})
                           for b in status["active_buckets"]]
                assert anchors, "Snapshot needs a captured live anchor"
                add_event(connection, now)
                store_read(connection, QuotaRead(now.isoformat(), status["plan"], tuple(
                    replace(p, timestamp=now.isoformat(), used_percent=min(100, p.used_percent+1)) for p in anchors)), None)
                increment_ledger_revision(connection)
                connection.commit()
            rows.append({"operation": "append write", "wall_seconds": perf_counter()-wall,
                         "writer_admission_seconds": admitted-wall,
                         "writer_held_seconds": perf_counter()-admitted})
            appended = timed("Today after usage and quota append", render)
            timed("30d after usage and quota append", lambda: render("30d"))
            if args.workload == "dashboard-extended":
                timed("switch Yesterday", lambda: render("yesterday"))
                timed("switch 7d", lambda: render("7d"))
                timed("30d day theme", lambda: render("30d", theme="day"))
                with open_ledger(ledger_database_path(home), read_only=True) as connection:
                    project = connection.execute("""select p.project_key from ledger_projects p
                        join ledger_contexts c using(project_id) join ledger_usage_events e using(context_id)
                        group by p.project_id order by count(*) desc, p.project_key limit 1""").fetchone()[0]
                timed("30d one project", lambda: render("30d", project_keys=[project]))
                from codex_usage.agent_reports import export_agent_activity_csv
                from zoneinfo import ZoneInfo
                local_date = now.astimezone(ZoneInfo("America/Toronto")).date()
                timed("30d CSV", lambda: export_agent_activity_csv(home, range_name="custom",
                    start_date=(local_date-timedelta(days=29)).isoformat(), end_date=local_date.isoformat(),
                    project_keys=[], timezone_name="America/Toronto"))
                action = next((a for a in appended.allowance_navigation["actions"]
                               if a["state"]["kind"] == "periods"), None)
                if action:
                    timed("exact history", lambda: render(allowance_action=json.dumps(action)))
            if args.workload == "dashboard-csv":
                from codex_usage.agent_reports import export_agent_activity_csv
                from zoneinfo import ZoneInfo
                local_date = now.astimezone(ZoneInfo("America/Toronto")).date()
                timed("30d CSV", lambda: export_agent_activity_csv(home, range_name="custom",
                    start_date=(local_date-timedelta(days=29)).isoformat(), end_date=local_date.isoformat(),
                    project_keys=[], timezone_name="America/Toronto"))
    try:
        from codex_usage import allowance_prepared_cache
        retained_quota_points = len(allowance_prepared_cache._raw[0]) if allowance_prepared_cache._raw else 0
    except ImportError:
        retained_quota_points = 0
    print(json.dumps({"python": sys.version, "sqlite": sqlite3.sqlite_version,
        "quota_eviction_seconds": quota_eviction_seconds,
        "retained_quota_points": retained_quota_points,
        "dependencies": {d.metadata["Name"]: d.version for d in distributions()},
        "gil_enabled": sys._is_gil_enabled(), "free_threaded_build": sysconfig.get_config_var("Py_GIL_DISABLED"),
        "jit_enabled": bool(getattr(sys, "_jit", None) and sys._jit.is_enabled()), "results": rows}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("capture", "report", "wal-cleanup"), required=True)
    parser.add_argument('--wal-cleanup-enabled', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument("--baseline-source", type=Path)
    parser.add_argument("--candidate-source", type=Path)
    parser.add_argument("--baseline-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--candidate-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--ledger-snapshot", type=Path)
    parser.add_argument("--now", default=datetime.now(UTC).isoformat())
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--profile", action="store_true", help="diagnostic runs only, never adoption samples")
    parser.add_argument("--workload", choices=("standard", "dashboard", "dashboard-extended", "dashboard-csv", "export-followup"), default="standard")
    parser.add_argument("--account-mode", choices=("revision", "empty"), default="revision")
    parser.add_argument("--trace-gc", action="store_true", help="Diagnostic allocation/retention follow-up only")
    parser.add_argument("--clear-quota-before-export", action="store_true",
                        help="Diagnostic retained-object ablation; never adoption samples")
    parser.add_argument('--allow-allowance-scope-difference', action='store_true',
                        help='Validate issued history links; ignore only scope hashes changed by cache-format revisions')
    args = parser.parse_args()
    if args.measure:
        measure(args)
        return
    if args.mode == 'wal-cleanup':
        if not args.output or args.ledger_snapshot or args.profile or not 1 <= args.repeats <= 20:
            parser.error('WAL cleanup requires fresh --output and 1-20 --repeats, without private input/profile')
        from wal_maintenance_benchmark import run as run_wal
        run_wal(args)
        return
    if not args.output or not args.baseline_source or not args.candidate_source or not 1 <= args.repeats <= 20:
        parser.error("fresh --output, both --*-source paths and 1-20 --repeats required")
    if args.mode == "report" and not args.ledger_snapshot:
        parser.error("report mode requires an already frozen --ledger-snapshot")
    root = args.output.resolve()
    root.mkdir(mode=0o700)
    evidence = {"source_only": True, "private_input": args.mode == "report",
        "profiled": args.profile, "gc_observation": args.trace_gc, "workers": args.workers,
        "candidate_quota_eviction": args.clear_quota_before_export,
        "memory_and_child_cpu": "process high-water RSS measured for reports; child CPU not measured",
        "account_mode": args.account_mode,
        "quota_rpc_excluded": True, "fixed_clock": args.now, "mode": args.mode, "workload": args.workload,
        "allowance_scope_normalization": args.allow_allowance_scope_difference,
        "baseline_source": str(args.baseline_source.resolve()),
        "candidate_source": str(args.candidate_source.resolve()), "pairs": []}
    home = root / "home"
    authorities = (("baseline", args.baseline_source, args.baseline_python.absolute()),
                   ("candidate", args.candidate_source, args.candidate_python.absolute()))
    evidence["source_identities"] = {label: digest({path.relative_to(source).as_posix():
        hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(source.rglob("*.py"))})
        for label, source, _ in authorities}
    evidence["harness_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    from codex_usage.process_tree import run_process_tree
    # Pair zero is separately reported preparation, not an adoption sample.
    for repeat in range(args.repeats+1):
        pair = {}
        for label, source, python in authorities[::(-1 if repeat % 2 else 1)]:
            if home.exists():
                shutil.rmtree(home)
            if args.mode == "report":
                retained = sum(p.stat().st_size for p in args.ledger_snapshot.parent.rglob("*") if p.is_file())
                if retained + args.ledger_snapshot.stat().st_size > 6 * 1024**3:
                    raise ValueError("Retained evidence and working copy exceed the 6 GiB dashboard budget")
                target = home / ".codex-usage/usage-ledger.sqlite3"
                target.parent.mkdir(parents=True, mode=0o700)
                shutil.copyfile(args.ledger_snapshot, target)
                target.chmod(0o600)
            environment = {key: value for key, value in os.environ.items()
                if key in {"PATH", "LANG", "TMPDIR", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
            environment.update(PYTHONPATH=str(source.resolve()), HOME=str(root), USERPROFILE=str(root),
                CODEX_HOME=str(home), CODEX_USAGE_DATA_DIR=str(root), PYTHONNOUSERSITE="1")
            command = [str(python), str(Path(__file__).resolve()), "--measure", "--home", str(home),
                       "--mode", args.mode, "--now", args.now, "--workers", str(args.workers),
                       "--workload", args.workload, "--account-mode", args.account_mode]
            if args.profile:
                command.append("--profile")
            if args.trace_gc:
                command.append("--trace-gc")
            if args.clear_quota_before_export and label == "candidate":
                command.append("--clear-quota-before-export")
            if args.allow_allowance_scope_difference:
                command.append('--allow-allowance-scope-difference')
            try:
                result = run_process_tree(command, cwd=root, environment=environment, timeout_seconds=600)
            except (OSError, subprocess.SubprocessError) as error:
                (root / "failure.json").write_text(json.dumps({"pair": repeat, "configuration": label,
                    "error": repr(error)}, indent=2))
                raise
            if result.returncode:
                (root / "failure.json").write_text(json.dumps({"pair": repeat, "configuration": label,
                    "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}, indent=2))
                raise RuntimeError("benchmark failed; private failure.json retained")
            pair[label] = json.loads(result.stdout)
        try:
            for old, new in zip(pair["baseline"]["results"], pair["candidate"]["results"], strict=True):
                assert old["operation"] == new["operation"]
                html_key = 'allowance_scope_html_sha256' if args.allow_allowance_scope_difference else 'html_sha256'
                for key in ("records_sha256", html_key, "csv_sha256", "csv_rows", "work", "events", "cache_hit"):
                    if key in old:
                        assert old[key] == new[key], (old["operation"], key)
        except AssertionError:
            (root / 'failure.json').write_text(json.dumps(dict(pair=repeat, results=pair), indent=2))
            raise
        evidence["pairs"].append({"preparation": repeat == 0, **pair})
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2)+"\n")
        print(json.dumps({"pair": repeat, "results": {label: [(r["operation"], round(r["wall_seconds"], 4))
              for r in value["results"]] for label, value in pair.items()}}), flush=True)
    summaries = {}
    for index, row in enumerate(evidence["pairs"][0]["baseline"]["results"]):
        summaries[row["operation"]] = {label: statistics.median(pair[label]["results"][index]["wall_seconds"]
            for pair in evidence["pairs"][1:]) for label in ("baseline", "candidate")}
    evidence["medians"] = summaries
    (root / "evidence.json").write_text(json.dumps(evidence, indent=2)+"\n")
    print(json.dumps({"medians": summaries}), flush=True)
    shutil.rmtree(home)


if __name__ == "__main__":
    main()
