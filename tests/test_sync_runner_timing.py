import json
from pathlib import Path

import codex_usage.sync.runner as runner_module
from codex_usage.project_identity import normalize_project_key
from codex_usage.session_cache import load_cached_session_data
from codex_usage.sync import ProjectResolutionRequest, pull_sync, push_sync


def test_conflict_result_includes_all_completed_planning_timing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    sync_dir = tmp_path / "sync"
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    push_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
        project_key=normalize_project_key(str(tmp_path / "repo")),
    )
    _append_token_event(local_path, "2026-07-13T12:01:00Z", 180)
    _append_token_event(
        sync_dir / "tasks" / "thread-1.jsonl",
        "2026-07-13T12:02:00Z",
        240,
    )
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    clock = iter(
        (
            1_000_000,
            3_000_000,
            4_000_000,
            6_000_000,
            7_000_000,
            10_000_000,
        )
    )
    monkeypatch.setattr(runner_module, "perf_counter_ns", lambda: next(clock))

    result = pull_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        project_resolution=ProjectResolutionRequest(),
        project_key=normalize_project_key(str(tmp_path / "repo")),
    )

    assert result.timings_ms.planning == 7


def _write_session(
    sessions_dir: Path,
    thread_id: str,
    cwd: Path,
    total: int,
) -> Path:
    cwd.mkdir(parents=True, exist_ok=True)
    day_dir = sessions_dir / "2026" / "04" / "29"
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"rollout-2026-04-29T10-00-00-{thread_id}.jsonl"
    rows = [
        {
            "timestamp": "2026-04-29T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": thread_id,
                "timestamp": "2026-04-29T10:00:00Z",
                "cwd": str(cwd),
                "memory_mode": "enabled",
                "base_instructions": {"text": "instructions"},
            },
        },
        {
            "timestamp": "2026-04-29T10:00:01Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.5"},
        },
        _token_count_event("2026-04-29T10:00:02Z", total),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _append_token_event(path: Path, timestamp: str, total: int) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps(_token_count_event(timestamp, total)))


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
