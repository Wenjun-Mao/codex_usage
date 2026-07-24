from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from time import perf_counter
from typing import Protocol

from codex_usage.discovery import default_session_dir
from codex_usage.reporting import print_json
from codex_usage.session_cache import CachedSessionData
from codex_usage.settings import get_settings
from codex_usage.sync import (
    ProjectBinding,
    ProjectResolutionRequest,
    SyncProgressEvent,
    SyncRunResult,
    load_sync_selection_inventory,
    pull_sync,
    push_sync,
    sync_status,
)
from codex_usage.sync.inventory import normalize_selected_thread_ids


class SessionDataLoader(Protocol):
    def __call__(
        self,
        session_dirs: list[Path],
        *,
        auto_transitions: bool,
    ) -> CachedSessionData: ...


class _SingleProjectKeyAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str,
        option_string: str | None = None,
    ) -> None:
        if not values.strip():
            parser.error("--project-key must not be blank.")
        if getattr(namespace, self.dest, None) is not None:
            parser.error(
                "--project-key must be provided exactly once; "
                "remove the duplicate option."
            )
        setattr(namespace, self.dest, values)


def add_sync_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--sync-dir",
        type=Path,
        required=True,
        help="Bring-your-own local sync folder.",
    )
    parser.add_argument(
        "--candidate-project-root",
        action="append",
        type=Path,
        help="Candidate local project root. Repeat as needed.",
    )
    parser.add_argument(
        "--no-auto-transitions",
        action="store_true",
        help="Disable automatic project transition inference.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON."
    )


def add_sync_execution_options(parser: argparse.ArgumentParser) -> None:
    add_sync_common_options(parser)
    parser.add_argument(
        "--thread-id",
        action="append",
        help="Technical thread id for a selected Codex task. Repeat as needed.",
    )
    parser.add_argument(
        "--project-binding",
        action="append",
        nargs=2,
        metavar=("PROJECT_KEY", "PATH"),
        help="Bind a remote project key to a local path. Repeat as needed.",
    )
    parser.add_argument(
        "--confirm-unverified-project",
        action="append",
        help="Confirm one non-Git project binding. Repeat as needed.",
    )


def add_sync_transfer_options(parser: argparse.ArgumentParser) -> None:
    add_sync_execution_options(parser)
    parser.add_argument(
        "--project-key",
        action=_SingleProjectKeyAction,
        required=True,
        help="Exact project key for this one-project transfer operation.",
    )


def handle_sync_inventory(
    args: argparse.Namespace, load_session_data: SessionDataLoader
) -> int:
    project_resolution = _project_resolution_request(args)
    data, _ = _load_sync_data(
        args,
        create_sessions=False,
        load_session_data=load_session_data,
    )
    payload = load_sync_selection_inventory(
        data,
        args.sync_dir,
        candidate_roots=project_resolution.candidate_roots,
    ).to_dict()
    if args.json:
        print_json(payload)
    else:
        _print_sync_inventory(payload)
    return 0


def handle_sync_pull(
    args: argparse.Namespace, load_session_data: SessionDataLoader
) -> int:
    project_resolution = _project_resolution_request(args)
    thread_ids = _sync_thread_ids(args)
    data, discovery_ms = _load_sync_data(
        args,
        create_sessions=True,
        load_session_data=load_session_data,
    )
    result = pull_sync(
        data=data,
        sync_dir=args.sync_dir,
        thread_ids=thread_ids,
        project_resolution=project_resolution,
        project_key=args.project_key,
        discovery_ms=discovery_ms,
        on_progress=_emit_sync_progress,
    )
    return _finish_sync_execution(args, result)


def handle_sync_push(
    args: argparse.Namespace, load_session_data: SessionDataLoader
) -> int:
    project_resolution = _project_resolution_request(args)
    thread_ids = _sync_thread_ids(args)
    data, discovery_ms = _load_sync_data(
        args,
        create_sessions=True,
        load_session_data=load_session_data,
    )
    result = push_sync(
        data=data,
        sync_dir=args.sync_dir,
        thread_ids=thread_ids,
        machine_id=args.machine_id or _default_machine_id(),
        project_key=args.project_key,
        project_resolution=project_resolution,
        discovery_ms=discovery_ms,
        on_progress=_emit_sync_progress,
    )
    return _finish_sync_execution(args, result)


def _finish_sync_execution(args: argparse.Namespace, result: SyncRunResult) -> int:
    payload = result.to_dict()
    if args.json:
        print_json(payload)
    else:
        _print_sync_run_summary(payload)
    return 0 if result.outcome == "completed" else 2


def handle_sync_status(
    args: argparse.Namespace,
    load_session_data: SessionDataLoader,
) -> int:
    project_resolution = _project_resolution_request(args)
    thread_ids = _sync_thread_ids(args)
    data, _ = _load_sync_data(
        args,
        create_sessions=False,
        load_session_data=load_session_data,
    )
    plan = sync_status(
        data=data,
        sync_dir=args.sync_dir,
        thread_ids=thread_ids,
        project_resolution=project_resolution,
    )
    payload = plan.to_dict()
    if args.json:
        print_json(payload)
    else:
        _print_sync_status_summary(payload)
    return 0


def _sync_thread_ids(args: argparse.Namespace) -> tuple[str, ...]:
    thread_ids = normalize_selected_thread_ids(args.thread_id or [])
    if not thread_ids:
        raise ValueError("Select at least one task with --thread-id for sync.")
    return thread_ids


def _project_resolution_request(
    args: argparse.Namespace,
) -> ProjectResolutionRequest:
    candidate_roots = tuple(getattr(args, "candidate_project_root", None) or ())
    confirmed_keys = {
        project_key.strip()
        for project_key in (
            getattr(args, "confirm_unverified_project", None) or ()
        )
        if project_key.strip()
    }
    bindings: list[ProjectBinding] = []
    binding_paths: dict[str, Path] = {}
    for raw_project_key, raw_path in getattr(args, "project_binding", None) or ():
        project_key = raw_project_key.strip()
        if not project_key:
            raise ValueError("Project binding key must not be blank.")
        if not raw_path.strip():
            raise ValueError(f"Project binding path for {project_key!r} must not be blank.")
        path = Path(raw_path)
        previous_path = binding_paths.get(project_key)
        if previous_path is not None:
            if previous_path != path:
                raise ValueError(f"Conflicting project bindings for {project_key!r}.")
            continue
        binding_paths[project_key] = path
        bindings.append(
            ProjectBinding(
                project_key,
                path,
                project_key in confirmed_keys,
            )
        )
    return ProjectResolutionRequest(candidate_roots, tuple(bindings))


def _load_sync_data(
    args: argparse.Namespace,
    *,
    create_sessions: bool,
    load_session_data: SessionDataLoader,
) -> tuple[CachedSessionData, int]:
    session_dirs = _sync_session_dirs(create=create_sessions)
    settings = get_settings()
    _emit_sync_progress(SyncProgressEvent("sync_progress", "scanning"))
    started = perf_counter()
    data = load_session_data(
        session_dirs,
        auto_transitions=settings.auto_project_transitions
        and not args.no_auto_transitions,
    )
    discovery_ms = max(0, int((perf_counter() - started) * 1000))
    return data, discovery_ms


def _emit_sync_progress(event: SyncProgressEvent) -> None:
    print(
        json.dumps(event.to_dict(), separators=(",", ":")),
        file=sys.stderr,
        flush=True,
    )


def _print_sync_inventory(payload: dict[str, object]) -> None:
    projects = payload["projects"]
    issues = payload["issues"]
    assert isinstance(projects, list) and isinstance(issues, list)
    task_count = sum(
        len(project.get("tasks", []))
        for project in projects
        if isinstance(project, dict) and isinstance(project.get("tasks"), list)
    )
    print(
        f"Sync inventory: {len(projects)} projects, "
        f"{task_count} tasks, {len(issues)} issues."
    )


def _print_sync_run_summary(payload: dict[str, object]) -> None:
    counts = payload["counts"]
    assert isinstance(counts, dict)
    print(
        f"Sync {payload.get('outcome', 'issue')}: "
        f"{counts.get('pulled', 0)} pulled, {counts.get('pushed', 0)} pushed, "
        f"{counts.get('unchanged', 0)} unchanged, "
        f"{counts.get('conflicts', 0)} conflicts, {counts.get('issues', 0)} issues."
    )


def _print_sync_status_summary(payload: dict[str, object]) -> None:
    threads = payload["threads"]
    issues = payload["issues"]
    assert isinstance(threads, list) and isinstance(issues, list)
    actions = [item.get("action") for item in threads if isinstance(item, dict)]
    print(
        f"Sync status: {len(threads)} selected, {actions.count('pull')} pull, "
        f"{actions.count('push')} push, {actions.count('conflict')} conflicts, "
        f"{len(issues)} issues."
    )


def _sync_session_dirs(*, create: bool) -> list[Path]:
    path = default_session_dir().expanduser()
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return [path]


def _default_machine_id() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown-machine"
