"""Compare date switches on copies of an explicit ledger, never a live report."""
import argparse
from contextlib import ExitStack
from datetime import datetime
from dataclasses import asdict
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
from time import perf_counter, process_time
from unittest.mock import patch


def measure(args):
    from codex_usage.agent_paths import ledger_database_path
    from codex_usage.agent_reports import PRICING_REVISION, render_ledger_report
    from codex_usage.allowance_index import indexed_allowance_report
    from codex_usage.allowance_queries import allowance_status
    from codex_usage.ledger_queries import query_ledger_status
    from codex_usage.ledger_schema import open_ledger
    import codex_usage.agent_reports as reports
    import codex_usage.breakdown_reports as breakdown
    path = ledger_database_path(args.home)
    # Hold the monetary index constant: measure navigation, not first-install
    # repricing. All writes are to a disposable copy of the supplied ledger.
    with open_ledger(path, read_only=True) as connection:
        status = query_ledger_status(connection)
        allowance = indexed_allowance_report(connection, path, revision=status.revision,
            pricing_revision=PRICING_REVISION, coverage_complete=status.coverage.complete)
        allowance["status"] = allowance_status(connection, now=datetime.fromisoformat(args.now))
        allowance_hash = hashlib.sha256(json.dumps(allowance, sort_keys=True).encode()).hexdigest()
    with open_ledger(path) as connection:
        connection.execute("delete from rendered_reports")
        connection.execute("delete from speed_html_cache")
        connection.commit()
    counts, timings, observations, economic, economics_by_range = {}, {}, [], {}, {}
    def track(module, name, label, stack, size=None):
        original = getattr(module, name)
        def run(*values, **kwargs):
            started = perf_counter()
            counts[label + "_calls"] = counts.get(label + "_calls", 0) + 1
            try:
                result = original(*values, **kwargs)
                if size:
                    counts[label + "_records"] = counts.get(label + "_records", 0) + size(result)
                if label == "economics":
                    economic["sha256"] = hashlib.sha256(json.dumps(asdict(result), sort_keys=True).encode()).hexdigest()
                return result
            finally:
                timings[label] = timings.get(label, 0) + perf_counter() - started
        stack.enter_context(patch.object(module, name, run))
    with ExitStack() as stack:
        track(reports, "materialize_ledger", "selected", stack, lambda r: len(r.valued))
        track(breakdown, "query_ledger_records", "breakdown_query", stack, len)
        track(breakdown, "prepare_evidence", "account_history", stack)
        track(breakdown, "aggregate", "composition", stack)
        track(reports, "build_project_economics", "economics", stack)
        for range_name in ("today", "yesterday", "7d", "today", "yesterday"):
            counts.clear()
            timings.clear()
            started = perf_counter()
            cpu_started = process_time()
            report = render_ledger_report(args.home, range_name=range_name, project_keys=[],
                theme="night", timezone_name="America/Toronto", now=datetime.fromisoformat(args.now))
            elapsed = perf_counter() - started
            cpu_elapsed = process_time() - cpu_started
            if counts.get("economics_calls"):
                economics_by_range[range_name] = economic["sha256"]
            with open_ledger(path, read_only=True) as connection:
                # Pick the scope actually issued by this range, including cache hits.
                for candidate in connection.execute("select cache_key,html from rendered_reports where cache_key like 'breakdown:%:metadata'"):
                    prefix = candidate[0][:-len("metadata")]
                    if connection.execute("select 1 from rendered_reports where cache_key=?",
                        (prefix + "nav:" + report.breakdown_navigation["scope"],)).fetchone():
                        summary = breakdown.load(connection, prefix + "selected:summary")
                        directory = breakdown.load(connection, prefix + "metadata")["ranges"]
                        break
                else:
                    raise AssertionError("Missing prepared selected-range summary")
            first = report.html.index('<style>\n    .usage-breakdown')
            last = report.html.index('<section class="section observed-speed"')
            base = report.html[:first] + report.html[last:]
            observations.append({"range": range_name, "seconds": elapsed, "cpu_seconds": cpu_elapsed,
                "cache_hit": report.cache_hit, "html_bytes": len(report.html.encode()),
                "work": dict(counts), "inclusive_seconds": dict(timings),
                "selected_summary_sha256": hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest(),
                "account_evidence_sha256": allowance_hash,
                "economics_sha256": economics_by_range[range_name],
                "base_html_sha256": hashlib.sha256(base.encode()).hexdigest()})
        origin = render_ledger_report(args.home, range_name="today", project_keys=[],
            theme="night", timezone_name="America/Toronto", now=datetime.fromisoformat(args.now))
        actions = [a for a in origin.breakdown_navigation["actions"] if a["state"]["detail"].startswith("evidence:")]
        def span(index):
            interval = directory[actions[index]["state"]["detail"][9:]]
            return interval["end"] - interval["start"]
        inspections = sorted({0, len(actions)//2, len(actions)-1,
            max(range(len(actions)), key=span)}) if actions else []
        for index in inspections:
            for attempt in ("cold", "warm"):
                counts.clear()
                timings.clear()
                started = perf_counter()
                cpu_started = process_time()
                inspected = render_ledger_report(args.home, range_name="today", project_keys=[],
                    theme="night", timezone_name="America/Toronto", now=datetime.fromisoformat(args.now),
                    breakdown_action=json.dumps(actions[index]))
                elapsed = perf_counter() - started
                cpu_elapsed = process_time() - cpu_started
                with open_ledger(path, read_only=True) as connection:
                    for candidate in connection.execute("select cache_key,html from rendered_reports where cache_key like 'breakdown:%:metadata'"):
                        prefix = candidate[0][:-len("metadata")]
                        metadata = json.loads(candidate[1])
                        if connection.execute("select 1 from rendered_reports where cache_key=?",
                            (prefix + "nav:" + inspected.breakdown_navigation["scope"],)).fetchone():
                            basis = actions[index]["state"]["detail"][len("evidence:"):]
                            summary = breakdown.load(connection, metadata.get("history_prefix", prefix) + basis + ":summary")
                            break
                    else:
                        raise AssertionError("Missing inspected interval")
                first = inspected.html.index('<style>\n    .usage-breakdown')
                last = inspected.html.index('<section class="section observed-speed"')
                base = inspected.html[:first] + inspected.html[last:]
                observations.append({"range": f"interval:{index}:{attempt}", "seconds": elapsed, "cpu_seconds": cpu_elapsed,
                    "work": dict(counts), "inclusive_seconds": dict(timings),
                    "_summary": summary,
                    "selected_summary_sha256": hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest(),
                    "base_html_sha256": hashlib.sha256(base.encode()).hexdigest()})
    print(json.dumps(observations))


def first_difference(expected, actual, path="summary"):
    if isinstance(expected, dict) and isinstance(actual, dict):
        if expected.keys() != actual.keys():
            return f"{path}: different fields {expected.keys() ^ actual.keys()}"
        for key in expected:
            difference = first_difference(expected[key], actual[key], path + "." + key)
            if difference:
                return difference
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return f"{path}: different lengths {len(expected)} / {len(actual)}"
        for index, (old, new) in enumerate(zip(expected, actual, strict=True)):
            difference = first_difference(old, new, f"{path}[{index}]")
            if difference:
                return difference
    elif expected != actual:
        return f"{path}: {expected!r} / {actual!r}"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--now", required=True)
    parser.add_argument("--release", default="v2.12.0")
    parser.add_argument("--presentation-changes", action="store_true",
        help="Permit intentional HTML formatting changes; still require exact selected/historical/account data parity")
    parser.add_argument("--output", type=Path, default=Path("output/performance/range-navigation.json"))
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--home", type=Path)
    args = parser.parse_args()
    if args.measure:
        measure(args)
        return
    if args.ledger is None:
        parser.error("--ledger is required; only a read-only SQLite backup touches this input")
    repo = Path(__file__).resolve().parents[1]
    release = subprocess.check_output(["git", "rev-parse", args.release], cwd=repo, text=True).strip()
    evidence = {"release": release, "fixed_clock": args.now, "private_input": True,
        "input_access": "SQLite mode=ro backup only; reports and caches use temporary copies",
        "cache_protocol": "prime monetary index; clear presentation caches; Today/Yesterday/7d/Today/Yesterday; first/middle/last/longest intervals cold and warm",
        "inclusive_timings": True, "results": {}}
    with TemporaryDirectory(prefix="range-navigation-") as directory:
        root = Path(directory)
        snapshot = root / "snapshot.sqlite3"
        with sqlite3.connect(args.ledger.resolve().as_uri()+"?mode=ro", uri=True) as source, sqlite3.connect(snapshot) as target:
            source.backup(target)
        snapshot.chmod(0o600)
        baseline = root / "release"
        baseline.mkdir()
        archive = subprocess.check_output(["git", "archive", release, "src"], cwd=repo)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(baseline, filter="data")
        for name, authority in (("release", baseline), ("candidate", repo)):
            home = root / name / "home"
            target = home / ".codex-usage/usage-ledger.sqlite3"
            target.parent.mkdir(parents=True, mode=0o700)
            with sqlite3.connect(snapshot) as source, sqlite3.connect(target) as destination:
                source.backup(destination)
            target.chmod(0o600)
            command = [sys.executable, str(Path(__file__).resolve()), "--measure", "--home", str(home), "--now", args.now]
            environment = dict(os.environ, PYTHONPATH=str(authority / "src"), HOME=str(root / "isolated-home"), CODEX_HOME=str(home))
            evidence["results"][name] = json.loads(subprocess.check_output(command, env=environment, cwd=root, text=True))
            print(name, [(r["range"], round(r["seconds"], 3)) for r in evidence["results"][name]], flush=True)
        differences = {}
        for old, new in zip(evidence["results"]["release"], evidence["results"]["candidate"], strict=True):
            difference = first_difference(old.pop("_summary", None), new.pop("_summary", None))
            if difference:
                differences[old["range"]] = difference
        evidence["interval_differences"] = differences
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n")
        for old, new in zip(evidence["results"]["release"], evidence["results"]["candidate"], strict=True):
            if not args.presentation_changes:
                assert old["base_html_sha256"] == new["base_html_sha256"], old["range"]
            if "account_evidence_sha256" in old:
                assert old["account_evidence_sha256"] == new["account_evidence_sha256"], old["range"]
                assert old["economics_sha256"] == new["economics_sha256"], old["range"]
            assert old["selected_summary_sha256"] == new["selected_summary_sha256"], (old["range"], differences.get(old["range"]))
        evidence["exact_selected_historical_and_account_parity"] = True
        evidence["base_html_equal"] = all(old["base_html_sha256"] == new["base_html_sha256"]
            for old, new in zip(evidence["results"]["release"], evidence["results"]["candidate"], strict=True))
        evidence["intentional_presentation_changes"] = args.presentation_changes
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
