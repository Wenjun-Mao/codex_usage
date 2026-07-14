from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

import codex_usage.sync.io as sync_io
import codex_usage.sync.remote_reconciliation as remote_reconciliation
from codex_usage.session_cache import (
    CacheStats,
    CachedFileSummary,
    CachedSessionData,
)
from codex_usage.sync.errors import LegacySyncLayoutError, MalformedSyncIndexError
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
    load_sync_selection_inventory,
)
from codex_usage.threads import ThreadInfo


def _remote_inventory(
    *entries: RemoteThreadEntry,
    issues: tuple[SyncIssue, ...] = (),
    missing_thread_ids: tuple[str, ...] = (),
) -> RemoteInventory:
    index = RemoteIndex(
        format_version=2,
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
        file=f"conversations/{thread_id}.jsonl",
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


def _empty_cached_data(session_dir: Path) -> CachedSessionData:
    return CachedSessionData(
        session_dirs=[session_dir],
        files=[],
        records=[],
        file_summaries={},
        project_transitions=[],
        stats=CacheStats(),
        file_errors={},
    )


def _cached_local_task_data(session_dir: Path, thread_id: str) -> CachedSessionData:
    session_dir.mkdir(parents=True)
    session_path = session_dir / f"{thread_id}.jsonl"
    session_path.write_bytes(b"{}\n")
    summary = CachedFileSummary(
        file_path=session_path,
        session_dir=session_dir,
        session_id=thread_id,
        cwd="/repo/a",
        project_key="repo-a",
        project_label="Repo A",
        project_aliases=(),
        git_repository_url="",
        git_branch="",
        memory_mode="",
        has_base_instructions=False,
        session_bytes=3,
        estimated_sync_bytes=4099,
    )
    return CachedSessionData(
        session_dirs=[session_dir],
        files=[session_path],
        records=[],
        file_summaries={session_path: summary},
        project_transitions=[],
        stats=CacheStats(files_total=1, files_current=1),
        file_errors={},
    )


def _session_jsonl(thread_id: str) -> bytes:
    event = {
        "timestamp": "2026-07-14T12:00:00Z",
        "type": "session_meta",
        "payload": {
            "id": thread_id,
            "timestamp": "2026-07-14T12:00:00Z",
            "cwd": "/repo/a",
            "git": {"repository_url": "https://github.com/example/repo-a.git"},
        },
    }
    return (json.dumps(event, separators=(",", ":")) + "\n").encode()


def _write_indexed_remote_task(sync_dir: Path, contents: bytes) -> None:
    conversation_path = sync_dir / "conversations" / "thread-1.jsonl"
    conversation_path.parent.mkdir(parents=True)
    conversation_path.write_bytes(contents)
    snapshot = sync_io.snapshot_file(conversation_path)
    entry = replace(
        _remote_task(
            "thread-1",
            "Remote task",
            "repo-a",
            "Repo A",
            "2026-07-14T12:00:00Z",
        ),
        sha256=snapshot.sha256,
        size_bytes=snapshot.size_bytes,
    )
    index = RemoteIndex(
        format_version=2,
        updated_at="2026-07-14T12:00:00Z",
        threads={entry.thread_id: entry},
    )
    (sync_dir / "sync-index.json").write_text(
        json.dumps(index.to_dict(), separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


_INVALID_INDEXED_CONVERSATIONS = (
    pytest.param(
        b"not-json\n",
        "has no readable session_meta identity",
        id="no-readable-session-meta",
    ),
    pytest.param(
        _session_jsonl("different-thread"),
        "contains thread id 'different-thread'",
        id="mismatched-thread-id",
    ),
    pytest.param(
        _session_jsonl(" thread-1 "),
        "has no readable session_meta identity",
        id="padded-thread-id",
    ),
)


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

    result = build_sync_selection_inventory(local, remote)

    assert result.inventory_version == 1
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

    result = build_sync_selection_inventory(local, remote)

    assert result.projects[0].project_label == "Alpha label"
    assert [task.thread_id for task in result.projects[0].tasks] == ["remote", "alpha", "beta"]


def test_inventory_omits_missing_remote_files_and_keeps_issue() -> None:
    issue = SyncIssue("unidentified_remote_file", "Could not identify mystery.jsonl")
    remote = _remote_inventory(
        _remote_task("missing", "Missing", "repo", "Repo", "2026-07-14T10:00:00Z"),
        issues=(issue,),
        missing_thread_ids=("missing",),
    )

    result = build_sync_selection_inventory(_local_inventory(), remote)

    assert result.projects == ()
    assert result.issues == (issue,)


def test_inventory_to_dict_uses_the_strict_protocol_shape() -> None:
    issue = SyncIssue("notice", "Remote notice")
    result = build_sync_selection_inventory(
        _local_inventory(
            _local_task("local", "Local", "repo", "Repo", "2026-07-14T12:00:00Z")
        ),
        _remote_inventory(issues=(issue,)),
    )

    assert result.to_dict() == {
        "inventory_version": 1,
        "projects": [
            {
                "project_key": "repo",
                "project_label": "Repo",
                "tasks": [
                    {
                        "thread_id": "local",
                        "title": "Local",
                        "updated_at": "2026-07-14T12:00:00Z",
                        "estimated_sync_bytes": 4196,
                        "availability": "local",
                    }
                ],
            }
        ],
        "issues": [{"code": "notice", "message": "Remote notice", "thread_id": ""}],
    }


def _snapshot_tree(root: Path) -> tuple[tuple[str, str, bytes], ...]:
    entries: list[tuple[str, str, bytes]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((relative, "symlink", os.readlink(path).encode()))
        elif path.is_dir():
            entries.append((relative, "directory", b""))
        else:
            entries.append((relative, "file", path.read_bytes()))
    return tuple(entries)


def test_load_inventory_is_read_only(tmp_path: Path) -> None:
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    data = CachedSessionData(
        session_dirs=[tmp_path / "sessions"],
        files=[],
        records=[],
        file_summaries={},
        project_transitions=[],
        stats=CacheStats(),
        file_errors={},
    )
    before = _snapshot_tree(tmp_path)

    load_sync_selection_inventory(data, sync_dir)

    assert _snapshot_tree(tmp_path) == before


def test_load_inventory_discovers_indexed_remote_task_without_local_sessions(
    tmp_path: Path,
) -> None:
    sync_dir = tmp_path / "sync"
    _write_indexed_remote_task(sync_dir, _session_jsonl("thread-1"))
    before = _snapshot_tree(tmp_path)

    result = load_sync_selection_inventory(
        _empty_cached_data(tmp_path / "empty-codex-home" / "sessions"),
        sync_dir,
    )

    assert [(project.project_key, project.project_label) for project in result.projects] == [
        ("repo-a", "Repo A")
    ]
    assert [
        (task.thread_id, task.title, task.availability) for task in result.projects[0].tasks
    ] == [("thread-1", "Remote task", "remote")]
    assert result.issues == ()
    assert _snapshot_tree(tmp_path) == before


@pytest.mark.parametrize(
    ("contents", "issue_fragment"),
    _INVALID_INDEXED_CONVERSATIONS,
)
def test_load_inventory_omits_invalid_indexed_remote_task(
    tmp_path: Path,
    contents: bytes,
    issue_fragment: str,
) -> None:
    sync_dir = tmp_path / "sync"
    _write_indexed_remote_task(sync_dir, contents)
    local_data = _cached_local_task_data(tmp_path / "codex-home" / "sessions", "thread-1")
    before = _snapshot_tree(tmp_path)

    remote_only = load_sync_selection_inventory(
        _empty_cached_data(tmp_path / "empty-codex-home" / "sessions"),
        sync_dir,
    )
    with_local = load_sync_selection_inventory(local_data, sync_dir)

    assert remote_only.projects == ()
    assert [(project.project_key, project.project_label) for project in with_local.projects] == [
        ("repo-a", "Repo A")
    ]
    assert [(task.thread_id, task.availability) for task in with_local.projects[0].tasks] == [
        ("thread-1", "local")
    ]
    for result in (remote_only, with_local):
        assert len(result.issues) == 1
        assert result.issues[0].code == "unindexed_unreadable"
        assert result.issues[0].thread_id == "thread-1"
        assert issue_fragment in result.issues[0].message
    assert _snapshot_tree(tmp_path) == before


def test_load_inventory_omits_indexed_remote_when_materialization_read_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_dir = tmp_path / "sync"
    _write_indexed_remote_task(sync_dir, _session_jsonl("thread-1"))
    conversation_path = sync_dir / "conversations" / "thread-1.jsonl"
    local_data = _cached_local_task_data(tmp_path / "codex-home" / "sessions", "thread-1")
    original_read = remote_reconciliation.read_bytes_with_snapshot

    def deny_conversation_read(path: Path) -> tuple[bytes | None, SyncFileSnapshot]:
        if path == conversation_path:
            raise PermissionError(f"Cannot read {path}")
        return original_read(path)

    monkeypatch.setattr(
        remote_reconciliation,
        "read_bytes_with_snapshot",
        deny_conversation_read,
    )
    before = _snapshot_tree(tmp_path)

    remote_only = load_sync_selection_inventory(
        _empty_cached_data(tmp_path / "empty-codex-home" / "sessions"),
        sync_dir,
    )
    with_local = load_sync_selection_inventory(local_data, sync_dir)

    assert remote_only.projects == ()
    assert [(task.thread_id, task.availability) for task in with_local.projects[0].tasks] == [
        ("thread-1", "local")
    ]
    for result in (remote_only, with_local):
        assert len(result.issues) == 1
        assert result.issues[0].code == "unindexed_unreadable"
        assert result.issues[0].thread_id == "thread-1"
        assert "has no readable session_meta identity" in result.issues[0].message
    assert _snapshot_tree(tmp_path) == before


def test_load_inventory_keeps_valid_indexed_task_with_preexisting_thread_issue(
    tmp_path: Path,
) -> None:
    sync_dir = tmp_path / "sync"
    _write_indexed_remote_task(sync_dir, _session_jsonl("thread-1"))
    (sync_dir / "conversations" / "duplicate.jsonl").write_bytes(
        _session_jsonl("thread-1")
    )
    before = _snapshot_tree(tmp_path)

    result = load_sync_selection_inventory(
        _empty_cached_data(tmp_path / "empty-codex-home" / "sessions"),
        sync_dir,
    )

    assert [(task.thread_id, task.availability) for task in result.projects[0].tasks] == [
        ("thread-1", "remote")
    ]
    assert len(result.issues) == 1
    assert result.issues[0].code == "unindexed_unreadable"
    assert result.issues[0].thread_id == "thread-1"
    assert "multiple remote files claim thread id" in result.issues[0].message
    assert _snapshot_tree(tmp_path) == before


@pytest.mark.parametrize(
    ("layout", "expected_error"),
    [
        ("malformed-index", MalformedSyncIndexError),
        ("legacy-threads", LegacySyncLayoutError),
        ("symlinked-conversations", MalformedSyncIndexError),
        ("unreadable-folder", PermissionError),
    ],
)
def test_load_inventory_propagates_structural_errors_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    layout: str,
    expected_error: type[Exception],
) -> None:
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    if layout == "malformed-index":
        (sync_dir / "sync-index.json").write_bytes(b"{not-json\n")
    elif layout == "legacy-threads":
        (sync_dir / "threads").mkdir()
    elif layout == "symlinked-conversations":
        external = tmp_path / "external"
        external.mkdir()
        try:
            (sync_dir / "conversations").symlink_to(external, target_is_directory=True)
        except OSError as error:
            pytest.skip(f"symlinks are unavailable: {error}")
    else:
        original_lstat = sync_io._lstat

        def unreadable_remote(path: Path) -> os.stat_result:
            if path == sync_dir / "threads":
                raise PermissionError(f"Cannot inspect unreadable remote folder {sync_dir}")
            return original_lstat(path)

        monkeypatch.setattr(sync_io, "_lstat", unreadable_remote)
    before = _snapshot_tree(tmp_path)

    with pytest.raises(expected_error):
        load_sync_selection_inventory(_empty_cached_data(tmp_path / "sessions"), sync_dir)

    assert _snapshot_tree(tmp_path) == before


def test_empty_remote_folder_returns_local_tasks(tmp_path: Path) -> None:
    data = _cached_local_task_data(tmp_path / "sessions", "local")
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()

    result = load_sync_selection_inventory(data, sync_dir)

    assert [(project.project_key, project.project_label) for project in result.projects] == [
        ("repo-a", "Repo A")
    ]
    assert [(task.thread_id, task.availability) for task in result.projects[0].tasks] == [
        ("local", "local")
    ]
    assert list(sync_dir.iterdir()) == []
