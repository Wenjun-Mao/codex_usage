import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import codex_usage.project_transition_evidence as project_transition_evidence
from codex_usage.project_transitions import collect_repo_path_observations


def test_collect_repo_path_observations_reads_function_call_workdir(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    repo = tmp_path / "ops-board"
    _write_git_config(repo, "https://github.com/Wenjun-Mao/ops-board.git")
    session_path = sessions / "2026" / "05" / "23" / "thread-1.jsonl"
    _write_jsonl(
        session_path,
        [
            "{malformed json",
            {
                "timestamp": "2026-05-23T21:00:00Z",
                "type": "session_meta",
                "payload": {"id": "thread-1", "cwd": "D:\\old\\signoz-stack"},
            },
            _function_call_workdir_event("2026-05-23T21:06:45Z", repo),
        ],
    )

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[session_path])

    assert len(observations) == 1
    assert observations[0].thread_id == "thread-1"
    assert observations[0].project_key == "https://github.com/wenjun-mao/ops-board"
    assert observations[0].timestamp == datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC)
    assert observations[0].source == "jsonl:response_item:function_call_workdir"


def test_collect_repo_path_observations_ignores_user_message_paths(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    repo = tmp_path / "ops-board"
    _write_git_config(repo, "https://github.com/Wenjun-Mao/ops-board.git")
    session_path = sessions / "2026" / "05" / "23" / "thread-1.jsonl"
    _write_jsonl(
        session_path,
        [
            _session_meta_event("thread-1"),
            {
                "timestamp": "2026-05-23T21:06:45Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": f"Work in repo `{repo}`"},
            },
            {
                "timestamp": "2026-05-23T21:06:46Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": f"Path mention: `{repo}`"}],
                },
            },
        ],
    )

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[session_path])

    assert observations == []


def test_collect_repo_path_observations_ignores_user_message_test_fixture_paths(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    current_repo = tmp_path / "codex-usage"
    fixture_repo = tmp_path / "ops-board"
    _write_git_config(current_repo, "https://github.com/Wenjun-Mao/codex_usage.git")
    _write_git_config(fixture_repo, "https://github.com/Wenjun-Mao/ops-board.git")
    session_path = sessions / "2026" / "05" / "23" / "thread-1.jsonl"
    _write_jsonl(
        session_path,
        [
            _session_meta_event("thread-1"),
            {
                "timestamp": "2026-05-23T21:06:45Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                f"Implement this in repo {current_repo}. "
                                f"Add a fixture path that points at {fixture_repo}."
                            ),
                        }
                    ],
                },
            },
        ],
    )

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[session_path])

    assert observations == []


def test_collect_repo_path_observations_ignores_function_call_output_paths(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    repo = tmp_path / "sports-feed"
    _write_git_config(repo, "https://github.com/Wenjun-Mao/sports_feed.git")
    session_path = sessions / "2026" / "05" / "23" / "thread-1.jsonl"
    _write_jsonl(
        session_path,
        [
            _session_meta_event("thread-1"),
            {
                "timestamp": "2026-05-23T21:06:45Z",
                "type": "response_item",
                "payload": {"type": "function_call_output", "output": f"Directory listing includes {repo}"},
            },
        ],
    )

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[session_path])

    assert observations == []


def test_collect_repo_path_observations_ignores_external_project_parent_workdir(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    parent_repo = tmp_path / "contentshuttle"
    external_parent = parent_repo / "zz_external_projects"
    _write_git_config(parent_repo, "https://github.com/Wenjun-Mao/ContentShuttle.git")
    external_parent.mkdir()
    session_path = sessions / "2026" / "05" / "23" / "thread-1.jsonl"
    _write_jsonl(
        session_path,
        [
            _session_meta_event("thread-1"),
            _function_call_workdir_event("2026-05-23T21:06:45Z", external_parent),
        ],
    )

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[session_path])

    assert observations == []


def test_collect_repo_path_observations_caches_repeated_repo_path_verification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    repo = tmp_path / "ops-board"
    _write_git_config(repo, "https://github.com/Wenjun-Mao/ops-board.git")
    session_path = sessions / "2026" / "05" / "23" / "thread-1.jsonl"
    rows = [_session_meta_event("thread-1")]
    rows.extend(_function_call_workdir_event(f"2026-05-23T21:00:0{second}Z", repo) for second in (1, 2, 3))
    _write_jsonl(session_path, rows)
    calls = 0
    original_normalize = project_transition_evidence.normalize_project_key

    def count_normalize(value: str) -> str:
        nonlocal calls
        calls += 1
        return original_normalize(value)

    monkeypatch.setattr(project_transition_evidence, "normalize_project_key", count_normalize)

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[session_path])

    assert len(observations) == 3
    assert calls == 1


def test_collect_repo_path_observations_ignores_invalid_utf8_jsonl_bytes(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    repo = tmp_path / "ops-board"
    _write_git_config(repo, "https://github.com/Wenjun-Mao/ops-board.git")
    session_path = sessions / "2026" / "05" / "23" / "thread-1.jsonl"
    session_path.parent.mkdir(parents=True)
    session_meta = json.dumps(_session_meta_event("thread-1"))
    response = json.dumps(_function_call_workdir_event("2026-05-23T21:06:45Z", repo))
    session_path.write_bytes(session_meta.encode() + b"\n\xff\xfe\xfa\n" + response.encode() + b"\n")

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[session_path])

    assert len(observations) == 1
    assert observations[0].thread_id == "thread-1"
    assert observations[0].project_key == "https://github.com/wenjun-mao/ops-board"


def test_parse_json_line_returns_none_for_extreme_json(monkeypatch) -> None:
    def raise_recursion_error(raw_line: str) -> object:
        raise RecursionError(f"too deep: {raw_line}")

    monkeypatch.setattr(project_transition_evidence.json, "loads", raise_recursion_error)

    parsed = project_transition_evidence._parse_json_line("[]")

    assert parsed is None


def test_collect_repo_path_observations_reads_state_sqlite_thread_cwd(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    repo = tmp_path / "ops-board"
    _write_git_config(repo, "https://github.com/Wenjun-Mao/ops-board.git")
    _write_thread_db(
        codex_home,
        cwd=str(repo),
        title="Task in ops-board",
        first_user_message="",
        preview="",
    )

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[])

    assert len(observations) == 1
    assert observations[0].thread_id == "thread-1"
    assert observations[0].project_key == "https://github.com/wenjun-mao/ops-board"
    assert observations[0].timestamp == datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC)
    assert observations[0].source == "state_5.sqlite:threads"


def test_collect_repo_path_observations_ignores_state_sqlite_prompt_paths(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    repo = tmp_path / "ops-board"
    _write_git_config(repo, "https://github.com/Wenjun-Mao/ops-board.git")
    _write_thread_db(
        codex_home,
        cwd="",
        title=f"Task in `{repo}`",
        first_user_message=f"Work in repo `{repo}`",
        preview=f"Preview path {repo}",
    )

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[])

    assert observations == []


def _session_meta_event(thread_id: str) -> dict[str, object]:
    return {
        "timestamp": "2026-05-23T21:00:00Z",
        "type": "session_meta",
        "payload": {"id": thread_id},
    }


def _function_call_workdir_event(timestamp: str, workdir: Path) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "arguments": json.dumps({"workdir": str(workdir), "command": "Get-Location"}),
        },
    }


def _write_jsonl(path: Path, rows: list[dict[str, object] | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(row if isinstance(row, str) else json.dumps(row) for row in rows), encoding="utf-8")


def _write_thread_db(
    codex_home: Path,
    *,
    cwd: str,
    title: str,
    first_user_message: str,
    preview: str,
) -> None:
    con = sqlite3.connect(codex_home / "state_5.sqlite")
    try:
        con.execute(
            "create table threads ("
            "id text primary key, created_at integer, updated_at integer, cwd text, "
            "title text, first_user_message text, preview text)"
        )
        con.execute(
            "insert into threads values (?, ?, ?, ?, ?, ?, ?)",
            ("thread-1", 1779570405000, 1779570405000, cwd, title, first_user_message, preview),
        )
        con.commit()
    finally:
        con.close()


def _write_git_config(repo: Path, url: str) -> None:
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(f'[remote "origin"]\n\turl = {url}\n', encoding="utf-8")
