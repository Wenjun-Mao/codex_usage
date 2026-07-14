import json
from pathlib import Path

from codex_usage.session_cache import load_cached_session_data
from codex_usage.threads import list_threads, list_threads_from_cached_data


def test_list_threads_filters_by_project_key_and_returns_titles(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    project = tmp_path / "repo"
    _write_git_config(project, "https://github.com/example/demo.git")
    session_path = _write_session(sessions, "thread-1", project, total=120)
    _write_session(sessions, "thread-2", tmp_path / "other", total=75)
    _write_index(
        codex_home,
        {
            "id": "thread-1",
            "thread_name": "Demo thread",
            "updated_at": "2026-04-29T10:05:00Z",
        },
    )

    threads = list_threads(
        [sessions], project_keys=["https://github.com/example/demo"]
    )

    assert [thread.thread_id for thread in threads] == ["thread-1"]
    assert threads[0].title == "Demo thread"
    assert threads[0].project_key == "https://github.com/example/demo"
    assert threads[0].total_tokens == 120
    assert threads[0].session_path == session_path
    expected_session_bytes = session_path.stat().st_size
    assert threads[0].session_bytes == expected_session_bytes
    assert threads[0].estimated_sync_bytes == expected_session_bytes + 4096
    assert threads[0].to_dict()["session_bytes"] == expected_session_bytes
    assert threads[0].to_dict()["estimated_sync_bytes"] == expected_session_bytes + 4096


def test_list_threads_filters_by_transition_target_project(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    old_repo = tmp_path / "signoz-stack"
    new_repo = tmp_path / "ops-board"
    _write_git_config(new_repo, "https://github.com/example/ops-board.git")
    day = sessions / "2026" / "05" / "23"
    day.mkdir(parents=True)
    path = day / "rollout-2026-05-23T17-00-00-thread-1.jsonl"
    rows = [
        {
            "timestamp": "2026-05-23T21:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "thread-1",
                "timestamp": "2026-05-23T21:00:00Z",
                "cwd": str(old_repo),
                "git": {
                    "repository_url": "https://github.com/example/signoz-stack.git"
                },
                "memory_mode": "enabled",
                "base_instructions": {"text": "instructions"},
            },
        },
        {
            "timestamp": "2026-05-23T21:00:01Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.5"},
        },
        _token_count_event("2026-05-23T21:00:02Z", 100),
        {
            "timestamp": "2026-05-23T21:06:45Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "arguments": json.dumps(
                    {"workdir": str(new_repo), "command": "Get-Location"}
                ),
            },
        },
        _token_count_event("2026-05-23T21:06:46Z", 300),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    _write_index(
        codex_home,
        {
            "id": "thread-1",
            "thread_name": "Ops thread",
            "updated_at": "2026-05-23T21:07:00Z",
        },
    )

    threads = list_threads(
        [sessions], project_keys=["https://github.com/example/ops-board"]
    )

    assert [thread.thread_id for thread in threads] == ["thread-1"]
    assert threads[0].title == "Ops thread"
    assert threads[0].project_key == "https://github.com/example/ops-board"
    assert "https://github.com/example/signoz-stack" in threads[0].project_aliases
    assert threads[0].total_tokens == 300
    assert threads[0].session_path == path


def test_list_threads_normalizes_raw_path_project_filter_for_metadata_fallback(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    project = tmp_path / "Repo With Spaces"
    _write_git_config(project, "https://github.com/example/demo.git")
    session_path = _write_metadata_only_session(sessions, "thread-1", project)

    threads = list_threads([sessions], project_keys=[str(project)])

    assert [thread.thread_id for thread in threads] == ["thread-1"]
    assert threads[0].project_key == "https://github.com/example/demo"
    assert threads[0].total_tokens == 0
    assert threads[0].session_path == session_path


def test_list_threads_can_use_cached_session_data(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    project = tmp_path / "repo"
    _write_git_config(project, "https://github.com/example/demo.git")
    session_path = _write_session(sessions, "thread-1", project, total=120)
    _write_index(
        codex_home,
        {
            "id": "thread-1",
            "thread_name": "Demo thread",
            "updated_at": "2026-04-29T10:05:00Z",
        },
    )
    data = load_cached_session_data(
        [sessions], cache_dir=tmp_path / "cache", auto_transitions=True
    )

    threads = list_threads_from_cached_data(
        data, project_keys=["https://github.com/example/demo"]
    )

    assert [thread.thread_id for thread in threads] == ["thread-1"]
    assert threads[0].title == "Demo thread"
    assert threads[0].project_key == "https://github.com/example/demo"
    assert threads[0].session_path == session_path
    assert threads[0].estimated_sync_bytes >= threads[0].session_bytes


def test_thread_listing_estimates_sync_bytes_without_importing_sync(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/one", 100)

    threads = list_threads([sessions], auto_transitions=False)

    assert threads[0].session_bytes == session_path.stat().st_size
    assert threads[0].estimated_sync_bytes == session_path.stat().st_size + 4096
    assert threads[0].to_dict()["estimated_sync_bytes"] == session_path.stat().st_size + 4096


def test_thread_listing_excludes_retained_missing_files(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", "/repo/one", 100)
    cache_dir = tmp_path / "cache"
    load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    session_path.unlink()
    data = load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)

    threads = list_threads_from_cached_data(data)

    assert threads == []


def _write_session(
    sessions: Path, session_id: str, cwd: str | Path, total: int
) -> Path:
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"{session_id}.jsonl"
    rows = [
        {
            "timestamp": "2026-04-29T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "timestamp": "2026-04-29T10:00:00Z",
                "cwd": str(cwd),
            },
        },
        {"timestamp": "2026-04-29T10:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.5"}},
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
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _write_metadata_only_session(
    sessions: Path, session_id: str, cwd: Path
) -> Path:
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"{session_id}.jsonl"
    rows = [
        {
            "timestamp": "2026-04-29T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "timestamp": "2026-04-29T10:00:00Z",
                "cwd": str(cwd),
            },
        }
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _token_count_event(timestamp: str, total: int) -> dict[str, object]:
    usage = {
        "input_tokens": total,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": total,
    }
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": "token_count", "info": {"total_token_usage": usage}},
    }


def _write_index(codex_home: Path, entry: dict[str, str]) -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    with (codex_home / "session_index.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def _write_git_config(repo: Path, url: str) -> None:
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = {url}\n', encoding="utf-8"
    )
