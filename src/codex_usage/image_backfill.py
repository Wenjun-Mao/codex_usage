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
IMAGE_BACKFILL_CAPTURE_BYTES = 64 * 1024 * 1024
IMAGE_BACKFILL_SLICE_COUNT = 4
IMAGE_BACKFILL_SLICE_BYTES = IMAGE_BACKFILL_CAPTURE_BYTES // IMAGE_BACKFILL_SLICE_COUNT
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


@dataclass(frozen=True, slots=True)
class _ArtifactTask:
    count: int
    newest_mtime_ns: int


def run_image_backfill(
    codex_home: Path,
    ledger_path: Path,
) -> ImageBackfillResult:
    """Use at most four parser slices for one capture request.

    A slice keeps its existing 16 MiB checkpoint contract.  Four slices make
    historical recovery useful under the normal 64 MiB capture budget without
    allowing a single request to turn into an unbounded rescan.
    """
    changed = False
    result: ImageBackfillResult | None = None
    for _ in range(IMAGE_BACKFILL_SLICE_COUNT):
        result = run_image_backfill_slice(codex_home, ledger_path)
        changed = changed or result.changed
        if result.pending_tasks == 0:
            break
    if result is None:
        # IMAGE_BACKFILL_SLICE_COUNT is a module invariant, but retain a total
        # result if a future edit accidentally makes it zero.
        return ImageBackfillResult(False, "complete", 0, 0, 0, 0, 0)
    return ImageBackfillResult(
        changed,
        result.status,
        result.artifacts_total,
        result.tasks_total,
        result.tasks_completed,
        result.tasks_unavailable,
        result.pending_tasks,
    )


def run_image_backfill_slice(
    codex_home: Path,
    ledger_path: Path,
) -> ImageBackfillResult:
    """Read one exact owning rollout slice, skipping unavailable candidates."""
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
    last_served = _service_orders(state.get("last_served"), known_tasks)
    last_served = {
        task_id: order
        for task_id, order in last_served.items()
        if task_id not in completed and task_id not in unavailable
    }
    next_service_order = max(
        _service_order(state.get("next_service_order")),
        *(last_served.values() or (0,)),
    )
    changed = False
    parsed = None
    parsed_task_id = ""
    parsed_path: Path | None = None
    # Discovering that a candidate cannot be safely attributed is not parser
    # work.  Keep checking candidates until one exact owner can consume the
    # single parser slice, so a missing rollout cannot starve valid history.
    while True:
        candidates = known_tasks - completed - set(unavailable)
        if not candidates:
            break
        changed = True
        task_id = _select_next_task(candidates, task_artifacts, last_served)
        if not _has_valid_artifact(codex_home / "generated_images" / task_id):
            unavailable[task_id] = "invalid_artifact"
            continue
        owning = _owning_rollouts(codex_home, task_id)
        if len(owning) != 1:
            unavailable[task_id] = "missing" if not owning else "ambiguous"
            continue

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
        except (KeyError, OSError, TypeError, ValueError) as error:
            # An append checkpoint is validated by the parser before it is
            # trusted.  Marking a changed owner unavailable is safer than
            # replaying past its guarded boundary.
            unavailable[task_id] = type(error).__name__
            checkpoints.pop(task_id, None)
        else:
            next_service_order += 1
            last_served[task_id] = next_service_order
            parsed_task_id = task_id
            parsed_path = path
            if parsed.checkpoint.byte_offset >= path.stat().st_size:
                completed.add(task_id)
                checkpoints.pop(task_id, None)
                last_served.pop(task_id, None)
            else:
                checkpoints[task_id] = _checkpoint_to_dict(parsed.checkpoint)
            break

    pending = known_tasks - completed - set(unavailable)
    status = "partial" if unavailable else "pending" if pending else "complete"
    stored = {
        "version": 1,
        "status": status,
        "artifacts_total": sum(task.count for task in task_artifacts.values()),
        "tasks_total": len(known_tasks),
        "completed": sorted(completed),
        "unavailable": dict(sorted(unavailable.items())),
        "checkpoints": checkpoints,
        "last_served": dict(sorted(last_served.items())),
        "next_service_order": next_service_order,
    }
    with sqlite3.connect(ledger_path) as connection:
        if parsed is not None and parsed_path is not None:
            insert_image_operations(
                connection,
                _file_key_for_path(connection, parsed_task_id, parsed_path),
                parsed.image_operations,
            )
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


def _artifact_inventory(root: Path) -> dict[str, _ArtifactTask]:
    if not root.is_dir():
        return {}
    inventory: dict[str, _ArtifactTask] = {}
    for directory in sorted(root.iterdir(), key=lambda item: item.name):
        if not directory.is_dir() or not _TASK_ID.fullmatch(directory.name):
            continue
        artifacts = []
        for path in directory.iterdir():
            if not path.is_file() or not _ARTIFACT_NAME.fullmatch(path.name):
                continue
            try:
                artifacts.append(path.stat().st_mtime_ns)
            except OSError:
                continue
        if not artifacts:
            continue
        inventory[directory.name] = _ArtifactTask(len(artifacts), max(artifacts))
    return inventory


def _has_valid_artifact(directory: Path) -> bool:
    """Use one bounded header probe before admitting an owning rollout read."""
    try:
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if path.is_file() and _ARTIFACT_NAME.fullmatch(path.name):
                if inspect_generated_artifact(directory, path.name).width is not None:
                    return True
    except OSError:
        return False
    return False


def _owning_rollouts(codex_home: Path, task_id: str) -> list[Path]:
    matches: list[Path] = []
    for root_name in ("sessions", "archived_sessions"):
        root = codex_home / root_name
        if root.is_dir():
            matches.extend(root.rglob(f"*{task_id}*.jsonl"))
    return sorted({path.resolve() for path in matches})


def _file_key_for_path(
    connection: sqlite3.Connection, task_id: str, path: Path
) -> str:
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


def _service_orders(value: object, known_tasks: set[str]) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        task_id: order
        for task_id, raw_order in value.items()
        if task_id in known_tasks
        and (order := _service_order(raw_order)) > 0
    }


def _service_order(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _select_next_task(
    candidates: set[str],
    task_artifacts: dict[str, _ArtifactTask],
    last_served: dict[str, int],
) -> str:
    """Prefer newly discovered recent artifacts, then rotate saved owners."""
    unserved = candidates - set(last_served)
    if unserved:
        return max(
            unserved,
            key=lambda task_id: (task_artifacts[task_id].newest_mtime_ns, task_id),
        )
    return min(
        candidates,
        key=lambda task_id: (
            last_served[task_id],
            -task_artifacts[task_id].newest_mtime_ns,
            task_id,
        ),
    )


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
