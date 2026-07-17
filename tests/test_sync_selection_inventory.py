from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from codex_usage.sync.constants import REMOTE_TRANSFER_FORMAT_VERSION
from codex_usage.sync.models import (
    LocalInventory,
    RemoteIndex,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
    SyncIssue,
)
from codex_usage.sync.selection_inventory import (
    build_sync_selection_inventory,
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


def _remote_inventory(
    *entries: RemoteThreadEntry,
    issues: tuple[SyncIssue, ...] = (),
    missing_thread_ids: tuple[str, ...] = (),
) -> RemoteInventory:
    index = RemoteIndex(
        format_version=REMOTE_TRANSFER_FORMAT_VERSION,
        updated_at="",
        threads={entry.thread_id: entry for entry in entries},
    )
    files = {
        entry.thread_id: SyncFileSnapshot(
            path=Path("sync") / entry.file,
            exists=entry.thread_id not in missing_thread_ids,
            sha256=entry.sha256,
            size_bytes=entry.size_bytes,
        )
        for entry in entries
    }
    return RemoteInventory(index, index, SyncFileSnapshot(None, False), files, (), issues)


def _local_inventory(*tasks: ThreadInfo) -> LocalInventory:
    return LocalInventory((Path("sessions"),), {task.thread_id: task for task in tasks}, {}, len(tasks))


def _local_task(
    thread_id: str,
    title: str,
    project_key: str,
    project_label: str,
    updated_at: str,
) -> ThreadInfo:
    return ThreadInfo(
        thread_id=thread_id,
        title=title,
        updated_at=updated_at,
        session_path=Path("sessions") / f"{thread_id}.jsonl",
        project_key=project_key,
        project_label=project_label,
        project_aliases=(),
        total_tokens=0,
        session_bytes=100,
        estimated_sync_bytes=4196,
    )


def _remote_task(
    thread_id: str,
    title: str,
    project_key: str,
    project_label: str,
    updated_at: str,
) -> RemoteThreadEntry:
    return RemoteThreadEntry(
        thread_id=thread_id,
        file=f"tasks/{thread_id}.jsonl",
        source_relative_path=f"2026/07/14/{thread_id}.jsonl",
        index_entry={"id": thread_id, "thread_name": title, "updated_at": updated_at},
        project_key=project_key,
        project_label=project_label,
        project_aliases=(),
        sha256=f"sha-{thread_id}",
        size_bytes=100,
        session_updated_at=updated_at,
        exported_at=updated_at,
        source_machine_id="machine-a",
    )


def test_remote_fixture_uses_current_v3_task_layout() -> None:
    entry = _remote_task(
        "task-1",
        "Task one",
        "repo",
        "Repo",
        "2026-07-14T12:00:00Z",
    )
    remote = _remote_inventory(entry)

    assert remote.index.format_version == REMOTE_TRANSFER_FORMAT_VERSION
    assert entry.file == "tasks/task-1.jsonl"


def test_build_inventory_merges_by_thread_id_and_groups_projects() -> None:
    local = LocalInventory(
        session_dirs=(Path("/codex/sessions"),),
        threads={
            "shared": _local_task("shared", "Local title", "repo-a", "Repo A", "2026-07-14T12:00:00Z"),
            "local": _local_task("local", "Local only", "repo-a", "Repo A", "2026-07-14T11:00:00Z"),
        },
        index_entries={},
        discovered_count=2,
    )
    remote = _remote_inventory(
        _remote_task("shared", "Remote title", "repo-b", "Repo B", "2026-07-14T13:00:00Z"),
        _remote_task("remote", "Remote only", "repo-b", "Repo B", "2026-07-14T10:00:00Z"),
    )

    result = build_sync_selection_inventory(local, remote, Path("sync"))

    assert result.inventory_version == 2
    assert [project.project_key for project in result.projects] == ["repo-a", "repo-b"]
    assert [(task.thread_id, task.title, task.availability) for task in result.projects[0].tasks] == [
        ("shared", "Local title", "both"),
        ("local", "Local only", "local"),
    ]
    assert [(task.thread_id, task.availability) for task in result.projects[1].tasks] == [
        ("remote", "remote"),
    ]


def test_inventory_order_and_project_label_prefer_local_candidates() -> None:
    local = _local_inventory(
        _local_task("beta", "Beta", "repo", "Beta label", "2026-07-14T12:00:00Z"),
        _local_task("alpha", "Alpha", "repo", "Alpha label", "2026-07-14T12:00:00Z"),
    )
    remote = _remote_inventory(
        _remote_task("remote", "Remote", "repo", "Remote label", "2026-07-14T13:00:00Z")
    )

    result = build_sync_selection_inventory(local, remote, Path("sync"))

    assert result.projects[0].project_label == "Alpha label"
    assert [task.thread_id for task in result.projects[0].tasks] == ["remote", "alpha", "beta"]


def test_inventory_keeps_portable_remote_project_when_local_key_is_its_machine_alias() -> None:
    local = _local_inventory(
        replace(
            _local_task(
                "shared",
                "Imported task",
                "d:/projects/persona_generators",
                "persona_generators",
                "2026-07-14T12:00:00Z",
            ),
            project_aliases=(),
        )
    )
    remote = _remote_inventory(
        replace(
            _remote_task(
                "shared",
                "Imported task",
                "https://github.com/example/persona_generators",
                "persona_generators",
                "2026-07-14T12:00:00Z",
            ),
            project_aliases=("d:/projects/persona_generators",),
        )
    )

    result = build_sync_selection_inventory(local, remote, Path("sync"))

    assert [project.project_key for project in result.projects] == [
        "https://github.com/example/persona_generators"
    ]
    assert result.projects[0].tasks[0].availability == "both"


def test_inventory_omits_missing_remote_files_and_keeps_issue() -> None:
    issue = SyncIssue("unidentified_remote_file", "Could not identify mystery.jsonl")
    remote = _remote_inventory(
        _remote_task("missing", "Missing", "repo", "Repo", "2026-07-14T10:00:00Z"),
        issues=(issue,),
        missing_thread_ids=("missing",),
    )

    result = build_sync_selection_inventory(
        _local_inventory(),
        remote,
        Path("sync"),
    )

    assert result.projects == ()
    assert result.issues == (issue,)


def test_inventory_to_dict_uses_the_strict_protocol_shape() -> None:
    issue = SyncIssue("notice", "Remote notice")
    result = build_sync_selection_inventory(
        _local_inventory(
            _local_task("local", "Local", "repo", "Repo", "2026-07-14T12:00:00Z")
        ),
        _remote_inventory(issues=(issue,)),
        Path("sync"),
    )

    assert result.to_dict() == {
        "inventory_version": 2,
        "projects": [
            {
                "project_key": "repo",
                "project_label": "Repo",
                "identity_kind": "path",
                "candidate_roots": [],
                "tasks": [
                    {
                        "thread_id": "local",
                        "title": "Local",
                        "updated_at": "2026-07-14T12:00:00Z",
                        "estimated_sync_bytes": 4196,
                        "availability": "local",
                        "state": "missing",
                        "action": "skip",
                    }
                ],
            }
        ],
        "issues": [{"code": "notice", "message": "Remote notice", "thread_id": ""}],
    }


def test_inventory_v2_exposes_state_and_destination_candidates(
    tmp_path: Path,
) -> None:
    checkout = _git_checkout(
        tmp_path / "checkout",
        "https://github.com/example/repo.git",
    )
    remote = _remote_inventory(
        _remote_task(
            "remote",
            "Remote task",
            "https://github.com/example/repo",
            "Repo",
            "2026-07-14T13:00:00Z",
        )
    )

    result = build_sync_selection_inventory(
        _local_inventory(),
        remote,
        sync_dir=Path("sync"),
        candidate_roots=(checkout,),
    )
    payload = result.to_dict()

    assert payload["inventory_version"] == 2
    project = payload["projects"][0]
    assert project["identity_kind"] == "git"
    assert project["candidate_roots"] == [str(checkout.absolute())]
    assert set(project["tasks"][0]) == {
        "thread_id",
        "title",
        "updated_at",
        "estimated_sync_bytes",
        "availability",
        "state",
        "action",
    }


def test_remote_only_task_remains_selectable_without_destination() -> None:
    remote = _remote_inventory(
        _remote_task(
            "remote",
            "Remote task",
            "https://github.com/example/repo",
            "Repo",
            "2026-07-14T13:00:00Z",
        )
    )

    result = build_sync_selection_inventory(
        _local_inventory(),
        remote,
        sync_dir=Path("sync"),
    )

    assert len(result.projects) == 1
    project = result.projects[0]
    assert project.candidate_roots == ()
    assert [task.thread_id for task in project.tasks] == ["remote"]
    assert (project.tasks[0].state, project.tasks[0].action) == (
        "remote_only",
        "pull",
    )
