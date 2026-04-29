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
