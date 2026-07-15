from __future__ import annotations

import json
from pathlib import Path

from codex_usage.project_identity import normalize_project_key
from codex_usage.session_files import codex_home_from_session_dir
from codex_usage.sync.io import read_json_object
from codex_usage.sync.models import (
    LocalInventory,
    RemoteThreadEntry,
    SyncIssue,
)
from codex_usage.threads import ThreadInfo


_SAVED_ROOTS_KEY = "electron-saved-workspace-roots"


def discover_project_roots(
    session_dirs: tuple[Path, ...],
) -> dict[str, tuple[Path, ...]]:
    grouped: dict[str, list[Path]] = {}
    seen_targets: set[Path] = set()
    for session_dir in session_dirs:
        state_path = (
            codex_home_from_session_dir(session_dir) / ".codex-global-state.json"
        )
        for root in _saved_roots(state_path):
            saved_root = root.expanduser().absolute()
            resolved_target = saved_root.resolve(strict=False)
            if resolved_target in seen_targets or not saved_root.is_dir():
                continue
            seen_targets.add(resolved_target)
            project_key = normalize_project_key(str(saved_root))
            if project_key:
                # Codex groups tasks by the saved path spelling, which can differ
                # from the filesystem-resolved target on macOS and symlinked roots.
                grouped.setdefault(project_key, []).append(saved_root)
    return {
        key: tuple(sorted(paths, key=lambda path: str(path).casefold()))
        for key, paths in grouped.items()
    }


def resolve_local_project_root(
    local: LocalInventory,
    local_thread: ThreadInfo | None,
    remote_entry: RemoteThreadEntry,
) -> tuple[Path | None, SyncIssue | None]:
    remote_identities = {
        remote_entry.project_key,
        *remote_entry.project_aliases,
    }
    if local_thread is not None and _same_project(local_thread, remote_identities):
        current = _native_absolute_path(local_thread.cwd)
        if current is not None:
            return current, None

    candidates = {
        path for key in remote_identities for path in local.project_roots.get(key, ())
    }
    if len(candidates) == 1:
        return next(iter(candidates)), None
    if not candidates:
        return None, SyncIssue(
            "missing_local_project",
            (
                f"No saved local project matches task {remote_entry.thread_id!r}. "
                "Add the project to Codex on this computer, then Pull Tasks again."
            ),
            remote_entry.thread_id,
        )
    roots = ", ".join(sorted(str(path) for path in candidates))
    return None, SyncIssue(
        "ambiguous_local_project",
        (
            f"More than one saved local project matches task {remote_entry.thread_id!r}: "
            f"{roots}"
        ),
        remote_entry.thread_id,
    )


def cwd_matches_root(cwd: str, root: Path) -> bool:
    current = _native_absolute_path(cwd)
    return current is not None and current == root.resolve(strict=False)


def _same_project(thread: ThreadInfo, remote_identities: set[str]) -> bool:
    return bool(
        {thread.project_key, *thread.project_aliases}.intersection(remote_identities)
    )


def _native_absolute_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path.resolve(strict=False) if path.is_absolute() else None


def _saved_roots(state_path: Path) -> tuple[Path, ...]:
    try:
        state = read_json_object(state_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return ()
    if state is None:
        return ()
    values = state.get(_SAVED_ROOTS_KEY)
    if not isinstance(values, list):
        return ()
    return tuple(Path(value) for value in values if isinstance(value, str) and value)
