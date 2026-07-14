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
TASK_TITLE = "Packaged sync smoke"
TASK_UPDATED_AT = "2026-04-29T10:00:02Z"
PROJECT_KEY = "/tmp/packaged-sync-smoke"
PROJECT_LABEL = "packaged-sync-smoke"
INVENTORY_VERSION = 1
SYNC_FORMAT_VERSION = 2
LOCAL_METADATA_ESTIMATE_BYTES = 4096


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
                "thread_name": TASK_TITLE,
                "updated_at": TASK_UPDATED_AT,
            }
        ],
    )
    return source_jsonl


def _run_json(
    executable: Path,
    codex_home: Path,
    args: list[str],
) -> dict[str, object]:
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    completed = subprocess.run(
        [str(executable), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Packaged command exited with code {completed.returncode}.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Packaged command stdout was not one JSON object.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        ) from error
    if not isinstance(result, dict):
        raise RuntimeError(f"Packaged command returned non-object JSON: {result!r}")
    return result


def _run_sync(executable: Path, codex_home: Path, sync_dir: Path) -> dict[str, object]:
    return _run_json(
        executable,
        codex_home,
        ["sync", "run", "--sync-dir", str(sync_dir), "--thread-id", THREAD_ID, "--json"],
    )


def _require_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise RuntimeError(
            f"Packaged sync validation failed for {label}: "
            f"expected {expected!r}, got {actual!r}"
        )


def _require_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RuntimeError(
            f"Packaged sync validation failed for {label}: expected an object, got {value!r}"
        )
    return value


def _require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise RuntimeError(
            f"Packaged sync validation failed for {label}: expected a list, got {value!r}"
        )
    return value


def _validate_inventory(
    result: dict[str, object],
    availability: str,
    estimated_sync_bytes: int,
) -> None:
    _require_equal(
        set(result),
        {"inventory_version", "projects", "issues"},
        f"{availability} inventory fields",
    )
    _require_equal(
        result.get("inventory_version"),
        INVENTORY_VERSION,
        f"{availability} inventory_version",
    )
    _require_equal(result.get("issues"), [], f"{availability} inventory issues")

    projects = _require_list(result.get("projects"), f"{availability} inventory projects")
    _require_equal(len(projects), 1, f"{availability} inventory project count")
    project = _require_object(projects[0], f"{availability} inventory project")
    _require_equal(
        set(project),
        {"project_key", "project_label", "tasks"},
        f"{availability} inventory project fields",
    )
    _require_equal(project.get("project_key"), PROJECT_KEY, f"{availability} project key")
    _require_equal(
        project.get("project_label"),
        PROJECT_LABEL,
        f"{availability} project label",
    )

    tasks = _require_list(project.get("tasks"), f"{availability} inventory tasks")
    _require_equal(len(tasks), 1, f"{availability} inventory task count")
    task = _require_object(tasks[0], f"{availability} inventory task")
    _require_equal(
        set(task),
        {
            "thread_id",
            "title",
            "updated_at",
            "estimated_sync_bytes",
            "availability",
        },
        f"{availability} inventory task fields",
    )
    _require_equal(task.get("thread_id"), THREAD_ID, f"{availability} task thread id")
    _require_equal(task.get("title"), TASK_TITLE, f"{availability} task title")
    _require_equal(task.get("updated_at"), TASK_UPDATED_AT, f"{availability} task timestamp")
    _require_equal(
        task.get("estimated_sync_bytes"),
        estimated_sync_bytes,
        f"{availability} task estimated sync bytes",
    )
    _require_equal(
        task.get("availability"),
        availability,
        f"{availability} task availability",
    )


def _validate_sync_result(result: dict[str, object], direction: str) -> None:
    if direction not in {"push", "pull"}:
        raise ValueError(f"Unsupported packaged sync direction: {direction!r}")
    pushing = direction == "push"
    expected_counts = {
        "discovered": 1 if pushing else 0,
        "selected": 1,
        "remote": 0 if pushing else 1,
        "pulled": 0 if pushing else 1,
        "pushed": 1 if pushing else 0,
        "unchanged": 0,
        "conflicts": 0,
        "issues": 0,
    }
    _require_equal(result.get("outcome"), "completed", f"{direction} outcome")
    _require_equal(result.get("counts"), expected_counts, f"{direction} counts")
    _require_equal(
        result.get("pulled"),
        [] if pushing else [THREAD_ID],
        f"{direction} pulled thread ids",
    )
    _require_equal(
        result.get("pushed"),
        [THREAD_ID] if pushing else [],
        f"{direction} pushed thread ids",
    )
    _require_equal(result.get("issues"), [], f"{direction} issues")


def _read_required_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise RuntimeError(
            f"Packaged sync validation could not read {label} at {path}: {error}"
        ) from error


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    contents = _read_required_bytes(path, label)
    try:
        value = json.loads(contents)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError(
            f"Packaged sync validation found invalid JSON in {label} at {path}"
        ) from error
    return _require_object(value, label)


def _validate_remote_layout(sync_dir: Path, source_bytes: bytes) -> None:
    conversations_dir = sync_dir / "conversations"
    try:
        conversation_files = sorted(path.name for path in conversations_dir.iterdir())
    except OSError as error:
        raise RuntimeError(
            "Packaged sync validation could not inspect the version-2 conversations "
            f"directory at {conversations_dir}: {error}"
        ) from error
    _require_equal(
        conversation_files,
        [f"{THREAD_ID}.jsonl"],
        "version-2 conversation files",
    )
    remote_jsonl = conversations_dir / f"{THREAD_ID}.jsonl"
    _require_equal(
        _read_required_bytes(remote_jsonl, "remote task JSONL"),
        source_bytes,
        "pushed task JSONL bytes",
    )

    sync_index = _read_json_object(sync_dir / "sync-index.json", "sync index")
    _require_equal(
        sync_index.get("format_version"),
        SYNC_FORMAT_VERSION,
        "sync index format_version",
    )
    indexed_threads = _require_object(sync_index.get("threads"), "sync index threads")
    _require_equal(set(indexed_threads), {THREAD_ID}, "sync index thread ids")
    index_entry = _require_object(indexed_threads[THREAD_ID], "sync index task entry")
    _require_equal(
        index_entry.get("file"),
        f"conversations/{THREAD_ID}.jsonl",
        "sync index task file",
    )
    if (sync_dir / "threads").exists():
        raise RuntimeError(
            "Packaged sync validation found the obsolete version-1 threads directory"
        )


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
        source_bytes = _read_required_bytes(source_jsonl, "source task JSONL")

        local_inventory = _run_json(
            executable,
            source_home,
            ["sync", "inventory", "--sync-dir", str(sync_dir), "--json"],
        )
        _validate_inventory(
            local_inventory,
            "local",
            len(source_bytes) + LOCAL_METADATA_ESTIMATE_BYTES,
        )

        pushed = _run_sync(executable, source_home, sync_dir)
        _validate_sync_result(pushed, "push")
        _validate_remote_layout(sync_dir, source_bytes)

        remote_inventory = _run_json(
            executable,
            target_home,
            ["sync", "inventory", "--sync-dir", str(sync_dir), "--json"],
        )
        _validate_inventory(remote_inventory, "remote", len(source_bytes))

        pulled = _run_sync(executable, target_home, sync_dir)
        imported_jsonl = target_home / "sessions" / SESSION_RELATIVE_PATH
        _validate_sync_result(pulled, "pull")
        _require_equal(
            _read_required_bytes(imported_jsonl, "imported task JSONL"),
            source_bytes,
            "pulled task JSONL bytes",
        )
        _validate_remote_layout(sync_dir, source_bytes)

    print(
        "Packaged sync smoke passed: "
        "inventory=local,remote pushed=1 pulled=1 format_version=2"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
