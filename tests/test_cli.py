import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import codex_usage.cli as cli_module
import pytest


def test_cli_summary_json_csv_and_report(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
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
                                    "cache_write_input_tokens": 10,
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

    env = {"CODEX_HOME": str(codex_home)}

    json_result = _run_cli(["summary", "--range", "all", "--by", "project", "--json"], env=env)
    payload = json.loads(json_result.stdout)
    assert payload["pricing_method"] == "effective_dated"
    assert payload["total"]["usage"]["total_tokens"] == 120
    assert payload["total"]["usage"]["cache_write_input_tokens"] == 10
    assert payload["total"]["usage"]["ordinary_input_tokens"] == 65
    assert "cost" in payload["total"]
    assert "credits" in payload["total"]
    assert payload["rows"][0]["label"] == "demo"
    assert "credits" in payload["rows"][0]

    csv_result = _run_cli(["summary", "--range", "all", "--by", "day", "--csv"], env=env)
    csv_rows = list(csv.DictReader(io.StringIO(csv_result.stdout)))
    assert csv_rows[0]["label"] == "2026-04-29"
    assert csv_rows[0]["total_tokens"] == "120"
    assert csv_rows[0]["cache_write_input_tokens"] == "10"
    assert csv_rows[0]["ordinary_input_tokens"] == "65"

    terminal_result = _run_cli(["summary", "--range", "all", "--by", "day"], env=env)
    assert "Cache Read" in terminal_result.stdout
    assert "Cache Write" in terminal_result.stdout
    day_row = next(line for line in terminal_result.stdout.splitlines() if line.startswith("2026-04-29"))
    assert day_row.split()[:6] == ["2026-04-29", "120", "100", "25", "10", "20"]

    report_path = tmp_path / "report.html"
    _run_cli(
        [
            "report",
            "--range",
            "all",
            "--theme",
            "night",
            "--output",
            str(report_path),
        ],
        env=env,
    )
    report_html = report_path.read_text(encoding="utf-8")
    assert "Codex Usage Report" in report_html
    assert 'data-codex-theme="night"' in report_html


def test_cli_project_key_filters_summary_and_report(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True)
    _write_session(day / "first.jsonl", "session-1", "/repo/first", 100)
    _write_session(day / "second.jsonl", "session-2", "/repo/second", 75)
    env = {"CODEX_HOME": str(codex_home)}

    all_result = _run_cli(
        [
            "summary",
            "--range",
            "all",
            "--by",
            "project",
            "--json",
        ],
        env=env,
    )
    all_payload = json.loads(all_result.stdout)
    assert all_payload["project_keys"] == []
    assert all_payload["total"]["usage"]["total_tokens"] == 175

    single_result = _run_cli(
        [
            "summary",
            "--range",
            "all",
            "--by",
            "project",
            "--project-key",
            "/repo/first",
            "--json",
        ],
        env=env,
    )
    single_payload = json.loads(single_result.stdout)
    assert single_payload["project_keys"] == ["/repo/first"]
    assert single_payload["total"]["usage"]["total_tokens"] == 100
    assert [row["key"] for row in single_payload["rows"]] == ["/repo/first"]

    multi_result = _run_cli(
        [
            "summary",
            "--range",
            "all",
            "--by",
            "project",
            "--project-key",
            "/repo/first",
            "--project-key",
            "/repo/second",
            "--json",
        ],
        env=env,
    )
    multi_payload = json.loads(multi_result.stdout)
    assert multi_payload["project_keys"] == ["/repo/first", "/repo/second"]
    assert multi_payload["total"]["usage"]["total_tokens"] == 175

    unmatched_result = _run_cli(
        [
            "summary",
            "--range",
            "all",
            "--by",
            "project",
            "--project-key",
            "/repo/missing",
            "--json",
        ],
        env=env,
    )
    unmatched_payload = json.loads(unmatched_result.stdout)
    assert unmatched_payload["total"]["usage"]["total_tokens"] == 0
    assert unmatched_payload["rows"] == []

    report_path = tmp_path / "filtered.html"
    _run_cli(
        [
            "report",
            "--range",
            "all",
            "--project-key",
            "/repo/missing",
            "--output",
            str(report_path),
        ],
        env=env,
    )
    report_html = report_path.read_text(encoding="utf-8")
    assert "Projects: /repo/missing" in report_html
    assert "No Codex usage was found for this report range." in report_html


def test_cli_uses_internal_cache_dir_env_var(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    cache_dir = tmp_path / "extension-cache"
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True)
    _write_session(day / "thread-1.jsonl", "thread-1", "/repo/first", 100)

    result = _run_cli(
        ["summary", "--range", "all", "--by", "project", "--json"],
        env={"CODEX_HOME": str(codex_home), "CODEX_USAGE_CACHE_DIR": str(cache_dir)},
    )

    payload = json.loads(result.stdout)
    assert payload["total"]["usage"]["total_tokens"] == 100
    assert (cache_dir / "usage-cache.sqlite3").is_file()


def test_cli_cache_reuses_records_after_first_scan(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    cache_dir = tmp_path / "cache"
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True)
    _write_session(day / "thread-1.jsonl", "thread-1", "/repo/first", 100)
    env = {"CODEX_HOME": str(codex_home), "CODEX_USAGE_CACHE_DIR": str(cache_dir)}

    first = _run_cli(["summary", "--range", "all", "--by", "project", "--json"], env=env)
    second = _run_cli(["summary", "--range", "all", "--by", "project", "--json"], env=env)

    assert json.loads(first.stdout)["total"]["usage"] == json.loads(second.stdout)["total"]["usage"]


def test_storage_snapshot_reports_active_and_archived_roots(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    day = sessions / "2026" / "04" / "29"
    archived_day = archived / "2026" / "04" / "29"
    day.mkdir(parents=True)
    archived_day.mkdir(parents=True)
    _write_session(day / "active-thread.jsonl", "active-thread", "/repo/active", 10)
    _write_session(archived_day / "archived-thread.jsonl", "archived-thread", "/repo/archived", 20)

    result = _run_cli(["storage", "snapshot", "--json"], env={"CODEX_HOME": str(codex_home)})

    payload = json.loads(result.stdout)
    roots = {Path(row["path"]).name: row for row in payload["roots"]}
    assert roots["sessions"]["jsonl_count"] == 1
    assert roots["archived_sessions"]["jsonl_count"] == 1


def test_summary_json_reports_archived_and_retained_missing_counts(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    archived = codex_home / "archived_sessions"
    active_day = sessions / "2026" / "04" / "29"
    archived_day = archived / "2026" / "04" / "29"
    active_day.mkdir(parents=True)
    archived_day.mkdir(parents=True)
    active_path = _write_session(active_day / "active-thread.jsonl", "active-thread", "/repo/active", 10)
    _write_session(archived_day / "archived-thread.jsonl", "archived-thread", "/repo/archived", 20)
    env = {"CODEX_HOME": str(codex_home)}

    first_result = _run_cli(["summary", "--range", "all", "--by", "project", "--json"], env=env)
    first_payload = json.loads(first_result.stdout)
    assert first_payload["files_archived"] == 1
    assert first_payload["files_retained_missing"] == 0

    active_path.unlink()
    second_result = _run_cli(["summary", "--range", "all", "--by", "project", "--json"], env=env)

    payload = json.loads(second_result.stdout)
    assert payload["files_archived"] == 1
    assert payload["files_retained_missing"] == 1
    assert payload["storage_roots"] == [str(sessions), str(archived)]
    assert payload["total"]["usage"]["total_tokens"] == 30


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


def test_cli_help_no_longer_exposes_removed_manual_options() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "codex_usage.cli", "summary", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--sessions-dir" not in result.stdout
    assert "--subscription-usd" not in result.stdout
    assert "--project-key" in result.stdout


def test_cli_threads_lists_selected_project(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
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
            "--project-key",
            "/repo/first",
            "--json",
        ],
        env={"CODEX_HOME": str(codex_home)},
    )
    threads_payload = json.loads(threads_result.stdout)
    assert [thread["thread_id"] for thread in threads_payload["threads"]] == ["thread-1"]
    assert threads_payload["threads"][0]["title"] == "First thread"
    assert "estimated_sync_bytes" in threads_payload["threads"][0]


def test_main_returns_two_for_unexpected_handler_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = SimpleNamespace(
        parse_args=lambda argv: SimpleNamespace(
            handler=lambda args: (_ for _ in ()).throw(RuntimeError("unexpected"))
        )
    )
    monkeypatch.setattr(cli_module, "build_parser", lambda: parser)

    assert cli_module.main([]) == 2
    assert capsys.readouterr().err.strip() == "codex-usage: unexpected"


def _run_cli(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.pop("CODEX_USAGE_SESSIONS_DIR", None)
    merged_env.pop("CODEX_USAGE_SUBSCRIPTION_USD", None)
    merged_env.pop("CODEX_USAGE_PROJECT_ALIASES", None)
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "codex_usage.cli", *args],
        check=True,
        capture_output=True,
        text=True,
        env=merged_env,
    )


def _write_session(path: Path, session_id: str, cwd: str, total: int) -> Path:
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
    return path


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
