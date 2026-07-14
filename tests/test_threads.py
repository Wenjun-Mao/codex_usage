import json
from pathlib import Path

from codex_usage.session_cache import load_cached_session_data
from codex_usage.threads import list_threads, list_threads_from_cached_data


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


def _write_session(sessions: Path, session_id: str, cwd: str, total: int) -> Path:
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"{session_id}.jsonl"
    rows = [
        {
            "timestamp": "2026-04-29T10:00:00Z",
            "type": "session_meta",
            "payload": {"id": session_id, "timestamp": "2026-04-29T10:00:00Z", "cwd": cwd},
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
