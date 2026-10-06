"""Synthetic-only local timings. Never opens the user's selected Codex home."""
import argparse
from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

from codex_usage.agent_api import AgentHttpServer
from codex_usage.agent_capture import capture_once
from codex_usage.agent_reports import render_ledger_report
from codex_usage.companion_service import CompanionService

ROOT = Path(__file__).resolve().parents[3]


def timed(function):
    start = perf_counter()
    value = function()
    return value, 1000 * (perf_counter() - start)


def write_fixture(home, count):
    sessions = home / "sessions"
    sessions.mkdir()
    for task in range(4):
        rows = []
        for index in range(count):
            stamp = (datetime(2026, 10, 5, tzinfo=UTC) + timedelta(seconds=index * 60)).isoformat()
            if index == 0:
                rows.append({"timestamp": stamp, "type": "session_meta",
                             "payload": {"id": f"task-{task}", "cwd": f"/synthetic/project-{task}"}})
            rows.append({"timestamp": stamp, "type": "turn_context", "payload": {
                "model": "gpt-6-sol", "turn_id": f"turn-{index}",
            }})
            total = 1000 * (index + 1)
            rows.append({"timestamp": stamp, "type": "event_msg", "payload": {
                "type": "token_count", "info": {"total_token_usage": {
                    "input_tokens": total - 10 * (index + 1), "cached_input_tokens": 500 * (index + 1),
                    "output_tokens": 10 * (index + 1), "total_tokens": total,
                }},
            }})
        (sessions / f"task-{task}.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events-per-task", type=int, default=1000)
    args = parser.parse_args()
    if not 1 <= args.events_per_task <= 10000:
        parser.error("events per task must be between 1 and 10000")
    spec = importlib.util.spec_from_file_location("private_benchmark_client", ROOT / "extensions/openai/companion/client.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with TemporaryDirectory(prefix="codex-usage-companion-benchmark-") as directory:
        home = Path(directory)
        write_fixture(home, args.events_per_task)
        with patch("codex_usage.agent_capture.capture_quota_read", lambda *a: None):
            capture, capture_ms = timed(lambda: capture_once(home, request_kind="manual", max_workers=1))
        assert capture.outcome == "success"
        settings = SimpleNamespace(timezone="America/Toronto", auto_project_transitions=True)
        now = datetime(2026, 10, 20, tzinfo=UTC)
        service = CompanionService(home, lambda: settings, now=lambda: now)
        request = {"kind": "summary", "scope": {"period": "30d"}}
        summary, cold_ms = timed(lambda: service.query(request))
        warm_ms = [timed(lambda: service.query(request))[1] for _ in range(7)]
        report_args = dict(range_name="30d", project_keys=[], theme="day",
                           timezone_name=settings.timezone, now=now)
        html, html_cold_ms = timed(lambda: render_ledger_report(home, **report_args))
        html_warm_ms = [timed(lambda: render_ledger_report(home, **report_args))[1] for _ in range(7)]
        server = AgentHttpServer(SimpleNamespace(companion_query=service.query), token="test-only" * 8)
        descriptor = home / ".codex-usage/agent.json"
        descriptor.write_text(json.dumps({"api_version": 1, "process_owner": "transient",
            "port": server.port, "token": "test-only" * 8, "started_at": now.isoformat(), "codex_home": str(home)}))
        descriptor.chmod(0o600)
        server.start()
        try:
            client = module.CollectorClient(home=home, enabled=True)
            reply, handshake_ms = timed(lambda: client.query(request))
            assert reply["state"] == "ok" and reply["result"] == summary
            http_ms = [timed(lambda: client.query(request))[1] for _ in range(7)]
        finally:
            server.stop()
        assert summary["data"]["language"]["usage"]["total_tokens"] == args.events_per_task * 4 * 1000
        print(json.dumps({
            "source": "disposable synthetic captured ledger", "events": args.events_per_task * 4,
            "capture_ms": capture_ms, "structured_cold_ms": cold_ms,
            "structured_warm_median_ms": median(warm_ms), "adapter_handshake_plus_warm_query_ms": handshake_ms,
            "adapter_loopback_warm_median_ms": median(http_ms), "html_cold_ms": html_cold_ms,
            "html_warm_median_ms": median(html_warm_ms),
            "summary_bytes": len(json.dumps(summary, separators=(",", ":")).encode()),
            "html_bytes": len(html.html.encode()),
            "limitations": ["Different payloads: not a before/after comparison", "Synthetic corpus only",
                "No quota/image history in this fixture", "No real host/tunnel transport or UI latency",
                "No Windows host or platform package acceptance"],
        }, indent=2))


if __name__ == "__main__":
    main()
