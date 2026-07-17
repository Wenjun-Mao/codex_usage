from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_usage.sync.models import (
    LocalInventory,
    ProjectBinding,
    ProjectResolutionRequest,
    RemoteThreadEntry,
)
from codex_usage.sync.project_roots import (
    discover_project_roots,
    resolve_local_project_root,
)
from codex_usage.threads import ThreadInfo


def _git_checkout(path: Path, origin: str) -> Path:
    path.mkdir(parents=True)
    git_dir = path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = {origin}\n',
        encoding="utf-8",
    )
    return path


def _empty_local(tmp_path: Path) -> LocalInventory:
    return LocalInventory(
        session_dirs=(tmp_path / "codex" / "sessions",),
        threads={},
        index_entries={},
        discovered_count=0,
        project_roots={},
    )


def _remote_entry(
    project_key: str,
    *,
    aliases: tuple[str, ...] = (),
) -> RemoteThreadEntry:
    return RemoteThreadEntry(
        thread_id="task-1",
        file="tasks/task-1.jsonl",
        source_relative_path="synced/task-1.jsonl",
        index_entry={"id": "task-1"},
        project_key=project_key,
        project_label="project",
        project_aliases=aliases,
        sha256="remote-sha",
        size_bytes=100,
        session_updated_at="2026-07-16T12:00:00Z",
        exported_at="2026-07-16T12:00:00Z",
        source_machine_id="source",
    )


def _local_thread(thread_id: str, root: Path, project_key: str) -> ThreadInfo:
    return ThreadInfo(
        thread_id=thread_id,
        title=thread_id,
        updated_at="2026-07-16T12:00:00Z",
        session_path=Path("sessions") / f"{thread_id}.jsonl",
        project_key=project_key,
        project_label="project",
        project_aliases=(),
        total_tokens=0,
        session_bytes=100,
        estimated_sync_bytes=4196,
        cwd=str(root),
    )


def _local_inventory(*threads: ThreadInfo) -> LocalInventory:
    return LocalInventory(
        session_dirs=(Path("sessions"),),
        threads={thread.thread_id: thread for thread in threads},
        index_entries={},
        discovered_count=len(threads),
        project_roots={},
    )


def test_discover_project_roots_preserves_codex_saved_path_spelling(tmp_path):
    actual_project = tmp_path / "actual-project"
    actual_project.mkdir()
    git_dir = actual_project / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/example/project.git\n',
        encoding="utf-8",
    )
    saved_project = tmp_path / "saved-project"
    saved_project.symlink_to(actual_project, target_is_directory=True)

    codex_home = tmp_path / "codex-home"
    sessions_dir = codex_home / "sessions"
    sessions_dir.mkdir(parents=True)
    (codex_home / ".codex-global-state.json").write_text(
        json.dumps({"electron-saved-workspace-roots": [str(saved_project)]}),
        encoding="utf-8",
    )

    roots = discover_project_roots((sessions_dir,))

    assert roots == {
        "https://github.com/example/project": (saved_project,),
    }


def test_workspace_candidate_resolves_without_desktop_global_state(
    tmp_path: Path,
) -> None:
    checkout = _git_checkout(
        tmp_path / "checkout",
        "https://github.com/example/project.git",
    )
    request = ProjectResolutionRequest(candidate_roots=(checkout,))

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        _remote_entry("https://github.com/example/project"),
        request,
    )

    assert root == checkout.absolute()
    assert issue is None
    assert not (tmp_path / "codex" / ".codex-global-state.json").exists()


def test_wrong_git_origin_is_rejected(tmp_path: Path) -> None:
    checkout = _git_checkout(
        tmp_path / "wrong",
        "https://github.com/example/other.git",
    )
    request = ProjectResolutionRequest(
        bindings=(
            ProjectBinding("https://github.com/example/project", checkout),
        )
    )

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        _remote_entry("https://github.com/example/project"),
        request,
    )

    assert root is None
    assert issue is not None
    assert issue.code == "project_binding_identity_mismatch"
    assert "https://github.com/example/project" in issue.message
    assert "https://github.com/example/other" in issue.message


def test_wrong_git_binding_does_not_fall_back_to_matching_candidate(
    tmp_path: Path,
) -> None:
    matching = _git_checkout(
        tmp_path / "matching",
        "https://github.com/example/project.git",
    )
    wrong = _git_checkout(
        tmp_path / "wrong",
        "https://github.com/example/other.git",
    )

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        _remote_entry("https://github.com/example/project"),
        ProjectResolutionRequest(
            candidate_roots=(matching,),
            bindings=(
                ProjectBinding("https://github.com/example/project", wrong),
            ),
        ),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "project_binding_identity_mismatch"


def test_git_candidate_cannot_match_only_a_machine_path_alias(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "project"
    checkout.mkdir()
    remote = _remote_entry(
        "https://github.com/example/project",
        aliases=(str(checkout).casefold(),),
    )

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        remote,
        ProjectResolutionRequest(candidate_roots=(checkout,)),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "missing_local_project"


def test_git_binding_cannot_match_only_a_machine_path_alias(tmp_path: Path) -> None:
    checkout = tmp_path / "project"
    checkout.mkdir()
    remote = _remote_entry(
        "https://github.com/example/project",
        aliases=(str(checkout).casefold(),),
    )

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        remote,
        ProjectResolutionRequest(
            bindings=(ProjectBinding(remote.project_key, checkout),)
        ),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "project_binding_identity_mismatch"


def test_two_matching_git_roots_are_ambiguous(tmp_path: Path) -> None:
    first = _git_checkout(
        tmp_path / "first",
        "https://github.com/example/project.git",
    )
    second = _git_checkout(
        tmp_path / "second",
        "https://github.com/example/project.git",
    )

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        _remote_entry("https://github.com/example/project"),
        ProjectResolutionRequest(candidate_roots=(first, second)),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "ambiguous_local_project"
    assert str(first) in issue.message
    assert str(second) in issue.message


def test_binding_to_missing_directory_is_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        _remote_entry("https://github.com/example/project"),
        ProjectResolutionRequest(
            bindings=(
                ProjectBinding("https://github.com/example/project", missing),
            )
        ),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "project_binding_path_missing"
    assert str(missing) in issue.message


def test_binding_to_file_is_rejected(tmp_path: Path) -> None:
    file_path = tmp_path / "project.txt"
    file_path.write_text("not a directory", encoding="utf-8")

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        _remote_entry("https://github.com/example/project"),
        ProjectResolutionRequest(
            bindings=(
                ProjectBinding("https://github.com/example/project", file_path),
            )
        ),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "project_binding_path_not_directory"
    assert str(file_path) in issue.message


def test_duplicate_bindings_are_rejected(tmp_path: Path) -> None:
    first = _git_checkout(
        tmp_path / "first",
        "https://github.com/example/project.git",
    )
    second = _git_checkout(
        tmp_path / "second",
        "https://github.com/example/project.git",
    )

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        _remote_entry("https://github.com/example/project"),
        ProjectResolutionRequest(
            bindings=(
                ProjectBinding("https://github.com/example/project", first),
                ProjectBinding("https://github.com/example/project.git", second),
            )
        ),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "duplicate_project_binding"


def test_workspace_candidate_preserves_symlink_spelling(tmp_path: Path) -> None:
    checkout = _git_checkout(
        tmp_path / "checkout",
        "https://github.com/example/project.git",
    )
    linked = tmp_path / "linked-project"
    try:
        linked.symlink_to(checkout, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable: {error}")

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        _remote_entry("https://github.com/example/project"),
        ProjectResolutionRequest(candidate_roots=(linked,)),
    )

    assert root == linked.absolute()
    assert issue is None


def test_non_git_native_path_candidate_resolves_automatically(tmp_path: Path) -> None:
    checkout = tmp_path / "project"
    checkout.mkdir()
    remote = _remote_entry(str(checkout).casefold(), aliases=())

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        remote,
        ProjectResolutionRequest(candidate_roots=(checkout,)),
    )

    assert root == checkout.absolute()
    assert issue is None


def test_non_git_cross_machine_binding_requires_confirmation(tmp_path: Path) -> None:
    checkout = tmp_path / "project"
    checkout.mkdir()
    remote = _remote_entry("c:/users/source/project", aliases=())

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        remote,
        ProjectResolutionRequest(
            bindings=(ProjectBinding(remote.project_key, checkout),)
        ),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "unverified_project_binding_confirmation_required"

    confirmed_root, confirmed_issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        remote,
        ProjectResolutionRequest(
            bindings=(ProjectBinding(remote.project_key, checkout, True),)
        ),
    )
    assert confirmed_root == checkout.absolute()
    assert confirmed_issue is None


def test_other_local_task_cwd_is_an_automatic_candidate(tmp_path: Path) -> None:
    checkout = _git_checkout(
        tmp_path / "checkout",
        "https://github.com/example/project.git",
    )
    other_thread = _local_thread(
        "other-task",
        checkout,
        "https://github.com/example/project",
    )

    root, issue = resolve_local_project_root(
        _local_inventory(other_thread),
        None,
        _remote_entry("https://github.com/example/project"),
        ProjectResolutionRequest(),
    )

    assert root == checkout.absolute()
    assert issue is None


def test_explicit_binding_selects_one_of_multiple_automatic_candidates(
    tmp_path: Path,
) -> None:
    first = _git_checkout(
        tmp_path / "first",
        "https://github.com/example/project.git",
    )
    second = _git_checkout(
        tmp_path / "second",
        "https://github.com/example/project.git",
    )

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        _remote_entry("https://github.com/example/project"),
        ProjectResolutionRequest(
            candidate_roots=(first, second),
            bindings=(
                ProjectBinding("https://github.com/example/project", second),
            ),
        ),
    )

    assert root == second.absolute()
    assert issue is None


def test_existing_local_counterpart_keeps_its_native_cwd(tmp_path: Path) -> None:
    existing_root = _git_checkout(
        tmp_path / "existing",
        "https://github.com/example/project.git",
    )
    other_root = _git_checkout(
        tmp_path / "other",
        "https://github.com/example/project.git",
    )
    local_thread = _local_thread(
        "task-1",
        existing_root,
        "https://github.com/example/project",
    )

    root, issue = resolve_local_project_root(
        _local_inventory(local_thread),
        local_thread,
        _remote_entry("https://github.com/example/project"),
        ProjectResolutionRequest(
            bindings=(
                ProjectBinding(
                    "https://github.com/example/project",
                    other_root,
                ),
            )
        ),
    )

    assert root == existing_root.resolve(strict=False)
    assert issue is None
