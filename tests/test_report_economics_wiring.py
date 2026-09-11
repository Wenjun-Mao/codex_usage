from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from codex_usage.agent_capture import capture_once
from codex_usage.agent_reports import render_ledger_report


def test_cli_and_ledger_reports_receive_precomputed_project_economics(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / ".codex"
    _write_session(codex_home)
    cli_report = tmp_path / "cli-report.html"
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_usage",
            "report",
            "--range",
            "all",
            "--output",
            str(cli_report),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    assert _has_project_economics(cli_report.read_text(encoding="utf-8"))

    assert capture_once(
        codex_home,
        request_kind="manual",
        max_workers=1,
    ).outcome == "success"
    ledger_report = render_ledger_report(
        codex_home,
        range_name="all",
        project_keys=[],
        theme="night",
        timezone_name="UTC",
    )
    assert _has_project_economics(ledger_report.html)


def _has_project_economics(report_html: str) -> bool:
    return all(
        marker in report_html
        for marker in (
            'data-report-section="project-economics"',
            "Weighted all-project benchmark",
            "wiring-fixture",
            "gpt-5.5",
        )
    )


def _write_session(codex_home: Path) -> None:
    session_path = (
        codex_home
        / "sessions"
        / "2026"
        / "09"
        / "10"
        / "wiring-fixture.jsonl"
    )
    session_path.parent.mkdir(parents=True)
    session_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-09-10T10:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "wiring-fixture",
                            "timestamp": "2026-09-10T10:00:00Z",
                            "cwd": "/repo/wiring-fixture",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-09-10T10:00:01Z",
                        "type": "turn_context",
                        "payload": {
                            "turn_id": "turn-1",
                            "model": "gpt-5.5",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-09-10T10:00:02Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": 100,
                                    "cached_input_tokens": 25,
                                    "cache_write_input_tokens": 10,
                                    "output_tokens": 20,
                                    "total_tokens": 120,
                                }
                            },
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
