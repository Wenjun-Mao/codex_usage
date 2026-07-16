from __future__ import annotations

from pathlib import Path

import pytest

from codex_usage.sync.models import (
    LocalInventory,
    ProjectBinding,
    ProjectResolutionRequest,
    RemoteThreadEntry,
)
from codex_usage.sync.project_roots import resolve_local_project_root
from codex_usage.threads import ThreadInfo


THREAD_ID = "task-1"


def _git_checkout(path: Path, origin: str) -> Path:
    path.mkdir(parents=True)
    git_dir = path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = {origin}\n',
        encoding="utf-8",
    )
    return path


def _remote_entry(
    project_key: str,
    *,
    aliases: tuple[str, ...] = (),
) -> RemoteThreadEntry:
    return RemoteThreadEntry(
        thread_id=THREAD_ID,
        file=f"tasks/{THREAD_ID}.jsonl",
        source_relative_path=f"synced/{THREAD_ID}.jsonl",
        index_entry={"id": THREAD_ID},
        project_key=project_key,
        project_label="project",
        project_aliases=aliases,
        sha256="remote-sha",
        size_bytes=100,
        session_updated_at="2026-07-16T12:00:00Z",
        exported_at="2026-07-16T12:00:00Z",
        source_machine_id="source",
    )


def _local_thread(cwd: Path, project_key: str) -> ThreadInfo:
    return ThreadInfo(
        thread_id=THREAD_ID,
        title="Local task",
        updated_at="2026-07-16T12:00:00Z",
        session_path=Path("sessions") / f"{THREAD_ID}.jsonl",
        project_key=project_key,
        project_label="project",
        project_aliases=(),
        total_tokens=0,
        session_bytes=100,
        estimated_sync_bytes=4196,
        cwd=str(cwd),
    )


def _local_inventory(thread: ThreadInfo | None = None) -> LocalInventory:
    threads = {} if thread is None else {thread.thread_id: thread}
    return LocalInventory(
        session_dirs=(Path("sessions"),),
        threads=threads,
        index_entries={},
        discovered_count=len(threads),
        project_roots={},
    )


def test_remote_path_alias_cannot_authorize_wrong_origin_candidate(
    tmp_path: Path,
) -> None:
    wrong_checkout = _git_checkout(
        tmp_path / "wrong-candidate",
        "git@github.com:example/wrong.git",
    )
    remote_entry = _remote_entry(
        "https://github.com/example/right.git",
        aliases=(str(wrong_checkout),),
    )

    root, issue = resolve_local_project_root(
        _local_inventory(),
        None,
        remote_entry,
        ProjectResolutionRequest(candidate_roots=(wrong_checkout,)),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "missing_local_project"


def test_remote_path_alias_cannot_authorize_wrong_origin_binding(
    tmp_path: Path,
) -> None:
    wrong_checkout = _git_checkout(
        tmp_path / "wrong-binding",
        "git@github.com:example/wrong.git",
    )
    remote_entry = _remote_entry(
        "https://github.com/example/right.git",
        aliases=(str(wrong_checkout),),
    )

    root, issue = resolve_local_project_root(
        _local_inventory(),
        None,
        remote_entry,
        ProjectResolutionRequest(
            bindings=(
                ProjectBinding(
                    project_key=remote_entry.project_key,
                    path=wrong_checkout,
                ),
            ),
        ),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "project_binding_identity_mismatch"


def test_git_shaped_alias_cannot_authorize_non_git_candidate(
    tmp_path: Path,
) -> None:
    checkout = _git_checkout(
        tmp_path / "alias-candidate",
        "git@github.com:example/alias-only.git",
    )
    remote_entry = _remote_entry(
        "c:/remote-machine/project",
        aliases=("https://github.com/example/alias-only.git",),
    )

    root, issue = resolve_local_project_root(
        _local_inventory(),
        None,
        remote_entry,
        ProjectResolutionRequest(candidate_roots=(checkout,)),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "missing_local_project"


def test_git_shaped_alias_cannot_bypass_non_git_binding_confirmation(
    tmp_path: Path,
) -> None:
    checkout = _git_checkout(
        tmp_path / "alias-binding",
        "git@github.com:example/alias-only.git",
    )
    remote_entry = _remote_entry(
        "c:/remote-machine/project",
        aliases=("https://github.com/example/alias-only.git",),
    )

    root, issue = resolve_local_project_root(
        _local_inventory(),
        None,
        remote_entry,
        ProjectResolutionRequest(
            bindings=(ProjectBinding(remote_entry.project_key, checkout),),
        ),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "unverified_project_binding_confirmation_required"


def test_existing_counterpart_precedes_non_overlapping_project_metadata_and_binding(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "native-local-root"
    bound_root = tmp_path / "bound-root"
    local_root.mkdir()
    bound_root.mkdir()
    local_thread = _local_thread(local_root, "d:/local-machine/project")
    remote_entry = _remote_entry("c:/remote-machine/project")

    root, issue = resolve_local_project_root(
        _local_inventory(local_thread),
        local_thread,
        remote_entry,
        ProjectResolutionRequest(
            bindings=(
                ProjectBinding(
                    project_key=remote_entry.project_key,
                    path=bound_root,
                    confirmed_unverified=True,
                ),
            ),
        ),
    )

    assert root == local_root
    assert issue is None


def test_existing_counterpart_preserves_exact_symlink_cwd_spelling(
    tmp_path: Path,
) -> None:
    actual_root = tmp_path / "actual-root"
    linked_root = tmp_path / "linked-root"
    actual_root.mkdir()
    try:
        linked_root.symlink_to(actual_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    local_thread = _local_thread(linked_root, "shared-project-key")

    root, issue = resolve_local_project_root(
        _local_inventory(local_thread),
        local_thread,
        _remote_entry("shared-project-key"),
        ProjectResolutionRequest(),
    )

    assert root == linked_root
    assert str(root) == str(linked_root)
    assert issue is None
