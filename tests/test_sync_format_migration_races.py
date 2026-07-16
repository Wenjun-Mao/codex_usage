from __future__ import annotations

import errno
import hashlib
import json
from pathlib import Path

import pytest

import codex_usage.sync.io as sync_io
from codex_usage.sync import format_migration, format_migration_layout
from codex_usage.sync.errors import (
    ConcurrentRemoteChangeError,
    MalformedSyncIndexError,
)
from codex_usage.sync.format_migration import migrate_remote_layout_v2_to_v3


def _session_payload(thread_id: str) -> bytes:
    return (
        json.dumps(
            {
                "timestamp": "2026-07-15T00:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": thread_id,
                    "timestamp": "2026-07-15T00:00:00Z",
                    "cwd": "/source/project",
                },
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _entry(thread_id: str, payload: bytes, directory: str) -> dict[str, object]:
    return {
        "file": f"{directory}/{thread_id}.jsonl",
        "source_relative_path": f"2026/07/15/{thread_id}.jsonl",
        "index_entry": {"id": thread_id, "thread_name": thread_id},
        "project_key": "/source/project",
        "project_label": "project",
        "project_aliases": [],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "session_updated_at": "2026-07-15T00:00:00Z",
        "exported_at": "2026-07-15T00:00:00Z",
        "source_machine_id": "source",
    }


def _write_index(
    root: Path,
    version: int,
    entries: dict[str, dict[str, object]],
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "sync-index.json").write_text(
        json.dumps(
            {
                "format_version": version,
                "updated_at": "2026-07-15T00:00:00Z",
                "threads": entries,
            }
        ),
        encoding="utf-8",
    )


def _write_v2(root: Path, *thread_ids: str) -> dict[str, bytes]:
    payloads = {thread_id: _session_payload(thread_id) for thread_id in thread_ids}
    conversations = root / "conversations"
    conversations.mkdir(parents=True)
    for thread_id, payload in payloads.items():
        (conversations / f"{thread_id}.jsonl").write_bytes(payload)
    _write_index(
        root,
        2,
        {
            thread_id: _entry(thread_id, payload, "conversations")
            for thread_id, payload in payloads.items()
        },
    )
    return payloads


def _write_v3_with_legacy(root: Path, *thread_ids: str) -> dict[str, bytes]:
    payloads = {thread_id: _session_payload(thread_id) for thread_id in thread_ids}
    tasks = root / "tasks"
    conversations = root / "conversations"
    tasks.mkdir(parents=True)
    conversations.mkdir()
    for thread_id, payload in payloads.items():
        filename = f"{thread_id}.jsonl"
        (tasks / filename).write_bytes(payload)
        (conversations / filename).write_bytes(payload)
    _write_index(
        root,
        3,
        {
            thread_id: _entry(thread_id, payload, "tasks")
            for thread_id, payload in payloads.items()
        },
    )
    return payloads


@pytest.mark.parametrize("changed_copy", ["legacy", "staged"])
def test_commit_boundary_revalidates_all_v2_task_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_copy: str,
) -> None:
    payload = _write_v2(tmp_path, "task-1")["task-1"]
    source = tmp_path / "conversations" / "task-1.jsonl"
    staged = tmp_path / "tasks" / "task-1.jsonl"
    real_replace = sync_io._replace_if_expected
    mutated = False

    def mutate_after_temp_write(*args, **kwargs) -> None:
        nonlocal mutated
        target = args[1]
        if target == tmp_path / "sync-index.json" and not mutated:
            mutated = True
            changed = source if changed_copy == "legacy" else staged
            changed.write_bytes(payload + b'{"type":"response_item"}\n')
        real_replace(*args, **kwargs)

    monkeypatch.setattr(sync_io, "_replace_if_expected", mutate_after_temp_write)

    with pytest.raises(
        ConcurrentRemoteChangeError, match="changed before migration commit"
    ):
        migrate_remote_layout_v2_to_v3(tmp_path)

    index = json.loads((tmp_path / "sync-index.json").read_text(encoding="utf-8"))
    assert index["format_version"] == 2
    assert source.exists()
    assert staged.exists()


def test_cleanup_revalidates_v3_task_snapshot_at_unlink_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _write_v3_with_legacy(tmp_path, "task-1")["task-1"]
    legacy = tmp_path / "conversations" / "task-1.jsonl"
    task = tmp_path / "tasks" / "task-1.jsonl"
    real_unlink = format_migration._unlink
    mutated = False

    def mutate_then_unlink(*args, **kwargs) -> None:
        nonlocal mutated
        if not mutated:
            mutated = True
            task.write_bytes(payload + b'{"type":"response_item"}\n')
        real_unlink(*args, **kwargs)

    monkeypatch.setattr(format_migration, "_unlink", mutate_then_unlink)

    with pytest.raises(ConcurrentRemoteChangeError, match="Version-3 task"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert legacy.read_bytes() == payload


def test_cleanup_revalidates_v3_index_snapshot_at_unlink_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _write_v3_with_legacy(tmp_path, "task-1")["task-1"]
    legacy = tmp_path / "conversations" / "task-1.jsonl"
    index_path = tmp_path / "sync-index.json"
    real_unlink = format_migration._unlink
    mutated = False

    def mutate_then_unlink(*args, **kwargs) -> None:
        nonlocal mutated
        if not mutated:
            mutated = True
            value = json.loads(index_path.read_text(encoding="utf-8"))
            value["updated_at"] = "2026-07-16T00:00:00Z"
            index_path.write_text(json.dumps(value), encoding="utf-8")
        real_unlink(*args, **kwargs)

    monkeypatch.setattr(format_migration, "_unlink", mutate_then_unlink)

    with pytest.raises(ConcurrentRemoteChangeError, match="index changed"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert legacy.read_bytes() == payload


def test_multi_file_cleanup_revalidates_before_each_legacy_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _write_v3_with_legacy(tmp_path, "task-1", "task-2")
    legacy_paths = [
        tmp_path / "conversations" / f"{thread_id}.jsonl" for thread_id in payloads
    ]
    real_unlink = format_migration._unlink
    mutated = False

    def unlink_once_then_mutate_remaining_task(*args, **kwargs) -> None:
        nonlocal mutated
        real_unlink(*args, **kwargs)
        remaining = [path for path in legacy_paths if path.exists()]
        if not mutated and len(remaining) == 1:
            mutated = True
            task = tmp_path / "tasks" / remaining[0].name
            task.write_bytes(task.read_bytes() + b'{"type":"response_item"}\n')

    monkeypatch.setattr(
        format_migration,
        "_unlink",
        unlink_once_then_mutate_remaining_task,
    )

    with pytest.raises(ConcurrentRemoteChangeError, match="Version-3 task"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    remaining = [path for path in legacy_paths if path.exists()]
    assert len(remaining) == 1
    thread_id = remaining[0].stem
    assert remaining[0].read_bytes() == payloads[thread_id]


def test_unlink_retry_revalidates_after_legacy_directory_junction_like_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _write_v3_with_legacy(tmp_path, "task-1")["task-1"]
    conversations = tmp_path / "conversations"
    legacy = conversations / "task-1.jsonl"
    real_unlink = Path.unlink
    real_path_kind = format_migration_layout.path_kind
    attempts = 0
    swapped = False

    def junction_after_failure(path: Path) -> str:
        if swapped and path == conversations:
            return "junction"
        return real_path_kind(path)

    def fail_then_swap(path: Path, *args, **kwargs) -> None:
        nonlocal attempts, swapped
        if path == legacy:
            attempts += 1
            if attempts == 1:
                swapped = True
                raise OSError(errno.EBUSY, "simulated transient unlink failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(format_migration_layout, "path_kind", junction_after_failure)
    monkeypatch.setattr(Path, "unlink", fail_then_swap)

    with pytest.raises(MalformedSyncIndexError, match="conversations"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert attempts == 1
    assert legacy.read_bytes() == payload


def test_rmdir_retry_revalidates_after_legacy_directory_junction_like_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_v3_with_legacy(tmp_path, "task-1")
    conversations = tmp_path / "conversations"
    real_rmdir = Path.rmdir
    real_path_kind = format_migration_layout.path_kind
    attempts = 0
    swapped = False

    def junction_after_failure(path: Path) -> str:
        if swapped and path == conversations:
            return "junction"
        return real_path_kind(path)

    def fail_then_swap(path: Path, *args, **kwargs) -> None:
        nonlocal attempts, swapped
        if path == conversations:
            attempts += 1
            if attempts == 1:
                swapped = True
                raise OSError(errno.EBUSY, "simulated transient rmdir failure")
        real_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(format_migration_layout, "path_kind", junction_after_failure)
    monkeypatch.setattr(Path, "rmdir", fail_then_swap)

    with pytest.raises(MalformedSyncIndexError, match="conversations"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert attempts == 1
    assert conversations.exists()
