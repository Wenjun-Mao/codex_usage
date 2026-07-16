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
from codex_usage.sync.errors import (
    LegacySyncLayoutError,
    MalformedSyncIndexError,
    TransferFormatMigrationError,
)
from codex_usage.sync.models import (
    RemoteIndex,
    RemoteThreadEntry,
    SyncFileSnapshot,
)
from codex_usage.sync.selection_inventory import load_sync_selection_inventory


def _remote_task(thread_id: str, *, directory: str) -> RemoteThreadEntry:
    return RemoteThreadEntry(
        thread_id=thread_id,
        file=f"{directory}/{thread_id}.jsonl",
        source_relative_path=f"2026/07/14/{thread_id}.jsonl",
        index_entry={
            "id": thread_id,
            "thread_name": "Remote task",
            "updated_at": "2026-07-14T12:00:00Z",
        },
        project_key="repo-a",
        project_label="Repo A",
        project_aliases=(),
        sha256="",
        size_bytes=0,
        session_updated_at="2026-07-14T12:00:00Z",
        exported_at="2026-07-14T12:00:00Z",
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


def _write_indexed_remote_task(
    sync_dir: Path,
    contents: bytes,
    *,
    format_version: int = 2,
) -> Path:
    directory = "conversations" if format_version == 2 else "tasks"
    task_path = sync_dir / directory / "thread-1.jsonl"
    task_path.parent.mkdir(parents=True)
    task_path.write_bytes(contents)
    snapshot = sync_io.snapshot_file(task_path)
    entry = replace(
        _remote_task("thread-1", directory=directory),
        sha256=snapshot.sha256,
        size_bytes=snapshot.size_bytes,
    )
    index = RemoteIndex(
        format_version=format_version,
        updated_at="2026-07-14T12:00:00Z",
        threads={entry.thread_id: entry},
    )
    (sync_dir / "sync-index.json").write_text(
        json.dumps(index.to_dict(), separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return task_path


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


def _snapshot_tree(root: Path) -> tuple[tuple[str, str, bytes], ...]:
    entries: list[tuple[str, str, bytes]] = []
    for path in sorted(root.rglob("*")):
        if path.name.endswith(".codex-usage.lock"):
            continue
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
    before = _snapshot_tree(tmp_path)

    load_sync_selection_inventory(
        _empty_cached_data(tmp_path / "sessions"),
        sync_dir,
    )

    assert _snapshot_tree(tmp_path) == before


def test_load_inventory_migrates_indexed_remote_task_without_local_sessions(
    tmp_path: Path,
) -> None:
    sync_dir = tmp_path / "sync"
    source = _write_indexed_remote_task(sync_dir, _session_jsonl("thread-1"))
    payload = source.read_bytes()

    result = load_sync_selection_inventory(
        _empty_cached_data(tmp_path / "empty-codex-home" / "sessions"),
        sync_dir,
    )

    assert [
        (project.project_key, project.project_label) for project in result.projects
    ] == [("repo-a", "Repo A")]
    assert [
        (task.thread_id, task.title, task.availability)
        for task in result.projects[0].tasks
    ] == [("thread-1", "Remote task", "remote")]
    assert result.issues == ()
    index = json.loads((sync_dir / "sync-index.json").read_text(encoding="utf-8"))
    assert index["format_version"] == 3
    assert index["threads"]["thread-1"]["file"] == "tasks/thread-1.jsonl"
    assert (sync_dir / "tasks" / "thread-1.jsonl").read_bytes() == payload
    assert not (sync_dir / "conversations").exists()


def test_load_inventory_rejects_mismatched_remote_index_identity_without_mutation(
    tmp_path: Path,
) -> None:
    sync_dir = tmp_path / "sync"
    _write_indexed_remote_task(sync_dir, _session_jsonl("thread-1"))
    index_path = sync_dir / "sync-index.json"
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    index_payload["threads"]["thread-1"]["index_entry"]["id"] = "thread-2"
    index_path.write_text(
        json.dumps(index_payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    before = _snapshot_tree(tmp_path)

    with pytest.raises(MalformedSyncIndexError, match=r"index_entry\.id.*match"):
        load_sync_selection_inventory(
            _empty_cached_data(tmp_path / "empty-codex-home" / "sessions"),
            sync_dir,
        )

    assert _snapshot_tree(tmp_path) == before


@pytest.mark.parametrize(
    ("contents", "issue_fragment"),
    _INVALID_INDEXED_CONVERSATIONS,
)
def test_load_inventory_rejects_invalid_indexed_v2_task(
    tmp_path: Path,
    contents: bytes,
    issue_fragment: str,
) -> None:
    sync_dir = tmp_path / "sync"
    _write_indexed_remote_task(sync_dir, contents)
    local_data = _cached_local_task_data(
        tmp_path / "codex-home" / "sessions", "thread-1"
    )
    before = _snapshot_tree(tmp_path)

    for data in (
        _empty_cached_data(tmp_path / "empty-codex-home" / "sessions"),
        local_data,
    ):
        with pytest.raises(TransferFormatMigrationError, match=issue_fragment):
            load_sync_selection_inventory(data, sync_dir)
    assert _snapshot_tree(tmp_path) == before


def test_load_inventory_propagates_v2_materialization_read_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_dir = tmp_path / "sync"
    conversation_path = _write_indexed_remote_task(
        sync_dir,
        _session_jsonl("thread-1"),
    )
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

    with pytest.raises(PermissionError, match="Cannot read"):
        load_sync_selection_inventory(
            _empty_cached_data(tmp_path / "empty-codex-home" / "sessions"),
            sync_dir,
        )

    assert _snapshot_tree(tmp_path) == before


def test_load_inventory_keeps_v3_materialization_read_error_as_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_dir = tmp_path / "sync"
    task_path = _write_indexed_remote_task(
        sync_dir,
        _session_jsonl("thread-1"),
        format_version=3,
    )
    original_read = remote_reconciliation.read_bytes_with_snapshot

    def deny_task_read(path: Path) -> tuple[bytes | None, SyncFileSnapshot]:
        if path == task_path:
            raise PermissionError(f"Cannot read {path}")
        return original_read(path)

    monkeypatch.setattr(
        remote_reconciliation,
        "read_bytes_with_snapshot",
        deny_task_read,
    )

    result = load_sync_selection_inventory(
        _empty_cached_data(tmp_path / "empty-codex-home" / "sessions"),
        sync_dir,
    )

    assert result.projects == ()
    assert len(result.issues) == 1
    assert result.issues[0].code == "unindexed_unreadable"
    assert result.issues[0].thread_id == "thread-1"


def test_load_inventory_rejects_duplicate_v2_task_identity_without_mutation(
    tmp_path: Path,
) -> None:
    sync_dir = tmp_path / "sync"
    _write_indexed_remote_task(sync_dir, _session_jsonl("thread-1"))
    (sync_dir / "conversations" / "duplicate.jsonl").write_bytes(
        _session_jsonl("thread-1")
    )
    before = _snapshot_tree(tmp_path)

    with pytest.raises(
        TransferFormatMigrationError,
        match="multiple remote files claim thread id",
    ):
        load_sync_selection_inventory(
            _empty_cached_data(tmp_path / "empty-codex-home" / "sessions"),
            sync_dir,
        )
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
                raise PermissionError(
                    f"Cannot inspect unreadable remote folder {sync_dir}"
                )
            return original_lstat(path)

        monkeypatch.setattr(sync_io, "_lstat", unreadable_remote)
    before = _snapshot_tree(tmp_path)

    with pytest.raises(expected_error):
        load_sync_selection_inventory(
            _empty_cached_data(tmp_path / "sessions"), sync_dir
        )

    assert _snapshot_tree(tmp_path) == before


def test_empty_remote_folder_returns_local_tasks(tmp_path: Path) -> None:
    data = _cached_local_task_data(tmp_path / "sessions", "local")
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()

    result = load_sync_selection_inventory(data, sync_dir)

    assert [
        (project.project_key, project.project_label) for project in result.projects
    ] == [("repo-a", "Repo A")]
    assert [
        (task.thread_id, task.availability) for task in result.projects[0].tasks
    ] == [("local", "local")]
    assert list(sync_dir.iterdir()) == []
