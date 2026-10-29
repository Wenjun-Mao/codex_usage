from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import sqlite3

from observed_speed_fixture import legacy_speed_home
from codex_usage.ledger_writer_contract import LEDGER_SCHEMA_VERSION
from collector_smoke_environment import smoke_environment, verify_synthetic_probe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--parallel-evidence", type=Path)
    parser.add_argument("--wal-evidence", type=Path)
    args = parser.parse_args()
    from packaged_agent_parallel_smoke import run_acceptance
    parallel = run_acceptance(args.executable)
    if args.parallel_evidence is not None:
        from codex_usage.parallel_audit import atomic_write
        atomic_write(args.parallel_evidence, json.dumps(parallel, indent=2)+"\n")
    print(json.dumps(parallel), flush=True)
    from packaged_wal_smoke import run_acceptance as wal_acceptance
    wal = wal_acceptance(args.executable)
    if args.wal_evidence is not None:
        from codex_usage.parallel_audit import atomic_write
        atomic_write(args.wal_evidence, json.dumps(wal, indent=2)+"\n")
    print(json.dumps(wal), flush=True)
    with tempfile.TemporaryDirectory(prefix="codex-usage-agent-smoke-") as raw:
        root = Path(raw)
        home = root / ".codex"
        sessions = home / "sessions" / "2026" / "09" / "02"
        sessions.mkdir(parents=True)
        task_id = "019f0000-0000-7000-8000-000000000001"
        session = sessions / f"rollout-2026-09-02T12-00-00-{task_id}.jsonl"
        session.write_text(_fixture_jsonl(task_id, root / "project"), encoding="utf-8")
        (root / "project").mkdir()
        speed_db, speed_baseline = legacy_speed_home(home)
        transfer = root / "legacy-transfer"
        preserved = _preservation_fixtures(home, transfer, session, task_id)
        settings = root / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "codex_home": str(home),
                    "capture_interval_minutes": None,
                    "background_capture": False,
                    "daily_update_checks": False,
                    "onboarding_complete": True,
                    "timezone": "UTC",
                    "theme": "night",
                    "auto_project_transitions": True,
                    "transfer_folder": str(transfer),
                }
            ),
            encoding="utf-8",
        )
        process = subprocess.Popen(
            [str(args.executable), "--background", "--settings-file", str(settings)],
            env=smoke_environment(root, home), cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        descriptor: dict[str, object] | None = None
        try:
            descriptor = _wait_for_descriptor(home / ".codex-usage" / "agent.json")
            health = _request(descriptor, "GET", "/v1/health")
            if not health.get("ok"):
                raise RuntimeError(f"unhealthy packaged agent: {health}")
            _verify_retired_transfer_routes(descriptor)
            capture = _request(descriptor, "POST", "/v1/capture", {})
            if capture.get("outcome") != "success":
                raise RuntimeError(f"packaged capture failed: {capture}")
            unchanged = _request(descriptor, "POST", "/v1/capture", {})
            if unchanged.get("outcome") != "success":
                raise RuntimeError(f"unchanged packaged capture failed: {unchanged}")
            stats = unchanged.get("stats")
            if not isinstance(stats, dict) or stats.get(
                "source_bytes_read"
            ) != 0:
                raise RuntimeError(
                    "unchanged packaged capture reopened source content: "
                    f"{unchanged}"
                )
            report = _request(descriptor, "GET", "/v1/report?range=all&theme=night")
            if "Codex Usage Report" not in str(report.get("html", "")):
                raise RuntimeError("packaged ledger report was not rendered")
            _verify_packaged_speed(descriptor, speed_db, speed_baseline, report)
            _request(descriptor, "GET", "/v1/storage/snapshot")
            _request(descriptor, "GET", "/v1/agent-activity?range=all")
            changed = _request(descriptor, "POST", "/v1/settings", {
                "theme": "day", "transfer_folder": str(root / "replacement")})
            assert changed["theme"] == "day" and changed["transfer_folder"] == str(transfer)
            assert json.loads(settings.read_text())["transfer_folder"] == str(transfer)
        finally:
            if process.poll() is None:
                try:
                    if descriptor is not None:
                        _request(descriptor, "POST", "/v1/shutdown", {})
                    else:
                        process.terminate()
                except (OSError, RuntimeError):
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        if process.returncode not in {0, None}:
            stderr = process.stderr.read() if process.stderr else ""
            raise RuntimeError(f"packaged agent exited with {process.returncode}: {stderr}")
        changed_files = [path.name for path, digest in preserved.items()
                         if hashlib.sha256(path.read_bytes()).hexdigest() != digest]
        assert not changed_files, changed_files
        print(json.dumps({"retired_transfer_routes": "rejected", "preserved_files": len(preserved),
                          **verify_synthetic_probe(root)}))
    return 0


def _preservation_fixtures(home, transfer, session, task_id):
    transfer.mkdir()
    export = transfer / "export.jsonl"
    export.write_bytes(session.read_bytes())
    normalized = os.path.normcase(str(transfer.resolve(strict=False))).replace("\\", "/")
    fingerprint = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    state = home / ".codex-sync-state" / fingerprint / "threads" / f"{task_id}.json"
    state.parent.mkdir(parents=True)
    digest = hashlib.sha256(session.read_bytes()).hexdigest()
    state.write_text(json.dumps({"sync_version": 2, "thread_id": task_id,
        "sync_dir_fingerprint": fingerprint, "base_sha256": digest,
        "base_size_bytes": session.stat().st_size, "base_updated_at": "2026-09-02T12:00:02Z",
        "last_remote_sha256": digest, "last_local_sha256": digest,
        "source_relative_path": session.relative_to(home / "sessions").as_posix(),
        "project_key": "synthetic", "project_label": "Synthetic",
        "synced_at": "2026-09-02T12:00:02Z"}))
    global_state = home / ".codex-global-state.json"
    global_state.write_text('{"local-projects":{}}')
    index = home / "session_index.jsonl"
    index.write_text('{"id":"preserved","thread_name":"Synthetic task"}\n')
    database = home / "state_5.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT)")
        connection.execute("INSERT INTO sentinel VALUES ('preserve')")
        connection.commit()
    return {path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (session, export, state, global_state, index, database)}


def _verify_retired_transfer_routes(descriptor):
    for path in ("/v1/transfer/inventory", "/v1/transfer/execute"):
        for method in ("GET", "POST"):
            request = Request(f"http://127.0.0.1:{descriptor['port']}{path}", method=method,
                data=b"{}" if method == "POST" else None,
                headers={"Authorization": f"Bearer {descriptor['token']}",
                         "Content-Type": "application/json"})
            try:
                with urlopen(request, timeout=30):  # noqa: S310 - fixed loopback.
                    pass
            except HTTPError as error:
                if error.code == 404 and json.loads(error.read()) == {"error": "not found"}:
                    continue
            raise RuntimeError("packaged collector did not reject a retired transfer route")


def _verify_packaged_speed(descriptor, db, baseline, report):
    status = _request(descriptor, "GET", "/v1/status")
    assert "observed-output-speed-v1" in status["capabilities"]
    assert status["speed"]["pending"] == 0
    assert "Observed Output Speed" in report["html"] and "300.0" in report["html"]
    warm = _request(descriptor, "GET", "/v1/report?range=all&theme=night")
    assert warm["cache_hit"]
    hourly = _request(descriptor, "GET", "/v1/report?range=all&theme=night&speed_granularity=hourly")
    assert hourly["speed_navigation"]["granularity"] == "hourly"
    with closing(sqlite3.connect(db)) as connection:
        assert connection.execute("select count(*), sum(total_tokens), sum(output_tokens) from ledger_usage_events").fetchone() == baseline
        assert connection.execute("select count(*) from ledger_speed_facts where reason='' ").fetchone()[0] == 20
        schema = connection.execute("select value from ledger_meta where key='schema_version'").fetchone()[0]
        assert schema == str(LEDGER_SCHEMA_VERSION), (schema, LEDGER_SCHEMA_VERSION)
    assert list(db.parent.glob("*.schema-5-backup-*"))


def _wait_for_descriptor(path: Path) -> dict[str, object]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("port"):
                return payload
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.1)
    raise RuntimeError("packaged agent did not publish its descriptor")


def _request(
    descriptor: dict[str, object],
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    body = None if payload is None else json.dumps(payload).encode()
    request = Request(
        f"http://127.0.0.1:{descriptor['port']}{path}",
        method=method,
        data=body,
        headers={
            "Authorization": f"Bearer {descriptor['token']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed loopback.
            decoded = json.loads(response.read())
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"packaged agent request {method} {path} failed with "
            f"HTTP {error.code}: {detail}"
        ) from error
    if not isinstance(decoded, dict):
        raise RuntimeError("packaged agent response was not an object")
    return decoded


def _fixture_jsonl(task_id: str, cwd: Path) -> str:
    rows = [
        {
            "timestamp": "2026-09-02T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": task_id, "cwd": str(cwd), "model": "gpt-5.6-sol"},
        },
        {
            "timestamp": "2026-09-02T12:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 50,
                        "output_tokens": 20,
                        "reasoning_output_tokens": 5,
                        "total_tokens": 120,
                    }
                },
            },
        },
    ]
    return "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)


if __name__ == "__main__":
    raise SystemExit(main())
