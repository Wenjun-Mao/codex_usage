from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="codex-usage-agent-smoke-") as raw:
        root = Path(raw)
        home = root / ".codex"
        sessions = home / "sessions" / "2026" / "09" / "02"
        sessions.mkdir(parents=True)
        task_id = "019f0000-0000-7000-8000-000000000001"
        session = sessions / f"rollout-2026-09-02T12-00-00-{task_id}.jsonl"
        session.write_text(_fixture_jsonl(task_id, root / "project"), encoding="utf-8")
        (root / "project").mkdir()
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
                    "transfer_folder": "",
                }
            ),
            encoding="utf-8",
        )
        process = subprocess.Popen(
            [str(args.executable), "--background", "--settings-file", str(settings)],
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
    return 0


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
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed loopback.
        decoded = json.loads(response.read())
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
