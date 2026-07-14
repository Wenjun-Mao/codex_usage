from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from codex_usage.session_cache import load_cached_session_data
import codex_usage.sync.inventory as inventory
import codex_usage.sync.planner as sync_planner
import codex_usage.sync.state as sync_state
from codex_usage.sync.inventory import build_local_inventory, resolve_selected_thread_ids
from codex_usage.sync.io import snapshot_file
from codex_usage.sync.models import (
    LocalInventory,
    LocalSyncState,
    RemoteIndex,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
    SyncIssue,
    SyncPlan,
    SyncPlanItem,
)
from codex_usage.sync.planner import build_sync_plan, classify_snapshots
from codex_usage.sync.state import (
    LocalStateStore,
    backup_local_session,
    memory_database_row_count,
    merge_session_index,
    save_conflict_candidate,
    sync_dir_fingerprint,
)
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
        file=f"conversations/{thread_id}.jsonl",
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
    index = RemoteIndex(format_version=2, updated_at="", threads={item.thread_id: item for item in entries})
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
        persisted_index=RemoteIndex(2, "", {persisted.thread_id: persisted}),
        index=RemoteIndex(2, "", {effective_entry.thread_id: effective_entry}),
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


def _plan_item(tmp_path: Path, *, state: str = "synced", action: str = "none") -> SyncPlanItem:
    missing = SyncFileSnapshot(path=tmp_path / "missing.jsonl", exists=False)
    return SyncPlanItem(
        thread_id="thread-1",
        state=state,
        action=action,
        reason="test",
        local=missing,
        remote=missing,
        base_sha256="",
        updated_at="2026-07-13T12:00:00Z",
        source_relative_path="synced/thread-1.jsonl",
        project_key="repo",
        project_label="Repo",
        memory_database_rows=0,
        expected_remote_entry=None,
    )


def _local_state(sync_dir: Path, thread_id: str = "thread-1") -> LocalSyncState:
    return LocalSyncState(
        thread_id=thread_id,
        sync_dir_fingerprint=sync_dir_fingerprint(sync_dir),
        base_sha256="abc",
        base_size_bytes=3,
        base_updated_at="2026-07-13T12:00:00Z",
        last_remote_sha256="abc",
        last_local_sha256="abc",
        source_relative_path=f"synced/{thread_id}.jsonl",
        project_key="repo",
        project_label="repo",
        synced_at="2026-07-13T12:00:01Z",
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


@pytest.mark.parametrize(
    ("state", "action"),
    [("issue", "push"), ("synced", "issue")],
)
def test_sync_plan_requires_issue_state_and_action_together(
    tmp_path: Path,
    state: str,
    action: str,
) -> None:
    item = _plan_item(tmp_path, state=state, action=action)

    with pytest.raises(ValueError, match="state and action must both be 'issue'"):
        SyncPlan(
            items=(item,),
            issues=(SyncIssue("test", "test", item.thread_id),),
            discovered_count=1,
            remote_count=0,
            selected_count=1,
        )


def test_sync_plan_has_one_selected_execution_gate(tmp_path: Path) -> None:
    diagnostic = SyncIssue("warning", "visible but unselected", "other")
    clear = SyncPlan((_plan_item(tmp_path),), (diagnostic,), 1, 0, 1)
    conflict = SyncPlan((_plan_item(tmp_path, state="conflict", action="conflict"),), (), 1, 0, 1)
    issue_item = _plan_item(tmp_path, state="issue", action="issue")
    issue = SyncPlan((issue_item,), (SyncIssue("test", "selected", "thread-1"),), 1, 0, 1)

    assert clear.has_issues
    assert not clear.blocks_execution
    assert conflict.blocks_execution
    assert issue.blocks_execution
    assert not hasattr(clear, "has_blocking_issues")


def test_planner_rejects_remote_path_traversal_without_mutating_local_files(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    sessions.mkdir(parents=True)
    sync_dir = tmp_path / "sync"
    remote_path = sync_dir / "conversations" / "thread-1.jsonl"
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
    remote_path = sync_dir / "conversations" / "thread-1.jsonl"
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
    remote_path = sync_dir / "conversations" / "thread-1.jsonl"
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
    )
    sync_dir = tmp_path / "sync"
    remote_path = sync_dir / "conversations" / "thread-1.jsonl"
    remote_path.parent.mkdir(parents=True)
    remote_path.write_bytes(b"base+remote")
    remote_entry = replace(
        _remote_entry("thread-1", project_key="remote-project"),
        source_relative_path="remote/thread-1.jsonl",
        project_label="Remote Label",
        session_updated_at="2026-07-13T13:00:00Z",
    )

    plan = build_sync_plan(
        LocalInventory((sessions,), {"thread-1": local_thread}, {}, 1),
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
    issue = SyncIssue("missing_remote_file", "Remote conversation is missing", "thread-1")
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
    issue = SyncIssue("missing_remote_file", "Remote conversation is missing", "other")
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
    remote_path = sync_dir / "conversations" / "thread-1.jsonl"
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


def test_planner_reports_memory_rows_without_writing_database_or_state(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    local_path = sessions / "thread-1.jsonl"
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(b"local")
    db_path = home / "state_5.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute("create table stage1_outputs (thread_id text)")
    connection.execute("insert into stage1_outputs values (?)", ("thread-1",))
    connection.commit()
    connection.close()
    database_before = db_path.read_bytes()
    thread = replace(_thread("thread-1"), session_path=local_path)
    sync_dir = tmp_path / "sync"

    plan = build_sync_plan(
        LocalInventory((sessions,), {"thread-1": thread}, {}, 1),
        _remote_inventory(),
        ("thread-1",),
        sync_dir,
    )

    assert plan.items[0].memory_database_rows == 1
    assert db_path.read_bytes() == database_before
    assert not (home / ".codex-sync-state").exists()


def test_memory_database_diagnostic_reads_wal_snapshot_without_opening_live_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    database_path = tmp_path / "codex" / "state_5.sqlite"
    database_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(database_path)
    assert connection.execute("pragma journal_mode=wal").fetchone() == ("wal",)
    connection.execute("pragma wal_autocheckpoint=0")
    connection.execute("create table stage1_outputs (thread_id text)")
    connection.commit()
    connection.execute("pragma wal_checkpoint(truncate)")
    connection.execute("insert into stage1_outputs values (?)", ("thread-1",))
    connection.commit()
    live_paths = tuple(Path(f"{database_path}{suffix}") for suffix in ("", "-wal", "-shm"))
    before = {path: (path.exists(), path.read_bytes()) for path in live_paths}
    original_connect = sqlite3.connect
    opened_databases: list[str] = []

    def tracking_connect(database: object, *args: object, **kwargs: object) -> sqlite3.Connection:
        opened_databases.append(str(database))
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sync_state.sqlite3, "connect", tracking_connect)
    try:
        row_count = memory_database_row_count(sessions, "thread-1")
    finally:
        after = {path: (path.exists(), path.read_bytes()) for path in live_paths}
        connection.close()

    assert row_count == 1
    assert after == before
    assert all(database_path.resolve().as_uri() not in opened for opened in opened_databases)


def test_local_state_store_namespaces_records_by_sync_folder(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    first_sync = tmp_path / "first-sync"
    second_sync = tmp_path / "second-sync"
    first_store = LocalStateStore(sessions, first_sync)
    second_store = LocalStateStore(sessions, second_sync)
    state = _local_state(first_sync)

    first_store.write(state)

    assert first_store.read("thread-1") == state
    assert second_store.read("thread-1") is None
    assert first_store.path_for("thread-1") != second_store.path_for("thread-1")
    with pytest.raises(ValueError, match="different sync folder"):
        second_store.write(state)


def test_local_sync_state_requires_exact_v2_version(tmp_path: Path) -> None:
    state = _local_state(tmp_path / "sync")
    valid = state.to_dict()

    assert LocalSyncState.from_dict(valid) == state
    for version in (None, 1, 3):
        payload = dict(valid)
        if version is None:
            payload.pop("sync_version")
        else:
            payload["sync_version"] = version
        assert LocalSyncState.from_dict(payload) is None


def test_local_state_store_rejects_record_for_different_requested_thread(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    sync_dir = tmp_path / "sync"
    store = LocalStateStore(sessions, sync_dir)
    path = store.path_for("requested")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_local_state(sync_dir, "other").to_dict()))

    assert store.read("requested") is None


@pytest.mark.parametrize(
    ("local_value", "remote_value", "expected_base"),
    [(b"local", b"remote", b"local"), (None, b"remote", b"remote")],
)
def test_local_state_store_record_success_persists_fields_and_selects_base(
    tmp_path: Path,
    local_value: bytes | None,
    remote_value: bytes | None,
    expected_base: bytes,
) -> None:
    sync_dir = tmp_path / "sync"
    store = LocalStateStore(tmp_path / "codex" / "sessions", sync_dir)
    local = _snapshot_bytes(tmp_path, "local-state.jsonl", local_value)
    remote = _snapshot_bytes(tmp_path, "remote-state.jsonl", remote_value)
    item = replace(
        _plan_item(tmp_path),
        local=local,
        remote=remote,
        updated_at="2026-07-13T15:00:00Z",
        source_relative_path="2026/07/13/thread-1.jsonl",
        project_key="project-key",
        project_label="Project Label",
    )

    store.record_success(item, local, remote)

    state = store.read("thread-1")
    assert state is not None
    assert state.sync_dir_fingerprint == sync_dir_fingerprint(sync_dir)
    assert state.base_sha256 == hashlib.sha256(expected_base).hexdigest()
    assert state.base_size_bytes == len(expected_base)
    assert state.base_updated_at == "2026-07-13T15:00:00Z"
    assert state.last_local_sha256 == local.sha256
    assert state.last_remote_sha256 == remote.sha256
    assert state.source_relative_path == "2026/07/13/thread-1.jsonl"
    assert state.project_key == "project-key"
    assert state.project_label == "Project Label"
    assert state.synced_at


def test_local_state_store_ignores_malformed_base_record(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    store = LocalStateStore(sessions, tmp_path / "sync")
    store.path_for("thread-1").parent.mkdir(parents=True)
    store.path_for("thread-1").write_text(
        json.dumps(
            {
                "thread_id": "thread-1",
                "sync_dir_fingerprint": sync_dir_fingerprint(tmp_path / "sync"),
                "base_sha256": "abc",
                "base_size_bytes": "not-an-integer",
            }
        )
    )

    assert store.read("thread-1") is None


def test_local_backup_and_conflict_candidate_preserve_original_bytes(tmp_path: Path) -> None:
    local_path = tmp_path / "sessions" / "local.jsonl"
    remote_path = tmp_path / "sync" / "conversations" / "remote.jsonl"
    local_path.parent.mkdir(parents=True)
    remote_path.parent.mkdir(parents=True)
    local_path.write_bytes(b"local before replace")
    remote_path.write_bytes(b"remote conflict")
    backup_dir = tmp_path / "backups" / "run"

    local_backup = backup_local_session(local_path, backup_dir, "thread/unsafe")
    conflict_backup = save_conflict_candidate(remote_path, backup_dir, "thread/unsafe")
    local_path.write_bytes(b"local after replace")

    assert local_backup.read_bytes() == b"local before replace"
    assert conflict_backup.read_bytes() == b"remote conflict"
    assert backup_dir in local_backup.parents
    assert backup_dir in conflict_backup.parents


def test_session_index_merge_keeps_newest_entry_and_backs_up_original(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    index_path = tmp_path / "codex" / "session_index.jsonl"
    index_path.parent.mkdir(parents=True)
    original = {"id": "thread-1", "thread_name": "old", "updated_at": "2026-07-13T10:00:00Z"}
    newer = {"id": "thread-1", "thread_name": "new", "updated_at": "2026-07-13T12:00:00Z"}
    other = {"id": "thread-2", "thread_name": "other", "updated_at": "2026-07-13T11:00:00Z"}
    original_bytes = (json.dumps(original) + "\n").encode()
    index_path.write_bytes(original_bytes)
    backup_dir = tmp_path / "backups" / "run"

    merge_session_index(sessions, [newer, other], backup_dir)

    rows = [json.loads(line) for line in index_path.read_text().splitlines()]
    assert rows == [other, newer]
    assert (backup_dir / "session_index.jsonl").read_bytes() == original_bytes


def test_memory_database_diagnostic_tolerates_missing_schema(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    db_path = tmp_path / "codex" / "state_5.sqlite"
    db_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(db_path)
    connection.execute("create table unrelated (value text)")
    connection.close()

    assert memory_database_row_count(sessions, "thread-1") == 0


def test_project_selection_unions_local_and_remote_threads() -> None:
    local = _local_inventory(
        _thread("local", project_key="https://github.com/example/demo", aliases=("/repo/demo",))
    )
    remote = _remote_inventory(
        _remote_entry("remote", project_key="https://github.com/example/demo")
    )

    selected = resolve_selected_thread_ids(
        local,
        remote,
        project_keys=["https://github.com/example/demo"],
        thread_ids=[],
    )

    assert selected == ("local", "remote")


def test_explicit_selection_is_exact_even_when_projects_are_available() -> None:
    local = _local_inventory(_thread("chosen"), _thread("not-chosen"))

    assert resolve_selected_thread_ids(local, _remote_inventory(), [], ["chosen"]) == ("chosen",)


def test_explicit_selection_preserves_unknown_case_sensitive_ids_and_ignores_project_matches() -> None:
    local = _local_inventory(_thread("local", project_key="/repo/demo"))
    remote = _remote_inventory(_remote_entry("remote", project_key="/repo/demo"))

    assert resolve_selected_thread_ids(local, remote, ["/repo/demo"], ["Missing", "local", "Missing"]) == (
        "Missing",
        "local",
    )


def test_project_selection_normalizes_aliases_and_orders_deduplicated_union() -> None:
    local = _local_inventory(
        _thread("z-local", aliases=("https://github.com/example/demo.git",)),
        _thread("a-local", aliases=("https://github.com/example/demo",)),
        _thread("shared", aliases=("https://github.com/example/demo",)),
    )
    remote = _remote_inventory(
        replace(_remote_entry("z-remote"), project_aliases=("https://github.com/example/demo",)),
        replace(_remote_entry("a-remote"), project_aliases=("https://github.com/example/demo",)),
        replace(_remote_entry("shared"), project_aliases=("https://github.com/example/demo",)),
    )

    assert resolve_selected_thread_ids(local, remote, ["Example/Demo"], []) == (
        "a-local",
        "shared",
        "z-local",
        "a-remote",
        "z-remote",
    )


def test_rebuilding_inventory_discovers_new_project_threads(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    cache_dir = tmp_path / "cache"
    _write_session(sessions, "original", "/repo/demo")
    first_inventory = build_local_inventory(
        load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    )
    _write_session(sessions, "new", "/repo/demo")
    rebuilt_inventory = build_local_inventory(
        load_cached_session_data([sessions], cache_dir=cache_dir, auto_transitions=False)
    )

    assert resolve_selected_thread_ids(first_inventory, _remote_inventory(), ["/repo/demo"], []) == ("original",)
    assert resolve_selected_thread_ids(rebuilt_inventory, _remote_inventory(), ["/repo/demo"], []) == (
        "new",
        "original",
    )
    assert first_inventory.discovered_count == 1
    assert rebuilt_inventory.discovered_count == 2


def test_build_inventory_lists_cached_threads_once(tmp_path: Path, monkeypatch: object) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "thread-1", "/repo/demo")
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache", auto_transitions=False)
    original = inventory.list_threads_from_cached_data
    calls = 0

    def list_once(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(inventory, "list_threads_from_cached_data", list_once)

    built = build_local_inventory(data)

    assert calls == 1
    assert tuple(built.threads) == ("thread-1",)


def _write_session(sessions: Path, session_id: str, cwd: str) -> None:
    day = sessions / "2026" / "07" / "13"
    day.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp": "2026-07-13T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": session_id, "timestamp": "2026-07-13T12:00:00Z", "cwd": cwd},
        }
    ]
    (day / f"{session_id}.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
