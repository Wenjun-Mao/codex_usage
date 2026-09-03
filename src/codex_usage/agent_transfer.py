from __future__ import annotations

import socket
from pathlib import Path
from time import perf_counter
from typing import Literal

from codex_usage.codex_registration import register_codex_tasks
from codex_usage.desktop_binding import (
    DesktopBindingPlan,
    bind_desktop_tasks,
    preflight_desktop_binding,
)
from codex_usage.sync import (
    ProjectBinding,
    ProjectResolutionRequest,
    load_local_transfer_probe,
    load_sync_selection_inventory,
    pull_sync,
    push_sync,
    sync_status,
)
from codex_usage.sync.inventory import normalize_selected_thread_ids


TransferOperation = Literal["import", "export", "status"]


def task_transfer_inventory(
    codex_home: Path,
    sync_dir: Path,
    *,
    candidate_roots: list[Path] | None = None,
) -> dict[str, object]:
    probe = load_local_transfer_probe([codex_home / "sessions"])
    return load_sync_selection_inventory(
        probe,
        sync_dir,
        candidate_roots=tuple(candidate_roots or ()),
    ).to_dict()


def execute_task_transfer(
    codex_home: Path,
    operation: TransferOperation,
    payload: dict[str, object],
) -> dict[str, object]:
    sync_dir = _required_path(payload, "sync_dir")
    task_ids = normalize_selected_thread_ids(_string_list(payload, "task_ids"))
    if not task_ids:
        raise ValueError("Select at least one task.")
    project_key = _required_text(payload, "project_key")
    candidate_roots = tuple(
        Path(value).expanduser() for value in _string_list(payload, "candidate_roots")
    )
    destination = _optional_path(payload.get("destination_path"))
    resolution = _resolution(payload, project_key, destination, candidate_roots)
    probe_started = perf_counter()
    probe = load_local_transfer_probe([codex_home / "sessions"])
    discovery_ms = max(0, int((perf_counter() - probe_started) * 1000))

    if operation == "status":
        return {
            "operation": operation,
            "result": sync_status(
                local=probe.inventory,
                sync_dir=sync_dir,
                thread_ids=task_ids,
                project_resolution=resolution,
            ).to_dict(),
        }
    binding_plan: DesktopBindingPlan | None = None
    if operation == "import":
        if destination is None:
            raise ValueError("destination_path is required for Import")
        binding_plan = preflight_desktop_binding(
            codex_home, destination, task_ids
        )
        result = pull_sync(
            local=probe.inventory,
            sync_dir=sync_dir,
            thread_ids=task_ids,
            project_resolution=resolution,
            project_key=project_key,
            discovery_ms=discovery_ms,
        )
        integration = _integrate_import(
            result, task_ids, binding_plan, codex_home=codex_home
        )
    elif operation == "export":
        result = push_sync(
            local=probe.inventory,
            sync_dir=sync_dir,
            thread_ids=task_ids,
            project_key=project_key,
            project_resolution=resolution,
            machine_id=_machine_id(),
            discovery_ms=discovery_ms,
        )
        integration = {}
    else:
        raise ValueError(f"unsupported Task Transfer operation: {operation}")
    return {
        "operation": operation,
        "result": result.to_dict(),
        "integration": integration,
    }


def _integrate_import(
    result,
    selected: tuple[str, ...],
    plan: DesktopBindingPlan,
    *,
    codex_home: Path,
) -> dict[str, object]:
    certified = _certified_import_task_ids(result, selected)
    if not certified:
        return {}
    registration = register_codex_tasks(certified, codex_home=codex_home)
    binding = bind_desktop_tasks(plan, registration.registered_task_ids)
    return {
        "registration": registration.to_dict(),
        "binding": binding,
    }


def _certified_import_task_ids(result, selected: tuple[str, ...]) -> tuple[str, ...]:
    if result.outcome not in {"completed", "issue"}:
        return ()
    selected_set = set(selected)
    pulled = tuple(result.pulled)
    if (
        result.counts.pulled != len(pulled)
        or len(set(pulled)) != len(pulled)
        or any(task_id not in selected_set for task_id in pulled)
    ):
        return ()
    return selected if result.outcome == "completed" else pulled


def _resolution(
    payload: dict[str, object],
    project_key: str,
    destination: Path | None,
    candidate_roots: tuple[Path, ...],
) -> ProjectResolutionRequest:
    bindings: tuple[ProjectBinding, ...] = ()
    if destination is not None:
        bindings = (
            ProjectBinding(
                project_key,
                destination,
                bool(payload.get("confirm_unverified_project", False)),
            ),
        )
    return ProjectResolutionRequest(candidate_roots, bindings)


def _required_path(payload: dict[str, object], key: str) -> Path:
    value = _required_text(payload, key)
    path = Path(value).expanduser()
    if not path.is_dir():
        raise ValueError(f"{key} is not an available folder: {path}")
    return path


def _optional_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"destination folder is unavailable: {path}")
    return path


def _required_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _string_list(payload: dict[str, object], key: str) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be an array of strings")
    return value


def _machine_id() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown-machine"
