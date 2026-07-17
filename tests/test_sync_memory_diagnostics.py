from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import codex_usage.sync.planner as sync_planner
import codex_usage.sync.state as sync_state
from codex_usage.sync.constants import REMOTE_TRANSFER_FORMAT_VERSION
from codex_usage.sync.models import (
    LocalInventory,
    ProjectResolutionRequest,
    RemoteIndex,
    RemoteInventory,
    SyncFileSnapshot,
)
from codex_usage.sync.planner import build_sync_plan
from codex_usage.sync.state import memory_database_row_counts
from codex_usage.threads import ThreadInfo


def _thread(thread_id: str, session_path: Path) -> ThreadInfo:
    return ThreadInfo(
        thread_id=thread_id,
        title=thread_id,
        updated_at="2026-07-13T12:00:00Z",
        session_path=session_path,
        project_key="repo",
        project_label="repo",
        project_aliases=(),
        total_tokens=0,
        session_bytes=0,
        estimated_sync_bytes=4096,
    )


def _remote_inventory() -> RemoteInventory:
    index = RemoteIndex(
        format_version=REMOTE_TRANSFER_FORMAT_VERSION,
        updated_at="",
        threads={},
    )
    return RemoteInventory(
        persisted_index=index,
        index=index,
        index_snapshot=SyncFileSnapshot(path=None, exists=False),
        files={},
        repaired_thread_ids=(),
        issues=(),
    )


def test_planner_reports_memory_rows_without_writing_database_or_state(
    tmp_path: Path,
) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    local_path = sessions / "thread-1.jsonl"
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(b"local")
    database_path = home / "state_5.sqlite"
    connection = sqlite3.connect(database_path)
    connection.execute("create table stage1_outputs (thread_id text)")
    connection.execute("insert into stage1_outputs values (?)", ("thread-1",))
    connection.commit()
    connection.close()
    database_before = database_path.read_bytes()
    sync_dir = tmp_path / "sync"

    plan = build_sync_plan(
        LocalInventory(
            (sessions,),
            {"thread-1": _thread("thread-1", local_path)},
            {},
            1,
        ),
        _remote_inventory(),
        ("thread-1",),
        sync_dir,
        project_resolution=ProjectResolutionRequest(),
    )

    assert plan.items[0].memory_database_rows == 1
    assert database_path.read_bytes() == database_before
    assert not (home / ".codex-sync-state").exists()


def test_planner_batches_memory_diagnostics_once_per_codex_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    threads: dict[str, ThreadInfo] = {}
    for thread_id in ("thread-1", "thread-2"):
        path = sessions / f"{thread_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(thread_id.encode())
        threads[thread_id] = _thread(thread_id, path)
    database_path = home / "state_5.sqlite"
    connection = sqlite3.connect(database_path)
    connection.execute("create table stage1_outputs (thread_id text)")
    connection.executemany(
        "insert into stage1_outputs values (?)",
        [("thread-1",), ("thread-1",), ("thread-2",)],
    )
    connection.commit()
    connection.close()
    original_batch = sync_state.memory_database_row_counts
    original_snapshot = sync_state._snapshot_memory_database
    original_copy = sync_state.atomic_copy
    api_calls: list[tuple[Path, tuple[str, ...]]] = []
    snapshot_calls = 0
    copy_calls = 0

    def tracking_batch(
        session_dir: Path,
        thread_ids: tuple[str, ...],
    ) -> dict[str, int]:
        api_calls.append((session_dir, thread_ids))
        return original_batch(session_dir, thread_ids)

    def tracking_snapshot(database: Path, snapshot_dir: Path) -> Path:
        nonlocal snapshot_calls
        snapshot_calls += 1
        return original_snapshot(database, snapshot_dir)

    def tracking_copy(
        source: Path,
        target: Path,
        **kwargs: object,
    ) -> SyncFileSnapshot:
        nonlocal copy_calls
        copy_calls += 1
        return original_copy(source, target, **kwargs)

    monkeypatch.setattr(sync_planner, "memory_database_row_counts", tracking_batch)
    monkeypatch.setattr(sync_state, "_snapshot_memory_database", tracking_snapshot)
    monkeypatch.setattr(sync_state, "atomic_copy", tracking_copy)

    plan = build_sync_plan(
        LocalInventory((sessions,), threads, {}, 2),
        _remote_inventory(),
        ("thread-1", "thread-2"),
        tmp_path / "sync",
        project_resolution=ProjectResolutionRequest(),
    )

    assert {item.thread_id: item.memory_database_rows for item in plan.items} == {
        "thread-1": 2,
        "thread-2": 1,
    }
    assert api_calls == [(sessions, ("thread-1", "thread-2"))]
    assert snapshot_calls == 1
    assert copy_calls == 1


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
    live_paths = tuple(
        Path(f"{database_path}{suffix}") for suffix in ("", "-wal", "-shm")
    )
    before = {path: (path.exists(), path.read_bytes()) for path in live_paths}
    original_connect = sqlite3.connect
    opened_databases: list[str] = []

    def tracking_connect(
        database: object,
        *args: object,
        **kwargs: object,
    ) -> sqlite3.Connection:
        opened_databases.append(str(database))
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sync_state.sqlite3, "connect", tracking_connect)
    try:
        row_count = memory_database_row_counts(sessions, ("thread-1",))["thread-1"]
    finally:
        after = {path: (path.exists(), path.read_bytes()) for path in live_paths}
        connection.close()

    assert row_count == 1
    assert after == before
    assert all(
        database_path.resolve().as_uri() not in opened
        for opened in opened_databases
    )


def test_memory_database_diagnostic_tolerates_missing_schema(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    database_path = tmp_path / "codex" / "state_5.sqlite"
    database_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(database_path)
    connection.execute("create table unrelated (value text)")
    connection.close()

    assert memory_database_row_counts(sessions, ("thread-1",)) == {"thread-1": 0}
