"""Real collector HTTP/worker acceptance on disposable synthetic data.

Run only on disposable CI or inside an external sandbox that blocks account
discovery and outbound networking. Source oracle and collector share fixtures.
"""
import argparse
from datetime import timedelta
from dataclasses import asdict
import importlib.util
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from codex_usage.agent_paths import ledger_database_path
from codex_usage.ledger_queries import query_ledger_records
from codex_usage.ledger_schema import open_ledger
from codex_usage.ledger_sync import synchronize_parser_workset
from collector_smoke_owner import run_driver
from codex_usage.session_cache import refresh_cached_session_data
from observed_speed_fixture import AT, TOKENS, append_rows, response, write_source
from packaged_parallel_cache_smoke import _require_actual_parallel_audit


def run_acceptance(executable):
    environment = dict(os.environ)
    scripts = Path(__file__).resolve().parent
    environment["PYTHONPATH"] = os.pathsep.join((str(scripts.parent / "src"), str(scripts)))
    result = run_driver([sys.executable, str(Path(__file__).resolve()),
        "--executable", str(executable), "--driver"], environment=environment,
        cwd=scripts.parent, timeout_seconds=120)
    if result.returncode:
        raise RuntimeError(f"packaged collector worker acceptance failed:\n{result.stdout}\n{result.stderr}")
    evidence = json.loads(result.stdout)
    if evidence.get("contract") != "collector-parallel-http-v1" or not evidence.get("oracle_equal"):
        raise RuntimeError("missing packaged collector worker proof")
    with Path(executable).open("rb") as stream:
        evidence["collector_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    with tempfile.TemporaryDirectory(prefix="collector-cleanup-") as raw:
        root = Path(raw).resolve()
        state = root / "state.json"
        evidence["cleanup"] = run_driver([sys.executable, str(Path(__file__).resolve()),
            "--executable", str(executable), "--driver", "--stall-after-cold",
            "--scratch", str(root), "--state-path", str(state)],
            environment=environment, cwd=scripts.parent, stop_after_state=state)
    return evidence


def _client():
    path = Path(__file__).with_name("smoke-test-packaged-agent.py")
    spec = importlib.util.spec_from_file_location("agent_smoke_client", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _audit(path, run_id):
    payload = json.loads(path.read_text())
    if payload["version"] != 1 or payload["capture_run_id"] != run_id:
        raise RuntimeError("capture audit is stale or unsupported")
    return payload


def _assert_stats(result):
    assert result["outcome"] == "success", result
    stats = result["stats"]
    assert stats["worker_serial_fallbacks"] == 0, stats
    assert stats["worker_infrastructure_errors"] == 0, stats
    assert stats["file_errors"] == 0 and stats["pending_files"] == 0, stats


def _records(path):
    with open_ledger(path, read_only=True) as connection:
        return query_ledger_records(connection)


def driver(executable, *, stall_after_cold=False, scratch=None, state_path=None):
    if os.name == "posix":
        assert os.getpgrp() == os.getpid(), "driver requires its outer owned process group"
    client = _client()
    with tempfile.TemporaryDirectory(prefix="collector-parallel-", dir=scratch) as raw:
        root = Path(raw).resolve()
        home = root / "home"
        project = root / "project"
        (project / ".git").mkdir(parents=True)
        (project / ".git/config").write_text('[remote "origin"]\n url = https://example.invalid/synthetic.git\n')
        files = [write_source(home, task=f"packaged-{i:02}", count=1000,
            cwd=str(project), at=AT-timedelta(days=i % 2)) for i in range(12)]
        settings = root / "settings.json"
        settings.write_text(json.dumps({"schema_version": 1, "codex_home": str(home),
            "capture_interval_minutes": None, "background_capture": False,
            "daily_update_checks": False, "onboarding_complete": True,
            "timezone": "UTC", "theme": "night", "auto_project_transitions": False,
            "transfer_folder": ""}))
        audit_path = root / "worker-audit.json"
        environment = dict(os.environ, HOME=str(root), USERPROFILE=str(root),
            CODEX_HOME=str(home), CODEX_USAGE_DATA_DIR=str(root))
        descriptor = None
        with (root / "stdout.log").open("w") as stdout, (root / "stderr.log").open("w") as stderr:
            process = subprocess.Popen(
                [str(executable), "--background", "--settings-file", str(settings),
                 "--capture-audit", str(audit_path)], env=environment,
                cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
            try:
                descriptor = client._wait_for_descriptor(home / ".codex-usage/agent.json")
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    status = client._request(descriptor, "GET", "/v1/status")
                    if not status["capture_running"] and status["last_capture_outcome"] == "success":
                        break
                    if process.poll() is not None:
                        raise RuntimeError("collector exited before startup capture")
                    time.sleep(.05)
                else:
                    raise TimeoutError("startup capture did not complete")
                db = ledger_database_path(home)
                with open_ledger(db, read_only=True) as connection:
                    row = connection.execute("select run_id,outcome,stats_json from capture_runs where request_kind='startup' order by run_id desc limit 1").fetchone()
                    run_id = row["run_id"]
                    startup_stats = json.loads(row["stats_json"])
                    _assert_stats({"outcome": row["outcome"], "stats": startup_stats})
                    cold_count = connection.execute("select count(*) from ledger_usage_events").fetchone()[0]
                    parsed_bytes = connection.execute("select sum(byte_offset) from parser_checkpoints").fetchone()[0]
                assert status["coverage"]["complete"] and cold_count == 12000
                assert startup_stats["files_parsed"] == 12 and startup_stats["pending_bytes"] == 0
                corpus_bytes = sum(path.stat().st_size for path in files)
                assert parsed_bytes == corpus_bytes and startup_stats["source_bytes_read"] >= parsed_bytes
                cold = _audit(audit_path, run_id)
                assert cold["parent_pid"] == descriptor["pid"]
                _require_actual_parallel_audit(cold["usage_run"], parent_pid=cold["parent_pid"], label="collector startup")
                assert cold["usage_run"]["span_count"] == 12
                cold["completed_events"] = cold_count
                cold["coverage_complete"] = True
                cold["pending_files"] = startup_stats["pending_files"]
                cold["pending_bytes"] = startup_stats["pending_bytes"]
                cold["source_bytes_read"] = startup_stats["source_bytes_read"]
                cold["corpus_bytes"] = corpus_bytes
                cold["parsed_bytes"] = parsed_bytes
                if stall_after_cold:
                    assert state_path is not None
                    state_path.write_text(json.dumps({"pid": descriptor["pid"]}))
                    while True:
                        time.sleep(1)

                def full_oracle(stage):
                    # A fresh full parse is independent of bounded incremental
                    # discovery, which may legitimately leave work pending.
                    oracle = root / f"oracle-{stage}.sqlite3"
                    with open_ledger(oracle):
                        pass
                    outcome = refresh_cached_session_data([home / "sessions"], cache_database_path=oracle,
                        max_workers=1, auto_transitions=False, refresh_storage_metadata=False)
                    with open_ledger(oracle, read_only=True) as diagnostic:
                        errors = [row[0] for row in diagnostic.execute("select error from files where error is not null")]
                    assert not outcome.stats.file_errors and not outcome.stats.pending_files, (asdict(outcome.stats), errors)
                    synchronize_parser_workset(oracle)
                    return _records(oracle)
                assert _records(db) == full_oracle("cold"), "cold frozen capture differs from serial oracle"
                cold["oracle_equal"] = True

                unchanged = client._request(descriptor, "POST", "/v1/capture", {})
                _assert_stats(unchanged)
                assert unchanged["stats"]["source_bytes_read"] == 0
                assert _audit(audit_path, unchanged["run_id"])["usage_run"]["span_count"] == 0
                for i, path in enumerate(files):
                    append_rows(path, response(1000, at=AT-timedelta(days=i % 2), response_id=f"appended-{i}"))
                changed = client._request(descriptor, "POST", "/v1/capture", {})
                _assert_stats(changed)
                assert changed["stats"]["files_appended"] == 12
                assert _audit(audit_path, changed["run_id"])["usage_run"]["span_count"] == 12
                with open_ledger(db, read_only=True) as connection:
                    totals = tuple(connection.execute("select count(*),sum(input_tokens),sum(cached_input_tokens),sum(output_tokens),sum(total_tokens) from ledger_usage_events").fetchone())
                assert totals == (12012, TOKENS.input_tokens*12012, TOKENS.cached_input_tokens*12012,
                                  TOKENS.output_tokens*12012, TOKENS.total_tokens*12012)
                actual, expected = _records(db), full_oracle("appended")
                if actual != expected:
                    first = next(((asdict(a), asdict(b)) for a, b in zip(actual, expected) if a != b), None)
                    raise AssertionError(f"incremental frozen capture differs from serial oracle: counts={len(actual)}/{len(expected)}, first={first}")
                report = client._request(descriptor, "GET", "/v1/report?range=all&theme=night")
                assert "Codex Usage Report" in report["html"]
                assert client._request(descriptor, "GET", "/v1/report?range=all&theme=night")["cache_hit"]
            finally:
                try:
                    if process.poll() is None:
                        if descriptor is not None:
                            client._request(descriptor, "POST", "/v1/shutdown", {})
                        else:
                            process.terminate()
                    output, errors = process.communicate(timeout=10)
                    stdout.write(output)
                    stderr.write(errors)
                except BaseException:
                    process.kill()
                    process.communicate(timeout=2)
                    raise
            if process.returncode:
                raise RuntimeError(f"collector exited {process.returncode}: {errors}")
        assert not (home / ".codex-usage/agent.json").exists()
        if os.name == "posix":
            for pid in cold["usage_run"]["worker_pids"]:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    continue
                raise RuntimeError("parser worker remained after shutdown")
        return {"contract": "collector-parallel-http-v1", "oracle_equal": True,
                "cold": cold, "unchanged_source_bytes": 0, "append_events": 12}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--driver", action="store_true")
    parser.add_argument("--stall-after-cold", action="store_true")
    parser.add_argument("--scratch", type=Path)
    parser.add_argument("--state-path", type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve()
    print(json.dumps(driver(executable, stall_after_cold=args.stall_after_cold,
        scratch=args.scratch, state_path=args.state_path) if args.driver else run_acceptance(executable)))


if __name__ == "__main__":
    main()
