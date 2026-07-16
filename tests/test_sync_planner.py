from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

import codex_usage.sync.planner as sync_planner
from codex_usage.sync.constants import REMOTE_TRANSFER_FORMAT_VERSION
from codex_usage.sync.io import snapshot_file
from codex_usage.sync.models import (
    LocalInventory,
    RemoteIndex,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
    SyncIssue,
)
from codex_usage.sync.planner import build_sync_plan, classify_snapshots
from codex_usage.threads import ThreadInfo


def _thread(thread_id: str, project_key: str = "repo", aliases: tuple[str, ...] = ()) -> ThreadInfo:
    return ThreadInfo(
        thread_id=thread_id,
        title=thread_id,
        updated_at="2026-07-13T12:00:00Z",
        session_path=Path("fixtures") / f"{thread_id}.jsonl",
        project_key=project_key,
        project_label=project_key,
        project_aliases=aliases,
        total_tokens=0,
        session_bytes=0,
        estimated_sync_bytes=4096,
    )


def _remote_entry(thread_id: str, project_key: str = "repo") -> RemoteThreadEntry:
    return RemoteThreadEntry(
        thread_id=thread_id,
        file=f"tasks/{thread_id}.jsonl",
        source_relative_path=f"synced/{thread_id}.jsonl",
        index_entry={"id": thread_id},
        project_key=project_key,
        project_label=project_key,
        project_aliases=(),
        sha256="",
        size_bytes=0,
        session_updated_at="2026-07-13T12:00:00Z",
        exported_at="2026-07-13T12:00:00Z",
        source_machine_id="machine-a",
    )


def _local_inventory(*threads: ThreadInfo) -> LocalInventory:
    return LocalInventory(
        session_dirs=(Path("sessions"),),
        threads={item.thread_id: item for item in threads},
        index_entries={},
        discovered_count=len(threads),
    )


def _remote_inventory(*entries: RemoteThreadEntry) -> RemoteInventory:
    index = RemoteIndex(
        format_version=REMOTE_TRANSFER_FORMAT_VERSION,
        updated_at="",
        threads={item.thread_id: item for item in entries},
    )
    return RemoteInventory(
        persisted_index=index,
        index=index,
        index_snapshot=SyncFileSnapshot(path=None, exists=False),
        files={},
        repaired_thread_ids=(),
        issues=(),
    )


def _one_thread_remote(
    effective_entry: RemoteThreadEntry,
    snapshot: SyncFileSnapshot,
    *,
    persisted_entry: RemoteThreadEntry | None = None,
    issues: tuple[SyncIssue, ...] = (),
    repaired: bool = False,
) -> RemoteInventory:
    persisted = persisted_entry or effective_entry
    return RemoteInventory(
        persisted_index=RemoteIndex(
            REMOTE_TRANSFER_FORMAT_VERSION,
            "",
            {persisted.thread_id: persisted},
        ),
        index=RemoteIndex(
            REMOTE_TRANSFER_FORMAT_VERSION,
            "",
            {effective_entry.thread_id: effective_entry},
        ),
        index_snapshot=SyncFileSnapshot(path=None, exists=False),
        files={effective_entry.thread_id: snapshot},
        repaired_thread_ids=(effective_entry.thread_id,) if repaired else (),
        issues=issues,
    )


def _snapshot_bytes(tmp_path: Path, name: str, value: bytes | None) -> SyncFileSnapshot:
    path = tmp_path / name
    if value is None:
        return SyncFileSnapshot(path=path, exists=False)
    path.write_bytes(value)
    return snapshot_file(path)


def test_build_sync_plan_rejects_unmaterialized_selected_remote_entry(
    tmp_path: Path,
) -> None:
    remote = _remote_inventory(_remote_entry("thread-1"))

    with pytest.raises(ValueError, match="must be materialized before planning"):
        build_sync_plan(
            _local_inventory(),
            remote,
            ("thread-1",),
            tmp_path / "sync",
        )


@pytest.mark.parametrize(
    ("local", "remote", "base", "expected_state", "expected_action"),
    [
        (b"same", b"same", b"same", "synced", "none"),
        (b"base+local", b"base", b"base", "local_ahead", "push"),
        (b"base", b"base+remote", b"base", "remote_ahead", "pull"),
        (b"base+local", b"base", None, "fast_forward_push", "push"),
        (b"base", b"base+remote", None, "fast_forward_pull", "pull"),
        (b"left", b"right", b"base", "conflict", "conflict"),
        (b"left", b"righty", None, "conflict", "conflict"),
        (b"local", None, None, "local_only", "push"),
        (None, b"remote", None, "remote_only", "pull"),
        (None, None, None, "missing", "skip"),
    ],
)
def test_planner_classifies_three_way_state(
    tmp_path: Path,
    local: bytes | None,
    remote: bytes | None,
    base: bytes | None,
    expected_state: str,
    expected_action: str,
) -> None:
    local_snapshot = _snapshot_bytes(tmp_path, "local.jsonl", local)
    remote_snapshot = _snapshot_bytes(tmp_path, "remote.jsonl", remote)
    base_sha256 = hashlib.sha256(base).hexdigest() if base is not None else ""

    state, action, _reason = classify_snapshots(local_snapshot, remote_snapshot, base_sha256)

    assert state == expected_state
    assert action == expected_action


def test_planner_treats_distinct_materialized_local_and_remote_baselines_as_synced(
    tmp_path: Path,
) -> None:
    local = _snapshot_bytes(tmp_path, "local.jsonl", b'local-cwd\nhistory')
    remote = _snapshot_bytes(tmp_path, "remote.jsonl", b'remote-cwd\nhistory')

    state, action, reason = classify_snapshots(
        local,
        remote,
        base_sha256=local.sha256,
        last_local_sha256=local.sha256,
        last_remote_sha256=remote.sha256,
    )

    assert (state, action) == ("synced", "none")
    assert reason == "local and remote match their last synchronized versions"


def test_planner_detects_real_local_change_from_distinct_materialized_baselines(
    tmp_path: Path,
) -> None:
    previous_local = _snapshot_bytes(tmp_path, "previous-local.jsonl", b'local-cwd\nhistory')
    local = _snapshot_bytes(tmp_path, "local.jsonl", b'local-cwd\nhistory\nnew turn')
    remote = _snapshot_bytes(tmp_path, "remote.jsonl", b'remote-cwd\nhistory')

    state, action, _reason = classify_snapshots(
        local,
        remote,
        base_sha256=previous_local.sha256,
        last_local_sha256=previous_local.sha256,
        last_remote_sha256=remote.sha256,
    )

    assert (state, action) == ("local_ahead", "push")


def test_equal_hashes_do_not_require_prefix_file_reads(tmp_path: Path) -> None:
    local = _snapshot_bytes(tmp_path, "local.jsonl", b"same")
    remote = _snapshot_bytes(tmp_path, "remote.jsonl", b"same")
    assert local.path is not None
    assert remote.path is not None
    local.path.unlink()
    remote.path.unlink()

    assert classify_snapshots(local, remote, "")[:2] == ("synced", "none")


def test_equal_size_different_hashes_do_not_require_prefix_file_reads(tmp_path: Path) -> None:
    local = _snapshot_bytes(tmp_path, "local.jsonl", b"left")
    remote = _snapshot_bytes(tmp_path, "remote.jsonl", b"rght")
    assert local.path is not None
    assert remote.path is not None
    local.path.unlink()
    remote.path.unlink()

    assert classify_snapshots(local, remote, "")[:2] == ("conflict", "conflict")


def test_different_sizes_check_only_possible_prefix_direction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = _snapshot_bytes(tmp_path, "local.jsonl", b"longer")
    remote = _snapshot_bytes(tmp_path, "remote.jsonl", b"short")
    calls: list[tuple[SyncFileSnapshot, SyncFileSnapshot]] = []

    def not_a_prefix(prefix: SyncFileSnapshot, full: SyncFileSnapshot) -> bool:
        calls.append((prefix, full))
        return False

    monkeypatch.setattr(sync_planner, "is_byte_prefix", not_a_prefix)

    assert classify_snapshots(local, remote, "")[:2] == ("conflict", "conflict")
    assert calls == [(remote, local)]


def test_planner_rejects_remote_path_traversal_without_mutating_local_files(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    sessions.mkdir(parents=True)
    sync_dir = tmp_path / "sync"
    remote_path = sync_dir / "tasks" / "thread-1.jsonl"
    remote_path.parent.mkdir(parents=True)
    remote_path.write_bytes(b"remote")
    entry = replace(_remote_entry("thread-1"), source_relative_path="../outside.jsonl")
    remote = _one_thread_remote(entry, snapshot_file(remote_path))

    plan = build_sync_plan(_local_inventory(), remote, ("thread-1",), sync_dir)

    assert plan.items[0].state == "issue"
    assert plan.items[0].action == "issue"
    assert plan.issues[-1].code == "unsafe_local_path"
    assert plan.issues[-1].thread_id == "thread-1"
    assert not (tmp_path / "codex" / "outside.jsonl").exists()
    assert tuple(sessions.rglob("*.jsonl")) == ()


def test_planner_uses_portable_fallback_target_when_thread_is_missing_everywhere(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    sessions.mkdir(parents=True)

    plan = build_sync_plan(
        LocalInventory((sessions,), {}, {}, 0),
        _remote_inventory(),
        ("thread-1",),
        tmp_path / "sync",
    )

    item = plan.items[0]
    assert item.state == "missing"
    assert item.action == "skip"
    assert item.local.path == sessions / "synced" / "thread-1.jsonl"
    assert item.source_relative_path == "synced/thread-1.jsonl"
    assert not item.local.path.exists()


def test_planner_rejects_discovered_local_path_outside_session_directory(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    sessions.mkdir(parents=True)
    outside_path = tmp_path / "outside.jsonl"
    outside_path.write_bytes(b"local")
    thread = replace(_thread("thread-1"), session_path=outside_path)

    plan = build_sync_plan(
        LocalInventory((sessions,), {"thread-1": thread}, {}, 1),
        _remote_inventory(),
        ("thread-1",),
        tmp_path / "sync",
    )

    assert plan.items[0].state == "issue"
    assert plan.items[0].action == "issue"
    assert plan.issues[-1].code == "unsafe_local_path"
    assert outside_path.read_bytes() == b"local"


def test_planner_prefers_discovered_local_path_over_remote_source_path(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    actual_path = sessions / "2026" / "07" / "13" / "actual.jsonl"
    actual_path.parent.mkdir(parents=True)
    actual_path.write_bytes(b"base+local")
    thread = replace(
        _thread("thread-1", project_key="local-project"),
        session_path=actual_path,
        project_label="Local Label",
        updated_at="2026-07-13T13:00:00Z",
    )
    sync_dir = tmp_path / "sync"
    remote_path = sync_dir / "tasks" / "thread-1.jsonl"
    remote_path.parent.mkdir(parents=True)
    remote_path.write_bytes(b"base")
    entry = replace(
        _remote_entry("thread-1"),
        source_relative_path="2026/06/01/duplicate.jsonl",
        project_key="remote-project",
        project_label="Remote Label",
        session_updated_at="2026-07-13T11:00:00Z",
        sha256=snapshot_file(remote_path).sha256,
        size_bytes=remote_path.stat().st_size,
    )
    remote = _one_thread_remote(entry, snapshot_file(remote_path))

    plan = build_sync_plan(
        LocalInventory(
            session_dirs=(sessions,),
            threads={"thread-1": thread},
            index_entries={},
            discovered_count=1,
        ),
        remote,
        ("thread-1",),
        sync_dir,
    )

    item = plan.items[0]
    assert item.local.path == actual_path
    assert item.state == "fast_forward_push"
    assert item.source_relative_path == "2026/07/13/actual.jsonl"
    assert item.project_key == "local-project"
    assert item.project_label == "Local Label"
    assert item.updated_at == "2026-07-13T13:00:00Z"
    assert not (sessions / "2026" / "06" / "01" / "duplicate.jsonl").exists()


@pytest.mark.parametrize(
    ("local_bytes", "remote_bytes", "expected_state"),
    [(b"same", b"same", "synced"), (b"left", b"rght", "conflict")],
)
def test_planner_uses_coherent_local_metadata_for_none_and_conflict(
    tmp_path: Path,
    local_bytes: bytes,
    remote_bytes: bytes,
    expected_state: str,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    local_path = sessions / "actual.jsonl"
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(local_bytes)
    local_thread = replace(
        _thread("thread-1", project_key="local-project"),
        session_path=local_path,
        project_label="Local Label",
        updated_at="2026-07-13T13:00:00Z",
    )
    sync_dir = tmp_path / "sync"
    remote_path = sync_dir / "tasks" / "thread-1.jsonl"
    remote_path.parent.mkdir(parents=True)
    remote_path.write_bytes(remote_bytes)
    remote_entry = replace(
        _remote_entry("thread-1", project_key="remote-project"),
        source_relative_path="remote/thread-1.jsonl",
        project_label="Remote Label",
        session_updated_at="2026-07-13T11:00:00Z",
    )

    plan = build_sync_plan(
        LocalInventory((sessions,), {"thread-1": local_thread}, {}, 1),
        _one_thread_remote(remote_entry, snapshot_file(remote_path)),
        ("thread-1",),
        sync_dir,
    )

    item = plan.items[0]
    assert item.state == expected_state
    assert (
        item.source_relative_path,
        item.project_key,
        item.project_label,
        item.updated_at,
    ) == ("actual.jsonl", "local-project", "Local Label", "2026-07-13T13:00:00Z")


def test_planner_uses_coherent_effective_remote_metadata_for_pull(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    local_path = sessions / "actual.jsonl"
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(b"base")
    local_thread = replace(
        _thread("thread-1", project_key="local-project"),
        session_path=local_path,
        project_label="Local Label",
        updated_at="2026-07-13T11:00:00Z",
        cwd=str(tmp_path / "remote-project"),
    )
    sync_dir = tmp_path / "sync"
    remote_path = sync_dir / "tasks" / "thread-1.jsonl"
    remote_path.parent.mkdir(parents=True)
    remote_path.write_bytes(b"base+remote")
    remote_entry = replace(
        _remote_entry("thread-1", project_key="remote-project"),
        source_relative_path="remote/thread-1.jsonl",
        project_label="Remote Label",
        session_updated_at="2026-07-13T13:00:00Z",
    )

    plan = build_sync_plan(
        LocalInventory(
            (sessions,),
            {"thread-1": local_thread},
            {},
            1,
            {"remote-project": (tmp_path / "remote-project",)},
        ),
        _one_thread_remote(remote_entry, snapshot_file(remote_path)),
        ("thread-1",),
        sync_dir,
    )

    item = plan.items[0]
    assert item.state == "fast_forward_pull"
    assert (
        item.source_relative_path,
        item.project_key,
        item.project_label,
        item.updated_at,
    ) == (
        "remote/thread-1.jsonl",
        "remote-project",
        "Remote Label",
        "2026-07-13T13:00:00Z",
    )


def test_selected_missing_remote_file_becomes_issue_item(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    sessions.mkdir(parents=True)
    sync_dir = tmp_path / "sync"
    entry = _remote_entry("thread-1")
    issue = SyncIssue("missing_remote_file", "Remote task is missing", "thread-1")
    remote = _one_thread_remote(
        entry,
        SyncFileSnapshot(path=sync_dir / entry.file, exists=False),
        issues=(issue,),
    )

    plan = build_sync_plan(
        LocalInventory((sessions,), {}, {}, 0),
        remote,
        ("thread-1",),
        sync_dir,
    )

    assert plan.items[0].state == "issue"
    assert plan.items[0].action == "issue"
    assert plan.items[0].expected_remote_entry == entry
    assert plan.issues == (issue,)
    assert plan.blocks_execution


def test_unselected_remote_issue_remains_visible_without_blocking_selected_work(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    local_path = sessions / "selected.jsonl"
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(b"local")
    selected = replace(_thread("selected"), session_path=local_path)
    issue = SyncIssue("missing_remote_file", "Remote task is missing", "other")
    remote = _remote_inventory()
    remote = replace(remote, issues=(issue,))

    plan = build_sync_plan(
        LocalInventory((sessions,), {"selected": selected}, {}, 1),
        remote,
        ("selected",),
        tmp_path / "sync",
    )

    assert plan.items[0].action == "push"
    assert plan.issues == (issue,)
    assert not plan.blocks_execution


def test_planner_uses_effective_metadata_and_persisted_expected_entry(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    sessions.mkdir(parents=True)
    sync_dir = tmp_path / "sync"
    remote_path = sync_dir / "tasks" / "thread-1.jsonl"
    remote_path.parent.mkdir(parents=True)
    remote_path.write_bytes(b"remote bytes")
    persisted = _remote_entry("thread-1", project_key="old")
    effective = replace(
        persisted,
        source_relative_path="synced/repaired.jsonl",
        project_key="new",
        project_label="New Label",
        session_updated_at="2026-07-13T14:00:00Z",
        sha256=snapshot_file(remote_path).sha256,
        size_bytes=remote_path.stat().st_size,
    )
    remote = _one_thread_remote(
        effective,
        snapshot_file(remote_path),
        persisted_entry=persisted,
        repaired=True,
    )

    plan = build_sync_plan(LocalInventory((sessions,), {}, {}, 0), remote, ("thread-1",), sync_dir)

    item = plan.items[0]
    assert item.expected_remote_entry == persisted
    assert item.remote == snapshot_file(remote_path)
    assert item.source_relative_path == "synced/repaired.jsonl"
    assert item.project_key == "new"
    assert item.project_label == "New Label"
    assert item.updated_at == "2026-07-13T14:00:00Z"
