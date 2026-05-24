import json
import subprocess
import sys
from pathlib import Path

from codex_usage.cli import _normalize_thread_ids


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
    assert payload["pricing_method"] == "effective_dated"
    assert payload["total"]["usage"]["total_tokens"] == 120
    assert "cost" in payload["total"]
    assert "credits" in payload["total"]
    assert payload["rows"][0]["label"] == "demo"
    assert "credits" in payload["rows"][0]

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
    assert "codex_credits" in csv_result.stdout
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
            "--theme",
            "night",
            "--output",
            str(report_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report_html = report_path.read_text(encoding="utf-8")
    assert "Codex Usage Report" in report_html
    assert 'data-codex-theme="night"' in report_html


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


def test_cli_report_rejects_unknown_theme(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_usage.cli",
            "report",
            "--range",
            "all",
            "--theme",
            "midnight",
            "--output",
            str(tmp_path / "report.html"),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_cli_threads_and_sync_commands(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    sync_dir = tmp_path / "sync"
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True)
    _write_session(day / "thread-1.jsonl", "thread-1", "/repo/first", 100)
    (codex_home / "session_index.jsonl").write_text(
        json.dumps({"id": "thread-1", "thread_name": "First thread", "updated_at": "2026-04-29T10:05:00Z"}) + "\n",
        encoding="utf-8",
    )

    threads_result = _run_cli(
        [
            "threads",
            "--sessions-dir",
            str(sessions),
            "--project-key",
            "/repo/first",
            "--json",
        ]
    )
    threads_payload = json.loads(threads_result.stdout)
    assert [thread["thread_id"] for thread in threads_payload["threads"]] == ["thread-1"]
    assert threads_payload["threads"][0]["title"] == "First thread"

    export_result = _run_cli(
        [
            "sync",
            "export",
            "--sessions-dir",
            str(sessions),
            "--sync-dir",
            str(sync_dir),
            "--thread-id",
            "thread-1",
        ]
    )
    assert json.loads(export_result.stdout)["exported"] == ["thread-1"]

    status_result = _run_cli(
        [
            "sync",
            "status",
            "--sessions-dir",
            str(sessions),
            "--sync-dir",
            str(sync_dir),
            "--thread-id",
            "thread-1",
            "--json",
        ]
    )
    assert json.loads(status_result.stdout)["threads"][0]["state"] == "synced"

    imported_sessions = tmp_path / "imported" / "sessions"
    import_result = _run_cli(
        [
            "sync",
            "import",
            "--sessions-dir",
            str(imported_sessions),
            "--sync-dir",
            str(sync_dir),
            "--thread-id",
            "thread-1",
        ]
    )
    assert json.loads(import_result.stdout)["imported"] == ["thread-1"]
    assert (tmp_path / "imported" / "session_index.jsonl").is_file()


def test_normalize_thread_ids_preserves_case_and_slashes() -> None:
    thread_ids = _normalize_thread_ids([" Owner/Repo ", "Owner/Repo", "owner/repo", "thread-1"])

    assert thread_ids == ["Owner/Repo", "owner/repo", "thread-1"]


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codex_usage.cli", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _write_session(path: Path, session_id: str, cwd: str, total: int) -> None:
    _write_jsonl(
        path,
        [
            {
                "timestamp": "2026-04-29T10:00:00Z",
                "type": "session_meta",
                "payload": {"id": session_id, "timestamp": "2026-04-29T10:00:00Z", "cwd": cwd},
            },
            _turn_context_event("2026-04-29T10:00:01Z", f"turn-{session_id}"),
            _token_count_event("2026-04-29T10:00:02Z", total),
        ],
    )


def _write_jsonl(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")


def _turn_context_event(timestamp: str, turn_id: str) -> dict[str, object]:
    return {"timestamp": timestamp, "type": "turn_context", "payload": {"turn_id": turn_id, "model": "gpt-5.5"}}


def _token_count_event(timestamp: str, total: int) -> dict[str, object]:
    usage = dict(
        input_tokens=total,
        cached_input_tokens=0,
        output_tokens=0,
        reasoning_output_tokens=0,
        total_tokens=total,
    )
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": "token_count", "info": {"total_token_usage": usage}},
    }
