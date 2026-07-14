from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from time import perf_counter
from typing import Protocol

from codex_usage.discovery import default_session_dir
from codex_usage.project_identity import normalize_project_key
from codex_usage.reporting import print_json
from codex_usage.session_cache import CachedSessionData
from codex_usage.settings import get_settings
from codex_usage.sync import (
    SyncProgressEvent,
    load_sync_selection_inventory,
    run_sync,
    sync_status,
)


class SessionDataLoader(Protocol):
    def __call__(
        self,
        session_dirs: list[Path],
        *,
        auto_transitions: bool,
    ) -> CachedSessionData: ...


def add_sync_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--sync-dir",
        type=Path,
        required=True,
        help="Bring-your-own local sync folder.",
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
        "--project-key", action="append", help="Project key to sync. Repeat as needed."
    )
    parser.add_argument(
        "--thread-id",
        action="append",
        help="Technical thread id for a selected Codex task. Repeat as needed.",
    )


def handle_sync_inventory(
    args: argparse.Namespace, load_session_data: SessionDataLoader
) -> int:
    data, _ = _load_sync_data(
        args,
        create_sessions=False,
        load_session_data=load_session_data,
    )
    payload = load_sync_selection_inventory(data, args.sync_dir).to_dict()
    if args.json:
        print_json(payload)
    else:
        _print_sync_inventory(payload)
    return 0


def handle_sync_run(
    args: argparse.Namespace, load_session_data: SessionDataLoader
) -> int:
    project_keys, thread_ids = _sync_selectors(args)
    data, discovery_ms = _load_sync_data(
        args,
        create_sessions=True,
        load_session_data=load_session_data,
    )
    result = run_sync(
        data=data,
        sync_dir=args.sync_dir,
        project_keys=project_keys,
        thread_ids=thread_ids,
        machine_id=args.machine_id or _default_machine_id(),
        discovery_ms=discovery_ms,
        on_progress=_emit_sync_progress,
    )
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
    project_keys, thread_ids = _sync_selectors(args)
    data, _ = _load_sync_data(
        args,
        create_sessions=False,
        load_session_data=load_session_data,
    )
    plan = sync_status(
        data=data,
        sync_dir=args.sync_dir,
        project_keys=project_keys,
        thread_ids=thread_ids,
    )
    payload = plan.to_dict()
    if args.json:
        print_json(payload)
    else:
        _print_sync_status_summary(payload)
    return 0


def normalize_thread_ids(values: list[str] | None) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        thread_id = value.strip()
        if not thread_id or thread_id in seen:
            continue
        selected.append(thread_id)
        seen.add(thread_id)
    return selected


def _sync_selectors(args: argparse.Namespace) -> tuple[list[str], list[str]]:
    project_keys = _normalize_project_keys(args.project_key)
    thread_ids = normalize_thread_ids(args.thread_id)
    if not project_keys and not thread_ids:
        raise ValueError("Select at least one project key or thread id for sync.")
    return project_keys, thread_ids


def _normalize_project_keys(values: list[str] | None) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        key = normalize_project_key(value)
        if key and key not in seen:
            selected.append(key)
            seen.add(key)
    return selected


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
