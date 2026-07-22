import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import codex_usage.session_cache as cache_module
from codex_usage.models import UsageRecord
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data


_TRANSITIONS_DIRTY_KEY = "project_transitions_dirty"


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


def test_transition_recomputed_after_disabled_version_rebuild(tmp_path: Path) -> None:
    codex_home, source_key, target_key = _write_transition_fixture(tmp_path)
    sessions = codex_home / "sessions"
    cache_dir = tmp_path / "cache"
    established = load_cached_session_data([sessions], cache_dir=cache_dir)
    assert _usage_by_project(established.records) == {source_key: 100, target_key: 200}
    assert len(established.project_transitions) == 1

    db_path = cache_dir / CACHE_DB_NAME
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            update schema_meta set value = 'old'
            where key in ('parser_version', 'project_transition_version')
            """
        )

    disabled = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    assert disabled.stats.rebuilt is True
    assert disabled.project_transitions == []
    assert _usage_by_project(disabled.records) == {source_key: 300}
    assert _transition_dirty_value(db_path) == "1"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("select count(*) from project_transitions").fetchone() == (0,)

    recovered = load_cached_session_data([sessions], cache_dir=cache_dir)

    assert recovered.stats.files_parsed == 0
    assert recovered.stats.files_reused == 1
    assert len(recovered.project_transitions) == 1
    assert _usage_by_project(recovered.records) == {source_key: 100, target_key: 200}
    assert _transition_dirty_value(db_path) == "0"


def test_transition_recomputed_after_file_change_while_disabled(tmp_path: Path) -> None:
    codex_home, source_key, initial_target_key = _write_transition_fixture(tmp_path)
    sessions = codex_home / "sessions"
    cache_dir = tmp_path / "cache"
    established = load_cached_session_data([sessions], cache_dir=cache_dir)
    assert _usage_by_project(established.records) == {source_key: 100, initial_target_key: 200}

    replacement_repo = tmp_path / "billing-console"
    replacement_target_key = "https://github.com/example/billing-console"
    _write_git_config(replacement_repo, f"{replacement_target_key}.git")
    session_path = sessions / "2026" / "05" / "23" / "thread-1.jsonl"
    _write_transition_session(session_path, "thread-1", tmp_path / "signoz-stack", replacement_repo)

    disabled = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    assert disabled.stats.files_parsed == 1
    assert disabled.project_transitions == []
    assert _transition_dirty_value(cache_dir / CACHE_DB_NAME) == "1"

    recovered = load_cached_session_data([sessions], cache_dir=cache_dir)

    assert recovered.stats.files_parsed == 0
    assert recovered.stats.files_reused == 1
    assert [transition.target_key for transition in recovered.project_transitions] == [replacement_target_key]
    assert _usage_by_project(recovered.records) == {source_key: 100, replacement_target_key: 200}


def test_missing_transition_dirty_marker_is_conservatively_recomputed(tmp_path: Path) -> None:
    codex_home, source_key, target_key = _write_transition_fixture(tmp_path)
    sessions = codex_home / "sessions"
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir)
    db_path = cache_dir / CACHE_DB_NAME
    with sqlite3.connect(db_path) as connection:
        connection.execute("delete from schema_meta where key = ?", (_TRANSITIONS_DIRTY_KEY,))
        connection.execute("delete from project_transitions")

    recovered = load_cached_session_data([sessions], cache_dir=cache_dir)

    assert recovered.stats.rebuilt is False
    assert recovered.stats.files_reused == 1
    assert len(recovered.project_transitions) == 1
    assert _usage_by_project(recovered.records) == {source_key: 100, target_key: 200}
    assert _transition_dirty_value(db_path) == "0"


def test_version_match_tolerates_transition_dirty_metadata(tmp_path: Path) -> None:
    codex_home, _, _ = _write_transition_fixture(tmp_path)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([codex_home / "sessions"], cache_dir=cache_dir)

    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "insert or replace into schema_meta (key, value) values (?, '0')",
            (_TRANSITIONS_DIRTY_KEY,),
        )
        assert cache_module._schema_matches(connection) is True


def test_failed_transition_inference_leaves_dirty_for_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home, source_key, target_key = _write_transition_fixture(tmp_path)
    sessions = codex_home / "sessions"
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    db_path = cache_dir / CACHE_DB_NAME

    original_infer = cache_module.infer_project_transitions

    def fail_inference(*_args, **_kwargs):
        raise RuntimeError("transition inference interrupted")

    monkeypatch.setattr(cache_module, "infer_project_transitions", fail_inference)
    with pytest.raises(RuntimeError, match="transition inference interrupted"):
        load_cached_session_data([sessions], cache_dir=cache_dir)
    assert _transition_dirty_value(db_path) == "1"

    monkeypatch.setattr(cache_module, "infer_project_transitions", original_infer)
    recovered = load_cached_session_data([sessions], cache_dir=cache_dir)

    assert recovered.stats.files_reused == 1
    assert _usage_by_project(recovered.records) == {source_key: 100, target_key: 200}
    assert _transition_dirty_value(db_path) == "0"


def test_failed_transition_replacement_rolls_back_and_leaves_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home, _, initial_target_key = _write_transition_fixture(tmp_path)
    sessions = codex_home / "sessions"
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir)

    replacement_repo = tmp_path / "billing-console"
    replacement_target_key = "https://github.com/example/billing-console"
    _write_git_config(replacement_repo, f"{replacement_target_key}.git")
    session_path = sessions / "2026" / "05" / "23" / "thread-1.jsonl"
    _write_transition_session(session_path, "thread-1", tmp_path / "signoz-stack", replacement_repo)
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    original_set_dirty = cache_module._set_project_transitions_dirty

    def interrupt_clean(connection: sqlite3.Connection, *, dirty: bool) -> None:
        if not dirty:
            raise RuntimeError("transition replacement interrupted")
        original_set_dirty(connection, dirty=dirty)

    monkeypatch.setattr(cache_module, "_set_project_transitions_dirty", interrupt_clean)
    with pytest.raises(RuntimeError, match="transition replacement interrupted"):
        load_cached_session_data([sessions], cache_dir=cache_dir)

    db_path = cache_dir / CACHE_DB_NAME
    assert _transition_dirty_value(db_path) == "1"
    with sqlite3.connect(db_path) as connection:
        targets = connection.execute("select target_key from project_transitions").fetchall()
    assert targets == [(initial_target_key,)]

    monkeypatch.setattr(cache_module, "_set_project_transitions_dirty", original_set_dirty)
    recovered = load_cached_session_data([sessions], cache_dir=cache_dir)

    assert [transition.target_key for transition in recovered.project_transitions] == [replacement_target_key]
    assert _transition_dirty_value(db_path) == "0"


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


def _usage_by_project(records: list[UsageRecord]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for record in records:
        totals[record.project_key] = totals.get(record.project_key, 0) + record.usage.total_tokens
    return totals


def _transition_dirty_value(db_path: Path) -> str | None:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "select value from schema_meta where key = ?", (_TRANSITIONS_DIRTY_KEY,)
        ).fetchone()
    return None if row is None else str(row[0])


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
