import json
import os
import subprocess
import sys
from pathlib import Path


def test_cli_summary_and_report_apply_auto_project_transitions(tmp_path: Path) -> None:
    codex_home, source_key, target_key = _write_transition_fixture(tmp_path)

    summary_result = _run_cli(["summary", "--range", "all", "--by", "project", "--json"], codex_home=codex_home)

    payload = json.loads(summary_result.stdout)
    rows_by_key = {row["key"]: row for row in payload["rows"]}
    assert rows_by_key[source_key]["usage"]["total_tokens"] == 100
    assert rows_by_key[target_key]["usage"]["total_tokens"] == 200
    assert payload["project_transitions"][0]["source_key"] == source_key
    assert payload["project_transitions"][0]["target_key"] == target_key

    report_path = tmp_path / "transition-report.html"
    _run_cli(["report", "--range", "all", "--output", str(report_path)], codex_home=codex_home)
    report_html = report_path.read_text(encoding="utf-8")
    assert "signoz-stack" in report_html
    assert "ops-board" in report_html


def test_cli_summary_can_disable_auto_project_transitions(tmp_path: Path) -> None:
    codex_home, source_key, target_key = _write_transition_fixture(tmp_path)

    result = _run_cli(
        ["summary", "--range", "all", "--by", "project", "--no-auto-transitions", "--json"],
        codex_home=codex_home,
    )

    payload = json.loads(result.stdout)
    assert payload["project_transitions"] == []
    assert [row["key"] for row in payload["rows"]] == [source_key]
    assert payload["rows"][0]["usage"]["total_tokens"] == 300
    assert target_key not in {row["key"] for row in payload["rows"]}


def test_cli_project_filter_matches_transition_target(tmp_path: Path) -> None:
    codex_home, _, target_key = _write_transition_fixture(tmp_path)

    result = _run_cli(
        ["summary", "--range", "all", "--by", "project", "--project-key", target_key, "--json"],
        codex_home=codex_home,
    )

    payload = json.loads(result.stdout)
    assert payload["project_keys"] == [target_key]
    assert [row["key"] for row in payload["rows"]] == [target_key]
    assert payload["total"]["usage"]["total_tokens"] == 200


def test_cli_summary_transition_metadata_follows_project_filter(tmp_path: Path) -> None:
    codex_home, _, target_key = _write_transition_fixture(tmp_path, include_second=True)
    other_target_key = "https://github.com/example/billing-console"

    result = _run_cli(
        ["summary", "--range", "all", "--by", "project", "--project-key", target_key, "--json"],
        codex_home=codex_home,
    )

    payload = json.loads(result.stdout)
    assert [transition["target_key"] for transition in payload["project_transitions"]] == [target_key]
    assert other_target_key not in json.dumps(payload["project_transitions"])


def test_cli_transitions_suggest_json(tmp_path: Path) -> None:
    codex_home, source_key, target_key = _write_transition_fixture(tmp_path)
    sessions = codex_home / "sessions"

    result = _run_cli(["transitions", "suggest", "--json"], codex_home=codex_home)

    payload = json.loads(result.stdout)
    assert payload["sessions_dirs"] == [str(sessions)]
    assert payload["files_scanned"] == 1
    assert payload["observations_count"] == 1
    assert [transition["source_key"] for transition in payload["project_transitions"]] == [source_key]
    assert [transition["target_key"] for transition in payload["project_transitions"]] == [target_key]


def test_cli_transitions_without_subcommand_shows_transitions_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "codex_usage.cli", "transitions"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert "suggest" in result.stderr
    assert "{summary,report,threads,transitions,sync}" not in result.stderr


def _run_cli(args: list[str], *, codex_home: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("CODEX_USAGE_SESSIONS_DIR", None)
    env.pop("CODEX_USAGE_PROJECT_ALIASES", None)
    if codex_home is not None:
        env["CODEX_HOME"] = str(codex_home)
    return subprocess.run(
        [sys.executable, "-m", "codex_usage.cli", *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _write_transition_fixture(tmp_path: Path, *, include_second: bool = False) -> tuple[Path, str, str]:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    day = sessions / "2026" / "05" / "23"
    day.mkdir(parents=True)

    signoz_repo = tmp_path / "signoz-stack"
    ops_repo = tmp_path / "ops-board"
    _write_git_config(signoz_repo, "https://github.com/example/signoz-stack.git")
    _write_git_config(ops_repo, "https://github.com/example/ops-board.git")

    source_key = "https://github.com/example/signoz-stack"
    target_key = "https://github.com/example/ops-board"
    _write_transition_session(day / "thread-1.jsonl", "thread-1", signoz_repo, ops_repo)
    if include_second:
        inventory_repo = tmp_path / "inventory-api"
        billing_repo = tmp_path / "billing-console"
        _write_git_config(inventory_repo, "https://github.com/example/inventory-api.git")
        _write_git_config(billing_repo, "https://github.com/example/billing-console.git")
        _write_transition_session(
            day / "thread-2.jsonl",
            "thread-2",
            inventory_repo,
            billing_repo,
            source_url="https://github.com/example/inventory-api.git",
        )
    return codex_home, source_key, target_key


def _write_transition_session(
    path: Path,
    session_id: str,
    source_repo: Path,
    target_repo: Path,
    *,
    source_url: str = "https://github.com/example/signoz-stack.git",
) -> None:
    _write_jsonl(
        path,
        [
            {
                "timestamp": "2026-05-23T21:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "timestamp": "2026-05-23T21:00:00Z",
                    "cwd": str(source_repo),
                    "git": {"repository_url": source_url},
                },
            },
            _turn_context_event("2026-05-23T21:00:01Z", "turn-1"),
            _token_count_event("2026-05-23T21:00:02Z", 100),
            {
                "timestamp": "2026-05-23T21:05:00Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "arguments": json.dumps({"workdir": str(target_repo), "command": "Get-Location"}),
                },
            },
            _turn_context_event("2026-05-23T21:10:01Z", "turn-2"),
            _token_count_event("2026-05-23T21:10:02Z", 300),
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


def _write_git_config(repo: Path, url: str) -> None:
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(f'[remote "origin"]\n\turl = {url}\n', encoding="utf-8")
