#!/usr/bin/env python3
"""Exercise a packaged codex-usage sync round trip without source imports."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


THREAD_ID = "thread-1"
SESSION_RELATIVE_PATH = Path("2026") / "04" / "29" / f"{THREAD_ID}.jsonl"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(row, separators=(",", ":")) + "\n" for row in rows
    )
    path.write_text(payload, encoding="utf-8")


def _write_source_home(source_home: Path) -> Path:
    source_jsonl = source_home / "sessions" / SESSION_RELATIVE_PATH
    usage = {
        "input_tokens": 100,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 100,
    }
    _write_jsonl(
        source_jsonl,
        [
            {
                "timestamp": "2026-04-29T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": THREAD_ID,
                    "timestamp": "2026-04-29T10:00:00Z",
                    "cwd": "/tmp/packaged-sync-smoke",
                },
            },
            {
                "timestamp": "2026-04-29T10:00:01Z",
                "type": "turn_context",
                "payload": {"turn_id": "turn-thread-1", "model": "gpt-5.5"},
            },
            {
                "timestamp": "2026-04-29T10:00:02Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": usage},
                },
            },
        ],
    )
    _write_jsonl(
        source_home / "session_index.jsonl",
        [
            {
                "id": THREAD_ID,
                "thread_name": "Packaged sync smoke",
                "updated_at": "2026-04-29T10:00:02Z",
            }
        ],
    )
    return source_jsonl


def _run_sync(executable: Path, codex_home: Path, sync_dir: Path) -> dict[str, object]:
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    command = [
        str(executable),
        "sync",
        "run",
        "--sync-dir",
        str(sync_dir),
        "--thread-id",
        THREAD_ID,
        "--json",
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Packaged sync exited with code {completed.returncode}.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Packaged sync stdout was not one JSON object.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        ) from error
    if not isinstance(result, dict):
        raise RuntimeError(f"Packaged sync returned non-object JSON: {result!r}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", required=True, type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve()
    if not executable.is_file():
        parser.error(f"executable does not exist: {executable}")

    with tempfile.TemporaryDirectory(prefix="codex-usage-packaged-sync-") as temp_dir:
        root = Path(temp_dir)
        source_home = root / "source-home"
        target_home = root / "target-home"
        sync_dir = root / "sync"
        source_jsonl = _write_source_home(source_home)

        pushed = _run_sync(executable, source_home, sync_dir)
        remote_jsonl = sync_dir / "conversations" / f"{THREAD_ID}.jsonl"
        sync_index = sync_dir / "sync-index.json"

        assert pushed["outcome"] == "completed"
        assert pushed["counts"]["pushed"] == 1
        assert remote_jsonl.read_bytes() == source_jsonl.read_bytes()
        assert json.loads(sync_index.read_text(encoding="utf-8"))["format_version"] == 2

        pulled = _run_sync(executable, target_home, sync_dir)
        imported_jsonl = target_home / "sessions" / SESSION_RELATIVE_PATH

        assert pulled["counts"]["pulled"] == 1
        assert imported_jsonl.read_bytes() == source_jsonl.read_bytes()
        assert not (sync_dir / "threads").exists()

    print("Packaged sync smoke passed: pushed=1 pulled=1 format_version=2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
