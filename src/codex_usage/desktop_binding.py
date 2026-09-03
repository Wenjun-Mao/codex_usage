from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal


class DesktopProjectBindingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    mode: int


@dataclass(frozen=True, slots=True)
class DesktopBindingPlan:
    mode: Literal["not-applicable", "ready"]
    task_ids: tuple[str, ...]
    state_path: str = ""
    project_id: str = ""
    destination_path: str = ""
    source_sha256: str = ""
    source_identity: FileIdentity | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["task_ids"] = list(self.task_ids)
        return payload


ProcessProbe = Callable[[], Literal["closed", "running", "unknown"]]


def desktop_state_path(codex_home: Path) -> Path:
    return codex_home / ".codex-global-state.json"


def inspect_desktop_process() -> Literal["closed", "running", "unknown"]:
    try:
        if sys_platform() == "darwin":
            result = subprocess.run(
                ["/bin/ps", "-axo", "pid=,args="],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode != 0:
                return "unknown"
            pattern = re.compile(
                r"(?:^|/)ChatGPT\.app/Contents/MacOS/ChatGPT(?:\s|$)"
            )
            return (
                "running"
                if any(pattern.search(_without_pid(line)) for line in result.stdout.splitlines())
                else "closed"
            )
        if os.name == "nt":
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "@(Get-Process -Name ChatGPT,OpenAI.Codex "
                    "-ErrorAction SilentlyContinue).Count",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            count = int(result.stdout.strip())
            return "running" if count > 0 else "closed"
    except (OSError, subprocess.SubprocessError, ValueError):
        return "unknown"
    return "unknown"


def preflight_desktop_binding(
    codex_home: Path,
    destination: Path,
    task_ids: Iterable[str],
    *,
    process_probe: ProcessProbe = inspect_desktop_process,
) -> DesktopBindingPlan:
    selected = _canonical_task_ids(task_ids)
    state_path = desktop_state_path(codex_home)
    if not state_path.is_file():
        return DesktopBindingPlan("not-applicable", selected)
    _require_desktop_closed(process_probe)
    raw, digest, identity = _read_stable(state_path)
    state = _parse_state(raw)
    _validate_state_shape(state)
    destination_path = _canonical_path(destination)
    project_id = _matching_project_id(state, destination_path)
    _require_compatible_assignments(state, selected, project_id, destination_path)
    return DesktopBindingPlan(
        "ready",
        selected,
        state_path=str(state_path),
        project_id=project_id,
        destination_path=str(destination_path),
        source_sha256=digest,
        source_identity=identity,
    )


def bind_desktop_tasks(
    plan: DesktopBindingPlan,
    registered_task_ids: Iterable[str],
    *,
    process_probe: ProcessProbe = inspect_desktop_process,
) -> dict[str, object]:
    registered = _canonical_task_ids(registered_task_ids)
    if not set(registered).issubset(plan.task_ids):
        _fail("registration-invalid", "Binding received an unselected task ID.")
    if plan.mode == "not-applicable":
        return {"status": "not-applicable", "attempted": len(registered), "bound": 0}
    if not registered:
        return {"status": "unchanged", "attempted": 0, "bound": 0}
    if plan.source_identity is None:
        _fail("state-malformed", "Binding plan has no Desktop state identity.")

    _require_desktop_closed(process_probe)
    state_path = Path(plan.state_path)
    current, digest, identity = _read_stable(state_path)
    if digest != plan.source_sha256 or identity != plan.source_identity:
        _fail("state-changed", "Codex Desktop state changed; retry Import.")
    state = _parse_state(current)
    destination = Path(plan.destination_path)
    project_id = _matching_project_id(state, destination)
    if project_id != plan.project_id:
        _fail("project-changed", "The matching Desktop project changed; retry Import.")
    _require_compatible_assignments(
        state, registered, plan.project_id, destination
    )
    if not _apply_assignments(state, registered, plan.project_id, destination):
        return {
            "status": "unchanged",
            "attempted": len(registered),
            "bound": len(registered),
        }

    backup = state_path.with_name(
        f"{state_path.name}.codex-usage-{int(time.time() * 1000)}-{uuid.uuid4()}.bak"
    )
    temporary = state_path.with_name(
        f"{state_path.name}.codex-usage-state-{os.getpid()}-{uuid.uuid4()}.tmp"
    )
    serialized = json.dumps(state, separators=(",", ":")).encode()
    if current.endswith(b"\n"):
        serialized += b"\n"
    replaced = False
    try:
        _write_new_synced(backup, current, 0o600)
        _write_new_synced(temporary, serialized, identity.mode & 0o777)
        _require_desktop_closed(process_probe)
        latest, latest_digest, latest_identity = _read_stable(state_path)
        if latest_digest != digest or latest_identity != identity or latest != current:
            _fail("state-changed", "Codex Desktop state changed; retry Import.")
        os.replace(temporary, state_path)
        replaced = True
        _verify_assignments(plan, registered)
    except BaseException:
        temporary.unlink(missing_ok=True)
        if replaced and backup.is_file() and process_probe() == "closed":
            restore = state_path.with_name(f".{state_path.name}.{uuid.uuid4()}.restore")
            try:
                _write_new_synced(restore, backup.read_bytes(), identity.mode & 0o777)
                os.replace(restore, state_path)
            finally:
                restore.unlink(missing_ok=True)
        raise
    return {
        "status": "bound",
        "attempted": len(registered),
        "bound": len(registered),
        "backup_path": str(backup),
    }


def _verify_assignments(plan: DesktopBindingPlan, task_ids: tuple[str, ...]) -> None:
    state = _parse_state(Path(plan.state_path).read_bytes())
    assignments = _object_field(state, "thread-project-assignments", required=True)
    projectless = set(_string_array(state.get("projectless-thread-ids"), optional=True))
    outputs = _object_field(
        state, "thread-projectless-output-directories", required=False
    )
    for task_id in task_ids:
        assignment = _object(assignments.get(task_id), f"assignment {task_id}")
        if (
            assignment.get("projectKind") != "local"
            or assignment.get("projectId") != plan.project_id
            or assignment.get("pendingCoreUpdate") is not False
            or not isinstance(assignment.get("cwd"), str)
            or not _same_path(Path(str(assignment["cwd"])), Path(plan.destination_path))
            or task_id in projectless
            or task_id in outputs
        ):
            _fail("state-verification-failed", "Desktop assignment verification failed.")


def _apply_assignments(
    state: dict[str, Any],
    task_ids: tuple[str, ...],
    project_id: str,
    destination: Path,
) -> bool:
    assignments = _object_field(state, "thread-project-assignments", required=False)
    changed = False
    for task_id in task_ids:
        value = {
            "projectKind": "local",
            "projectId": project_id,
            "cwd": str(destination),
            "pendingCoreUpdate": False,
        }
        if assignments.get(task_id) != value:
            assignments[task_id] = value
            changed = True
    state["thread-project-assignments"] = assignments
    projectless = _string_array(state.get("projectless-thread-ids"), optional=True)
    retained = [task_id for task_id in projectless if task_id not in task_ids]
    if retained != projectless:
        state["projectless-thread-ids"] = retained
        changed = True
    outputs = _object_field(
        state, "thread-projectless-output-directories", required=False
    )
    for task_id in task_ids:
        if task_id in outputs:
            del outputs[task_id]
            changed = True
    if "thread-projectless-output-directories" in state:
        state["thread-projectless-output-directories"] = outputs
    return changed


def _matching_project_id(state: dict[str, Any], destination: Path) -> str:
    projects = _object_field(state, "local-projects", required=True)
    matches: set[str] = set()
    for key, raw_project in projects.items():
        project = _object(raw_project, f"local-projects.{key}")
        project_id = _text(project.get("id"), f"local-projects.{key}.id")
        if project_id != key:
            _malformed(f"local-projects.{key}.id must match its key")
        roots = _string_array(project.get("rootPaths"), optional=False)
        for root in roots:
            try:
                if _same_path(Path(root).resolve(strict=True), destination):
                    matches.add(project_id)
            except OSError:
                continue
    if not matches:
        _fail(
            "project-missing",
            "Add the destination as a Codex Desktop project, quit Desktop, and retry Import.",
        )
    if len(matches) != 1:
        _fail("project-ambiguous", "More than one Desktop project matches the destination.")
    return next(iter(matches))


def _require_compatible_assignments(
    state: dict[str, Any],
    task_ids: tuple[str, ...],
    project_id: str,
    destination: Path,
) -> None:
    assignments = _object_field(state, "thread-project-assignments", required=False)
    allowed = {"projectKind", "projectId", "cwd", "pendingCoreUpdate"}
    for task_id in task_ids:
        raw = assignments.get(task_id)
        if raw is None:
            continue
        assignment = _object(raw, f"thread-project-assignments.{task_id}")
        if set(assignment) - allowed:
            _malformed(f"thread-project-assignments.{task_id} has unknown fields")
        if (
            assignment.get("projectKind") != "local"
            or assignment.get("projectId") != project_id
            or type(assignment.get("pendingCoreUpdate")) is not bool
            or not isinstance(assignment.get("cwd"), str)
        ):
            _fail("assignment-conflict", "A selected task belongs to another project.")
        try:
            existing = Path(str(assignment["cwd"])).resolve(strict=True)
        except OSError:
            _fail("assignment-conflict", "A selected task has an unavailable project folder.")
        if not _same_path(existing, destination):
            _fail("assignment-conflict", "A selected task has a different project folder.")


def _read_stable(path: Path) -> tuple[bytes, str, FileIdentity]:
    before = _identity(path.stat())
    raw = path.read_bytes()
    after = _identity(path.stat())
    if before != after or len(raw) != after.size:
        _fail("state-changed", "Codex Desktop state changed while being inspected.")
    return raw, hashlib.sha256(raw).hexdigest(), after


def _identity(stat: os.stat_result) -> FileIdentity:
    if not stat.st_ino:
        _fail("state-identity-unavailable", "Desktop state identity is unavailable.")
    return FileIdentity(
        int(stat.st_dev),
        int(stat.st_ino),
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_mode,
    )


def _parse_state(raw: bytes) -> dict[str, Any]:
    try:
        return _object(json.loads(raw), "Desktop global state")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _malformed(f"Desktop global state is not valid JSON: {exc}")


def _validate_state_shape(state: dict[str, Any]) -> None:
    _object_field(state, "thread-project-assignments", required=False)
    _string_array(state.get("projectless-thread-ids"), optional=True)
    _object_field(state, "thread-projectless-output-directories", required=False)


def _object_field(
    state: dict[str, Any], key: str, *, required: bool
) -> dict[str, Any]:
    if key not in state and not required:
        return {}
    return _object(state.get(key), key)


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _malformed(f"{label} must be an object")
    return value


def _string_array(value: object, *, optional: bool) -> list[str]:
    if value is None and optional:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        _malformed("expected an array of strings")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _malformed(f"{label} must be a nonempty string")
    return value


def _canonical_task_ids(values: Iterable[str]) -> tuple[str, ...]:
    result = tuple(dict.fromkeys(values))
    if any(not value or value != value.strip() for value in result):
        _fail("task-id-invalid", "Desktop binding received an invalid task ID.")
    return result


def _canonical_path(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise DesktopProjectBindingError(
            "destination-invalid", "The destination folder is unavailable."
        ) from exc


def _same_path(left: Path, right: Path) -> bool:
    left_value = os.path.normpath(str(left))
    right_value = os.path.normpath(str(right))
    if os.name == "nt":
        return left_value.casefold() == right_value.casefold()
    return left_value == right_value


def _require_desktop_closed(probe: ProcessProbe) -> None:
    status = probe()
    if status == "running":
        _fail("desktop-running", "Quit Codex Desktop before importing tasks.")
    if status != "closed":
        _fail(
            "desktop-process-unknown",
            "Codex Desktop closure could not be verified; close it and retry Import.",
        )


def _write_new_synced(path: Path, raw: bytes, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _without_pid(line: str) -> str:
    return re.sub(r"^\s*\d+\s+", "", line.strip())


def sys_platform() -> str:
    import sys

    return sys.platform


def _malformed(detail: str) -> None:
    _fail("state-malformed", f"Codex Desktop state is incompatible: {detail}.")


def _fail(code: str, message: str) -> None:
    raise DesktopProjectBindingError(code, message)
