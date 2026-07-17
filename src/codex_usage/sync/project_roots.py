from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath

from codex_usage.project_identity import (
    is_git_project_key,
    normalize_declared_project_key,
    normalize_project_key,
)
from codex_usage.session_files import codex_home_from_session_dir
from codex_usage.sync.io import read_json_object
from codex_usage.sync.models import (
    LocalInventory,
    ProjectBinding,
    ProjectDestination,
    ProjectResolutionRequest,
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
    request: ProjectResolutionRequest,
) -> tuple[Path | None, SyncIssue | None]:
    if local_thread is not None:
        current = _native_absolute_path(local_thread.cwd)
        if current is None:
            return None, _invalid_existing_project_path(
                local_thread.cwd,
                remote_entry.thread_id,
            )
        if not current.exists():
            return None, SyncIssue(
                "existing_project_path_missing",
                f"Existing task project path does not exist: {current}",
                remote_entry.thread_id,
            )
        if not current.is_dir():
            return None, SyncIssue(
                "existing_project_path_not_directory",
                f"Existing task project path is not a directory: {current}",
                remote_entry.thread_id,
            )
        return current, None

    binding, binding_issue = _binding_for_project(remote_entry, request.bindings)
    if binding_issue is not None:
        return None, binding_issue
    if binding is not None:
        return _validated_binding_root(remote_entry, binding)

    destination = destination_for_project(local, remote_entry, request)
    if len(destination.candidate_roots) == 1:
        return destination.candidate_roots[0], None
    if not destination.candidate_roots:
        return None, _missing_project_issue(remote_entry)

    roots = ", ".join(str(path) for path in destination.candidate_roots)
    return None, SyncIssue(
        "ambiguous_local_project",
        (
            f"More than one local project matches task {remote_entry.thread_id!r}: "
            f"{roots}"
        ),
        remote_entry.thread_id,
    )


def destination_for_project(
    local: LocalInventory,
    remote_entry: RemoteThreadEntry,
    request: ProjectResolutionRequest,
) -> ProjectDestination:
    identity_kind = "git" if is_git_project_key(remote_entry.project_key) else "path"
    destination_identities = _destination_identities(remote_entry)
    candidate_paths = [
        *(
            Path(thread.cwd)
            for thread in local.threads.values()
            if thread.cwd and Path(thread.cwd).expanduser().is_absolute()
        ),
        *request.candidate_roots,
        *(
            root
            for roots in local.project_roots.values()
            for root in roots
        ),
    ]
    matching = [
        path.expanduser().absolute()
        for path in candidate_paths
        if path.expanduser().is_dir()
        and normalize_project_key(str(path.expanduser().absolute()))
        in destination_identities
    ]
    return ProjectDestination(
        identity_kind=identity_kind,
        candidate_roots=_deduplicate_targets(matching),
    )


def _binding_for_project(
    remote_entry: RemoteThreadEntry,
    bindings: tuple[ProjectBinding, ...],
) -> tuple[ProjectBinding | None, SyncIssue | None]:
    remote_identities = _destination_identities(remote_entry)
    matches = [
        binding
        for binding in bindings
        if normalize_declared_project_key(binding.project_key) in remote_identities
    ]
    if len(matches) > 1:
        return None, SyncIssue(
            "duplicate_project_binding",
            f"More than one binding was provided for project {remote_entry.project_key!r}.",
            remote_entry.thread_id,
        )
    return (matches[0], None) if matches else (None, None)


def _validated_binding_root(
    remote_entry: RemoteThreadEntry,
    binding: ProjectBinding,
) -> tuple[Path | None, SyncIssue | None]:
    root = binding.path.expanduser().absolute()
    if not root.exists():
        return None, SyncIssue(
            "project_binding_path_missing",
            f"Project binding path does not exist: {root}",
            remote_entry.thread_id,
        )
    if not root.is_dir():
        return None, SyncIssue(
            "project_binding_path_not_directory",
            f"Project binding path is not a directory: {root}",
            remote_entry.thread_id,
        )

    actual_identity = normalize_project_key(str(root))
    destination_identities = _destination_identities(remote_entry)
    if is_git_project_key(remote_entry.project_key):
        if actual_identity not in destination_identities:
            return None, SyncIssue(
                "project_binding_identity_mismatch",
                (
                    f"Project binding for {remote_entry.project_key!r} points to "
                    f"{actual_identity!r}."
                ),
                remote_entry.thread_id,
            )
    elif (
        actual_identity not in destination_identities
        and not binding.confirmed_unverified
    ):
        return None, SyncIssue(
            "unverified_project_binding_confirmation_required",
            (
                f"Project binding for {remote_entry.project_key!r} cannot be verified "
                "with Git identity and requires explicit confirmation."
            ),
            remote_entry.thread_id,
        )
    return root, None


def _missing_project_issue(remote_entry: RemoteThreadEntry) -> SyncIssue:
    return SyncIssue(
        "missing_local_project",
        (
            f"No local project matches task {remote_entry.thread_id!r}. Open the "
            "project in VS Code, Add the project to Codex, or provide an explicit "
            "binding before pulling again."
        ),
        remote_entry.thread_id,
    )


def _deduplicate_targets(paths: list[Path]) -> tuple[Path, ...]:
    roots: list[Path] = []
    seen_targets: set[Path] = set()
    for path in paths:
        target = path.resolve(strict=False)
        if target in seen_targets:
            continue
        seen_targets.add(target)
        roots.append(path)
    return tuple(roots)


def _declared_path_identities(remote_entry: RemoteThreadEntry) -> set[str]:
    return {
        normalized
        for value in (remote_entry.project_key, *remote_entry.project_aliases)
        if (normalized := normalize_declared_project_key(value))
        and not is_git_project_key(normalized)
    }


def _destination_identities(remote_entry: RemoteThreadEntry) -> set[str]:
    if not is_git_project_key(remote_entry.project_key):
        return _declared_path_identities(remote_entry)
    primary = normalize_declared_project_key(remote_entry.project_key)
    return {primary} if primary else set()


def cwd_matches_root(cwd: str, root: Path) -> bool:
    current = _native_absolute_path(cwd)
    return (
        current is not None
        and current.resolve(strict=False) == root.resolve(strict=False)
    )


def _native_absolute_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else None


def _invalid_existing_project_path(value: str, thread_id: str) -> SyncIssue:
    if not value.strip():
        return SyncIssue(
            "existing_project_path_blank",
            "Existing task project path is blank.",
            thread_id,
        )
    if PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute():
        return SyncIssue(
            "existing_project_path_not_native",
            f"Existing task project path is not native on this computer: {value}",
            thread_id,
        )
    return SyncIssue(
        "existing_project_path_not_absolute",
        f"Existing task project path is not absolute: {value}",
        thread_id,
    )


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
