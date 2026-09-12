"""Resumable, artifact-first recovery of historical image operations."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from codex_usage.image_artifacts import inspect_generated_artifact
from codex_usage.parser import parse_session_append, parse_session_generation
from codex_usage.session_cache_generations import insert_image_operations
from codex_usage.session_inventory import session_file_key
from codex_usage.session_parser_models import (
    SessionParseCheckpoint,
    parser_state_from_json,
    parser_state_to_json,
)


IMAGE_BACKFILL_STATE_KEY = "image_backfill_state_v1"
IMAGE_BACKFILL_SLICE_BYTES = 16 * 1024 * 1024
_TASK_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_ARTIFACT_NAME = re.compile(
    r"^exec-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.png$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ImageBackfillResult:
    changed: bool
    status: str
    artifacts_total: int
    tasks_total: int
    tasks_completed: int
    tasks_unavailable: int
    pending_tasks: int


def run_image_backfill_slice(
    codex_home: Path,
    ledger_path: Path,
) -> ImageBackfillResult:
    """Inspect artifacts first, then read at most one exact owning rollout slice."""
    task_artifacts = _artifact_inventory(codex_home / "generated_images")
    with sqlite3.connect(ledger_path) as connection:
        connection.row_factory = sqlite3.Row
        state = _load_state(connection)
        completed = set(state.get("completed", []))
        unavailable = dict(state.get("unavailable", {}))
        checkpoints = dict(state.get("checkpoints", {}))

    known_tasks = set(task_artifacts)
    completed.intersection_update(known_tasks)
    unavailable = {
        task_id: reason
        for task_id, reason in unavailable.items()
        if task_id in known_tasks
    }
    checkpoints = {
        task_id: checkpoint
        for task_id, checkpoint in checkpoints.items()
        if task_id in known_tasks
    }
    candidates = sorted(known_tasks - completed - set(unavailable))
    changed = False
    if candidates:
        changed = True
        task_id = candidates[0]
        if not _has_valid_artifact(codex_home / "generated_images" / task_id):
            unavailable[task_id] = "invalid_artifact"
            owning = []
        else:
            owning = _owning_rollouts(codex_home, task_id)
        if task_id not in unavailable and len(owning) != 1:
            unavailable[task_id] = "missing" if not owning else "ambiguous"
        elif task_id not in unavailable:
            path = owning[0]
            checkpoint_value = checkpoints.get(task_id)
            try:
                if isinstance(checkpoint_value, dict):
                    checkpoint = _checkpoint_from_dict(checkpoint_value, path)
                    parsed = parse_session_append(
                        path,
                        checkpoint,
                        stop_offset=path.stat().st_size,
                        max_bytes=IMAGE_BACKFILL_SLICE_BYTES,
                    )
                else:
                    parsed = parse_session_generation(
                        path,
                        stop_offset=path.stat().st_size,
                        max_bytes=IMAGE_BACKFILL_SLICE_BYTES,
                    )
                file_key = _file_key_for_path(ledger_path, task_id, path)
                with sqlite3.connect(ledger_path) as connection:
                    insert_image_operations(
                        connection,
                        file_key,
                        parsed.image_operations,
                    )
                    connection.commit()
                if parsed.checkpoint.byte_offset >= path.stat().st_size:
                    completed.add(task_id)
                    checkpoints.pop(task_id, None)
                else:
                    checkpoints[task_id] = _checkpoint_to_dict(parsed.checkpoint)
            except (OSError, ValueError) as error:
                unavailable[task_id] = type(error).__name__
                checkpoints.pop(task_id, None)

    pending = known_tasks - completed - set(unavailable)
    status = "partial" if unavailable else "pending" if pending else "complete"
    stored = {
        "version": 1,
        "status": status,
        "artifacts_total": sum(task_artifacts.values()),
        "tasks_total": len(known_tasks),
        "completed": sorted(completed),
        "unavailable": dict(sorted(unavailable.items())),
        "checkpoints": checkpoints,
    }
    with sqlite3.connect(ledger_path) as connection:
        connection.execute(
            "insert or replace into ledger_meta (key, value) values (?, ?)",
            (
                IMAGE_BACKFILL_STATE_KEY,
                json.dumps(stored, separators=(",", ":"), sort_keys=True),
            ),
        )
        connection.commit()
    return ImageBackfillResult(
        changed,
        status,
        stored["artifacts_total"],
        len(known_tasks),
        len(completed),
        len(unavailable),
        len(pending),
    )


def _artifact_inventory(root: Path) -> dict[str, int]:
    if not root.is_dir():
        return {}
    inventory: dict[str, int] = {}
    for directory in sorted(root.iterdir(), key=lambda item: item.name):
        if not directory.is_dir() or not _TASK_ID.fullmatch(directory.name):
            continue
        artifacts = [
            path
            for path in directory.iterdir()
            if path.is_file() and _ARTIFACT_NAME.fullmatch(path.name)
        ]
        if not artifacts:
            continue
        inventory[directory.name] = len(artifacts)
    return inventory


def _has_valid_artifact(directory: Path) -> bool:
    """Use one bounded header probe before admitting an owning rollout read."""
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.is_file() and _ARTIFACT_NAME.fullmatch(path.name):
            if inspect_generated_artifact(directory, path.name).width is not None:
                return True
    return False


def _owning_rollouts(codex_home: Path, task_id: str) -> list[Path]:
    matches: list[Path] = []
    for root_name in ("sessions", "archived_sessions"):
        root = codex_home / root_name
        if root.is_dir():
            matches.extend(root.rglob(f"*{task_id}*.jsonl"))
    return sorted({path.resolve() for path in matches})


def _file_key_for_path(ledger_path: Path, task_id: str, path: Path) -> str:
    with sqlite3.connect(ledger_path) as connection:
        row = connection.execute(
            "select file_key from files where session_id = ? and path = ?",
            (task_id, str(path)),
        ).fetchone()
    return str(row[0]) if row is not None else session_file_key(path)


def _load_state(connection: sqlite3.Connection) -> dict[str, object]:
    row = connection.execute(
        "select value from ledger_meta where key = ?",
        (IMAGE_BACKFILL_STATE_KEY,),
    ).fetchone()
    if row is None:
        return {}
    try:
        value = json.loads(str(row[0]))
    except (TypeError, ValueError):
        return {}
    if not isinstance(value, dict) or value.get("version") != 1:
        return {}
    if (
        not isinstance(value.get("completed", []), list)
        or not isinstance(value.get("unavailable", {}), dict)
        or not isinstance(value.get("checkpoints", {}), dict)
    ):
        return {}
    return value


def _checkpoint_to_dict(checkpoint: SessionParseCheckpoint) -> dict[str, object]:
    return {
        "byte_offset": checkpoint.byte_offset,
        "next_record_index": checkpoint.next_record_index,
        "next_candidate_index": checkpoint.next_candidate_index,
        "source_device": checkpoint.source_device,
        "source_inode": checkpoint.source_inode,
        "head_sha256": checkpoint.head_sha256,
        "boundary_sha256": checkpoint.boundary_sha256,
        "session_id": checkpoint.session_id,
        "state_json": parser_state_to_json(checkpoint.state),
    }


def _checkpoint_from_dict(
    value: dict[str, object], path: Path
) -> SessionParseCheckpoint:
    return SessionParseCheckpoint(
        byte_offset=int(value["byte_offset"]),
        next_record_index=int(value["next_record_index"]),
        next_candidate_index=int(value["next_candidate_index"]),
        source_device=int(value["source_device"]),
        source_inode=int(value["source_inode"]),
        head_sha256=str(value["head_sha256"]),
        boundary_sha256=str(value["boundary_sha256"]),
        session_id=str(value["session_id"]),
        state=parser_state_from_json(str(value["state_json"]), path),
    )
