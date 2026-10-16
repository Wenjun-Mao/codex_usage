"""Paired source-backed capture/report measurements on owned disposable inputs."""
import argparse
import cProfile
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import statistics
import subprocess
import sys
import sysconfig
from time import perf_counter, process_time
from unittest.mock import patch

from collector_benchmark_guard import audit_guard


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def measure(args):
    home = args.home.resolve()
    os.environ.update(HOME=str(home.parent), CODEX_HOME=str(home), CODEX_USAGE_DATA_DIR=str(home))
    sys.addaudithook(audit_guard(home.parent, report=args.mode == "report"))
    from codex_usage.agent_capture import capture_once
    from codex_usage.agent_paths import ledger_database_path
    from codex_usage.agent_reports import render_ledger_report
    from codex_usage.allowance_probe import QuotaRead
    from codex_usage.ledger_queries import query_ledger_records
    from codex_usage.ledger_schema import increment_ledger_revision, open_ledger
    rows = []

    def timed(name, operation):
        profiler = cProfile.Profile() if args.profile else None
        wall, cpu = perf_counter(), process_time()
        if profiler:
            profiler.enable()
        result = operation()
        if profiler:
            profiler.disable()
            profiler.dump_stats(str(home.parent / (name.replace(" ", "-")+".prof")))
        item = {"operation": name, "wall_seconds": perf_counter()-wall,
                "parent_cpu_seconds": process_time()-cpu}
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
            item.update(cache_hit=result.cache_hit, html_sha256=hashlib.sha256(result.html.encode()).hexdigest(),
                        html_bytes=len(result.html.encode()))
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
            connection.execute("delete from rendered_reports")
            connection.execute("delete from speed_html_cache")
            connection.commit()
        for name, range_name in (("first Today after revision", "today"),
                                  ("switch Yesterday", "yesterday"), ("cached Today", "today")):
            timed(name, lambda r=range_name: render_ledger_report(home, range_name=r,
                project_keys=[], theme="night", timezone_name="America/Toronto",
                now=datetime.fromisoformat(args.now)))
    print(json.dumps({"python": sys.version, "sqlite": sqlite3.sqlite_version,
        "gil_enabled": sys._is_gil_enabled(), "free_threaded_build": sysconfig.get_config_var("Py_GIL_DISABLED"),
        "jit_enabled": bool(getattr(sys, "_jit", None) and sys._jit.is_enabled()), "results": rows}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("capture", "report"), required=True)
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
    args = parser.parse_args()
    if args.measure:
        measure(args)
        return
    if not args.output or not args.baseline_source or not args.candidate_source or not 1 <= args.repeats <= 20:
        parser.error("fresh --output, both --*-source paths and 1-20 --repeats required")
    if args.mode == "report" and not args.ledger_snapshot:
        parser.error("report mode requires an already frozen --ledger-snapshot")
    root = args.output.resolve()
    root.mkdir(mode=0o700)
    evidence = {"source_only": True, "private_input": args.mode == "report",
        "profiled": args.profile, "workers": args.workers,
        "memory_and_child_cpu": "not measured; optional adoption gates remain open",
        "quota_rpc_excluded": True, "fixed_clock": args.now, "mode": args.mode,
        "baseline_source": str(args.baseline_source.resolve()),
        "candidate_source": str(args.candidate_source.resolve()), "pairs": []}
    home = root / "home"
    authorities = (("baseline", args.baseline_source, args.baseline_python.absolute()),
                   ("candidate", args.candidate_source, args.candidate_python.absolute()))
    evidence["source_identities"] = {label: digest({path.relative_to(source).as_posix():
        hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(source.rglob("*.py"))})
        for label, source, _ in authorities}
    from codex_usage.process_tree import run_process_tree
    # Pair zero is separately reported preparation, not an adoption sample.
    for repeat in range(args.repeats+1):
        pair = {}
        for label, source, python in authorities[::(-1 if repeat % 2 else 1)]:
            if home.exists():
                shutil.rmtree(home)
            if args.mode == "report":
                target = home / ".codex-usage/usage-ledger.sqlite3"
                target.parent.mkdir(parents=True, mode=0o700)
                shutil.copyfile(args.ledger_snapshot, target)
                target.chmod(0o600)
            environment = {key: value for key, value in os.environ.items()
                if key in {"PATH", "LANG", "TMPDIR", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
            environment.update(PYTHONPATH=str(source.resolve()), HOME=str(root), USERPROFILE=str(root),
                CODEX_HOME=str(home), CODEX_USAGE_DATA_DIR=str(root), PYTHONNOUSERSITE="1")
            command = [str(python), str(Path(__file__).resolve()), "--measure", "--home", str(home),
                       "--mode", args.mode, "--now", args.now, "--workers", str(args.workers)]
            if args.profile:
                command.append("--profile")
            try:
                result = run_process_tree(command, cwd=root, environment=environment, timeout_seconds=180)
            except (OSError, subprocess.SubprocessError) as error:
                (root / "failure.json").write_text(json.dumps({"pair": repeat, "configuration": label,
                    "error": repr(error)}, indent=2))
                raise
            if result.returncode:
                (root / "failure.json").write_text(json.dumps({"pair": repeat, "configuration": label,
                    "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}, indent=2))
                raise RuntimeError("benchmark failed; private failure.json retained")
            pair[label] = json.loads(result.stdout)
        for old, new in zip(pair["baseline"]["results"], pair["candidate"]["results"], strict=True):
            assert old["operation"] == new["operation"]
            for key in ("records_sha256", "html_sha256", "work", "events", "cache_hit"):
                if key in old:
                    assert old[key] == new[key], (old["operation"], key)
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
