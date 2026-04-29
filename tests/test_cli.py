import json
import subprocess
import sys
from pathlib import Path


def test_cli_summary_json_csv_and_report(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True)
    (day / "session.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-04-29T10:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "session-1",
                            "timestamp": "2026-04-29T10:00:00Z",
                            "cwd": "/repo/demo",
                            "git": {"repository_url": "https://github.com/example/demo.git"},
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-04-29T10:00:01Z",
                        "type": "turn_context",
                        "payload": {"turn_id": "turn-1", "model": "gpt-5.5"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-04-29T10:00:02Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": 100,
                                    "cached_input_tokens": 25,
                                    "output_tokens": 20,
                                    "reasoning_output_tokens": 5,
                                    "total_tokens": 120,
                                }
                            },
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    json_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_usage.cli",
            "summary",
            "--sessions-dir",
            str(sessions),
            "--range",
            "all",
            "--by",
            "project",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(json_result.stdout)
    assert payload["total"]["usage"]["total_tokens"] == 120
    assert payload["rows"][0]["label"] == "demo"

    csv_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_usage.cli",
            "summary",
            "--sessions-dir",
            str(sessions),
            "--range",
            "all",
            "--by",
            "day",
            "--csv",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "total_tokens" in csv_result.stdout
    assert "120" in csv_result.stdout

    report_path = tmp_path / "report.html"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_usage.cli",
            "report",
            "--sessions-dir",
            str(sessions),
            "--range",
            "all",
            "--output",
            str(report_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Codex Usage Report" in report_path.read_text(encoding="utf-8")


def test_cli_project_key_filters_summary_and_report(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True)
    _write_session(day / "first.jsonl", "session-1", "/repo/first", 100)
    _write_session(day / "second.jsonl", "session-2", "/repo/second", 75)

    all_result = _run_cli(
        [
            "summary",
            "--sessions-dir",
            str(sessions),
            "--range",
            "all",
            "--by",
            "project",
            "--json",
        ]
    )
    all_payload = json.loads(all_result.stdout)
    assert all_payload["project_keys"] == []
    assert all_payload["total"]["usage"]["total_tokens"] == 175

    single_result = _run_cli(
        [
            "summary",
            "--sessions-dir",
            str(sessions),
            "--range",
            "all",
            "--by",
            "project",
            "--project-key",
            "/repo/first",
            "--json",
        ]
    )
    single_payload = json.loads(single_result.stdout)
    assert single_payload["project_keys"] == ["/repo/first"]
    assert single_payload["total"]["usage"]["total_tokens"] == 100
    assert [row["key"] for row in single_payload["rows"]] == ["/repo/first"]

    multi_result = _run_cli(
        [
            "summary",
            "--sessions-dir",
            str(sessions),
            "--range",
            "all",
            "--by",
            "project",
            "--project-key",
            "/repo/first",
            "--project-key",
            "/repo/second",
            "--json",
        ]
    )
    multi_payload = json.loads(multi_result.stdout)
    assert multi_payload["project_keys"] == ["/repo/first", "/repo/second"]
    assert multi_payload["total"]["usage"]["total_tokens"] == 175

    unmatched_result = _run_cli(
        [
            "summary",
            "--sessions-dir",
            str(sessions),
            "--range",
            "all",
            "--by",
            "project",
            "--project-key",
            "/repo/missing",
            "--json",
        ]
    )
    unmatched_payload = json.loads(unmatched_result.stdout)
    assert unmatched_payload["total"]["usage"]["total_tokens"] == 0
    assert unmatched_payload["rows"] == []

    report_path = tmp_path / "filtered.html"
    _run_cli(
        [
            "report",
            "--sessions-dir",
            str(sessions),
            "--range",
            "all",
            "--project-key",
            "/repo/missing",
            "--output",
            str(report_path),
        ]
    )
    report_html = report_path.read_text(encoding="utf-8")
    assert "Projects: /repo/missing" in report_html
    assert "No Codex usage was found for this report range." in report_html


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codex_usage.cli", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _write_session(path: Path, session_id: str, cwd: str, total: int) -> None:
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-04-29T10:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": session_id,
                            "timestamp": "2026-04-29T10:00:00Z",
                            "cwd": cwd,
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-04-29T10:00:01Z",
                        "type": "turn_context",
                        "payload": {"turn_id": f"turn-{session_id}", "model": "gpt-5.5"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-04-29T10:00:02Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": total,
                                    "cached_input_tokens": 0,
                                    "output_tokens": 0,
                                    "reasoning_output_tokens": 0,
                                    "total_tokens": total,
                                }
                            },
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
