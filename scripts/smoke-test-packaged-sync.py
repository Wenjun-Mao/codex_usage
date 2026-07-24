#!/usr/bin/env python3
"""Exercise a packaged codex-usage sync round trip without source imports."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from packaged_sync_smoke_validation import (
    INVENTORY_VERSION as INVENTORY_VERSION,
    LOCAL_METADATA_ESTIMATE_BYTES,
    PROJECT_KEY,
    PROJECT_LABEL as PROJECT_LABEL,
    REMOTE_TRANSFER_FORMAT_VERSION as REMOTE_TRANSFER_FORMAT_VERSION,
    SESSION_RELATIVE_PATH,
    TASKS_DIRNAME,
    TASK_TITLE,
    TASK_UPDATED_AT,
    THREAD_ID,
    UNRELATED_PROJECT_KEY,
    UNRELATED_SESSION_RELATIVE_PATH,
    UNRELATED_THREAD_ID,
    _read_required_bytes,
    _require_equal,
    _validate_baseline,
    _validate_destination_home,
    _validate_imported_task,
    _validate_inventory,
    _validate_remote_layout,
    _validate_status,
    _validate_sync_result,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(row, separators=(",", ":")) + "\n" for row in rows
    )
    path.write_text(payload, encoding="utf-8")


def _write_source_home(source_home: Path, project_root: Path) -> Path:
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
                    "cwd": str(project_root),
                    "git": {"repository_url": f"{PROJECT_KEY}.git"},
                },
            },
            {
                "timestamp": "2026-04-29T10:00:00.500Z",
                "type": "turn_context",
                "payload": {"turn_id": "turn-thread-1", "model": "gpt-5.5"},
            },
            {
                "timestamp": "2026-04-29T10:00:01Z",
                "type": "session_meta",
                "payload": {
                    "id": THREAD_ID,
                    "timestamp": "2026-04-29T10:00:01Z",
                    "cwd": str(project_root),
                    "git": {"repository_url": PROJECT_KEY},
                },
            },
            {
                "timestamp": TASK_UPDATED_AT,
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": usage},
                },
            },
            {
                "timestamp": "2026-04-29T10:00:03Z",
                "type": "session_meta",
                "payload": {
                    "id": "unrelated-project-metadata",
                    "timestamp": "2026-04-29T10:00:03Z",
                    "cwd": "/unrelated/source/spelling",
                    "git": {"repository_url": f"{UNRELATED_PROJECT_KEY}.git"},
                },
            },
            {
                "timestamp": "2026-04-29T10:00:04Z",
                "type": "event_msg",
                "payload": {"type": "task_started"},
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
            },
        ],
    )
    return source_jsonl


def _write_unrelated_source_task(source_home: Path) -> Path:
    unrelated_jsonl = source_home / "sessions" / UNRELATED_SESSION_RELATIVE_PATH
    _write_jsonl(
        unrelated_jsonl,
        [
            {
                "timestamp": "2026-04-29T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": UNRELATED_THREAD_ID,
                    "timestamp": "2026-04-29T10:00:00Z",
                    "cwd": "/unrelated/source/spelling",
                    "git": {"repository_url": UNRELATED_PROJECT_KEY},
                },
            },
            {
                "timestamp": TASK_UPDATED_AT,
                "type": "event_msg",
                "payload": {"type": "task_started"},
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
            },
            {
                "id": UNRELATED_THREAD_ID,
                "thread_name": "Unrelated packaged smoke task",
                "updated_at": TASK_UPDATED_AT,
            },
        ],
    )
    return unrelated_jsonl


def _run_json(
    executable: Path,
    codex_home: Path,
    args: list[str],
    *,
    allowed_returncodes: frozenset[int] = frozenset({0}),
) -> dict[str, object]:
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    environment["CODEX_USAGE_CACHE_DIR"] = str(
        codex_home.parent / "tool-cache" / codex_home.name
    )
    environment["PYTHONNOUSERSITE"] = "1"
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [str(executable), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        cwd=codex_home,
        check=False,
    )
    if completed.returncode not in allowed_returncodes:
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


def _run_sync(
    executable: Path,
    codex_home: Path,
    sync_dir: Path,
    direction: str,
    *,
    candidate_project_root: Path | None = None,
    thread_ids: tuple[str, ...] = (THREAD_ID,),
    allow_issue: bool = False,
) -> dict[str, object]:
    args = [
        "sync",
        direction,
        "--sync-dir",
        str(sync_dir),
    ]
    for thread_id in thread_ids:
        args.extend(["--thread-id", thread_id])
    if direction in {"pull", "push"}:
        args.extend(["--project-key", PROJECT_KEY])
    args.append("--json")
    if candidate_project_root is not None:
        args.extend(["--candidate-project-root", str(candidate_project_root)])
    return _run_json(
        executable,
        codex_home,
        args,
        allowed_returncodes=frozenset({0, 2}) if allow_issue else frozenset({0}),
    )


def _validate_cross_project_selection(result: dict[str, object]) -> None:
    _require_equal(result.get("outcome"), "issue", "cross-project selection outcome")
    issues = result.get("issues")
    if not isinstance(issues, list) or not any(
        isinstance(issue, dict) and issue.get("code") == "cross_project_selection"
        for issue in issues
    ):
        raise RuntimeError(
            "Packaged sync validation failed for cross-project selection issue"
        )


def _create_git_checkout(path: Path) -> None:
    git_dir = path / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = {PROJECT_KEY}.git\n',
        encoding="utf-8",
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
        source_project_root = root / "source-project"
        destination_project_root = root / "Destination Project Spelling"
        _create_git_checkout(source_project_root)
        _create_git_checkout(destination_project_root)
        target_home.mkdir(parents=True)

        source_jsonl = _write_source_home(source_home, source_project_root)
        source_bytes = _read_required_bytes(source_jsonl, "source task JSONL")
        remote_jsonl = sync_dir / TASKS_DIRNAME / f"{THREAD_ID}.jsonl"

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

        pushed = _run_sync(executable, source_home, sync_dir, "push")
        _validate_sync_result(
            pushed,
            "push",
            local_jsonl=source_jsonl,
            remote_jsonl=remote_jsonl,
            source_bytes=source_bytes,
        )
        _validate_remote_layout(sync_dir, source_bytes)
        _validate_baseline(source_home, source_bytes, source_bytes)
        unrelated_jsonl = _write_unrelated_source_task(source_home)
        unrelated_bytes = _read_required_bytes(unrelated_jsonl, "unrelated task JSONL")

        remote_inventory = _run_json(
            executable,
            target_home,
            [
                "sync",
                "inventory",
                "--sync-dir",
                str(sync_dir),
                "--json",
                "--candidate-project-root",
                str(destination_project_root),
            ],
        )
        _validate_destination_home(target_home, "inventory")
        _validate_inventory(
            remote_inventory,
            "remote",
            len(source_bytes),
            candidate_project_root=destination_project_root,
        )

        pulled = _run_sync(
            executable,
            target_home,
            sync_dir,
            "pull",
            candidate_project_root=destination_project_root,
        )
        imported_jsonl = target_home / "sessions" / SESSION_RELATIVE_PATH
        _validate_destination_home(
            target_home,
            "pull",
            imported_jsonl=imported_jsonl,
        )
        _validate_sync_result(
            pulled,
            "pull",
            local_jsonl=imported_jsonl,
            remote_jsonl=remote_jsonl,
            source_bytes=source_bytes,
        )
        imported_bytes = _validate_imported_task(
            imported_jsonl,
            source_bytes,
            destination_project_root,
        )
        _validate_remote_layout(sync_dir, source_bytes)
        _validate_baseline(target_home, imported_bytes, source_bytes)
        _require_equal(
            _read_required_bytes(source_jsonl, "source task JSONL after import"),
            source_bytes,
            "source-home isolation",
        )

        rejected = _run_sync(
            executable,
            source_home,
            sync_dir,
            "push",
            thread_ids=(THREAD_ID, UNRELATED_THREAD_ID),
            allow_issue=True,
        )
        _validate_cross_project_selection(rejected)
        _require_equal(
            _read_required_bytes(source_jsonl, "source task after rejected selection"),
            source_bytes,
            "cross-project local task isolation",
        )
        _require_equal(
            _read_required_bytes(unrelated_jsonl, "unrelated task after rejected selection"),
            unrelated_bytes,
            "cross-project unrelated task isolation",
        )
        _require_equal(
            _read_required_bytes(remote_jsonl, "remote task after rejected selection"),
            source_bytes,
            "cross-project remote task isolation",
        )

        status = _run_sync(
            executable,
            target_home,
            sync_dir,
            "status",
            candidate_project_root=destination_project_root,
        )
        _validate_destination_home(
            target_home,
            "status",
            imported_jsonl=imported_jsonl,
        )
        _validate_status(
            status,
            imported_jsonl,
            remote_jsonl,
            imported_bytes,
            source_bytes,
        )

    print(
        "Packaged Task Transfer smoke passed: inventory=local,remote pushed=1 pulled=1 "
        "status=up-to-date format_version=3"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
