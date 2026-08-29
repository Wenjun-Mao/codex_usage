from __future__ import annotations

import json
import os
import queue
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

import codex_usage.session_cache_refresh as refresh_module
from codex_usage.parallel.usage import UsageParseRequest, parse_usage_request
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data
from codex_usage.session_cache_refresh import (
    StaleAppendCheckpointError,
    _commit_result_group,
)
from codex_usage.session_cache_requests import (
    eligible_append_checkpoint,
    load_cached_rows,
)
from codex_usage.session_inventory import collect_session_file_inventory


def test_second_process_waits_for_refresh_and_reuses_committed_append(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", 100)
    cache_dir = tmp_path / "cache"
    _load(sessions, cache_dir)
    _append_token_count(session_path, "2026-04-29T10:05:00Z", 150)

    parsed_marker = tmp_path / "first-parsed"
    release_marker = tmp_path / "release-first"
    first = _start_refresh_process(
        sessions,
        cache_dir,
        parsed_marker=parsed_marker,
        release_marker=release_marker,
    )
    second: subprocess.Popen[str] | None = None
    try:
        _wait_for_path(parsed_marker)
        second = _start_refresh_process(sessions, cache_dir)
        assert second.stdout is not None
        second_output: queue.Queue[str] = queue.Queue()
        reader = threading.Thread(
            target=lambda: second_output.put(second.stdout.readline()), daemon=True
        )
        reader.start()
        with pytest.raises(queue.Empty):
            second_output.get(timeout=0.5)

        release_marker.touch()
        first_payload = _read_refresh_result(first)
        second_line = second_output.get(timeout=10)
        assert second.wait(timeout=10) == 0, second.stderr.read() if second.stderr else ""
        second_payload = json.loads(second_line)

        assert first_payload == {"parsed": 1, "totals": [100, 50]}
        assert second_payload == {"parsed": 0, "totals": [100, 50]}
    finally:
        release_marker.touch(exist_ok=True)
        _stop_process(first)
        if second is not None:
            _stop_process(second)

    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as connection:
        assert connection.execute(
            "select count(*) from usage_records"
        ).fetchone() == (2,)
        assert connection.execute(
            "select count(*) from ("
            "select file_key, record_index from usage_records "
            "group by file_key, record_index having count(*) > 1"
            ")"
        ).fetchone() == (0,)


def test_stale_append_result_rolls_back_before_duplicate_record_indexes(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", 100)
    cache_dir = tmp_path / "cache"
    _load(sessions, cache_dir)
    _append_token_count(session_path, "2026-04-29T10:05:00Z", 150)
    inventory = collect_session_file_inventory([sessions])
    (entry,) = inventory

    with sqlite3.connect(cache_dir / CACHE_DB_NAME) as stale_connection:
        stale_connection.row_factory = sqlite3.Row
        checkpoint = eligible_append_checkpoint(
            stale_connection,
            entry,
            load_cached_rows(stale_connection)[entry.file_key],
            rebuilt=False,
        )
        assert checkpoint is not None
        stale_result = parse_usage_request(
            UsageParseRequest(
                ordinal=0,
                file_key=entry.file_key,
                path=entry.path,
                size_bytes=entry.size_bytes,
                mtime_ns=entry.mtime_ns,
                checkpoint=checkpoint,
            )
        )
        assert stale_result.appended is not None

        committed = _load(sessions, cache_dir)
        assert [record.usage.total_tokens for record in committed.records] == [100, 50]

        with pytest.raises(StaleAppendCheckpointError, match="thread-1"):
            _commit_result_group(
                stale_connection,
                [sessions],
                inventory,
                (stale_result,),
            )

        assert [
            tuple(row)
            for row in stale_connection.execute(
                "select file_key, record_index, total_tokens from usage_records "
                "order by file_key, record_index"
            )
        ] == [("thread-1", 0, 100), ("thread-1", 1, 50)]


def test_refresh_retries_once_after_stale_checkpoint_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    session_path = _write_session(sessions, "thread-1", 100)
    cache_dir = tmp_path / "cache"
    _load(sessions, cache_dir)
    _append_token_count(session_path, "2026-04-29T10:05:00Z", 150)

    original_refresh = refresh_module.refresh_files
    calls = 0

    def stale_once(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise StaleAppendCheckpointError("injected stale checkpoint")
        return original_refresh(*args, **kwargs)

    monkeypatch.setattr(refresh_module, "refresh_files", stale_once)

    refreshed = _load(sessions, cache_dir)

    assert calls == 2
    assert refreshed.stats.files_appended == 1
    assert [record.usage.total_tokens for record in refreshed.records] == [100, 50]


def _start_refresh_process(
    sessions: Path,
    cache_dir: Path,
    *,
    parsed_marker: Path | None = None,
    release_marker: Path | None = None,
) -> subprocess.Popen[str]:
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(source_root), environment.get("PYTHONPATH", "")) if part
    )
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import json
                import sys
                import time
                from pathlib import Path

                import codex_usage.session_cache_refresh as refresh_module
                from codex_usage.session_cache import load_cached_session_data

                sessions = Path(sys.argv[1])
                cache_dir = Path(sys.argv[2])
                parsed_marker = Path(sys.argv[3]) if sys.argv[3] else None
                release_marker = Path(sys.argv[4]) if sys.argv[4] else None
                if parsed_marker is not None:
                    original_parse = refresh_module.parse_usage_request

                    def parse_then_wait(request):
                        result = original_parse(request)
                        parsed_marker.touch()
                        while not release_marker.exists():
                            time.sleep(0.01)
                        return result

                    refresh_module.parse_usage_request = parse_then_wait

                data = load_cached_session_data(
                    [sessions],
                    cache_dir=cache_dir,
                    auto_transitions=False,
                    max_workers=1,
                )
                print(
                    json.dumps(
                        {
                            "parsed": data.stats.files_parsed,
                            "totals": [record.usage.total_tokens for record in data.records],
                        }
                    ),
                    flush=True,
                )
                """
            ),
            str(sessions),
            str(cache_dir),
            "" if parsed_marker is None else str(parsed_marker),
            "" if release_marker is None else str(release_marker),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )


def _read_refresh_result(process: subprocess.Popen[str]) -> dict[str, object]:
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stderr
    return json.loads(stdout)


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)


def _wait_for_path(path: Path) -> None:
    deadline = time.monotonic() + 10
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {path}")
        time.sleep(0.01)


def _load(sessions: Path, cache_dir: Path):
    return load_cached_session_data(
        [sessions],
        cache_dir=cache_dir,
        auto_transitions=False,
        max_workers=1,
    )


def _write_session(sessions: Path, session_id: str, total: int) -> Path:
    day = sessions / "2026" / "04" / "29"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"{session_id}.jsonl"
    rows = [
        {
            "timestamp": "2026-04-29T10:00:00Z",
            "type": "session_meta",
            "payload": {"id": session_id, "cwd": "/repo/demo"},
        },
        {
            "timestamp": "2026-04-29T10:00:01Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.5"},
        },
        _token_count("2026-04-29T10:00:02Z", total),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _append_token_count(path: Path, timestamp: str, total: int) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps(_token_count(timestamp, total)))


def _token_count(timestamp: str, total: int) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total,
                    "total_tokens": total,
                }
            },
        },
    }
