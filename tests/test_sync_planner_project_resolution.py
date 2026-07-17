from __future__ import annotations

from pathlib import Path

import pytest

from codex_usage.sync.constants import REMOTE_TRANSFER_FORMAT_VERSION
from codex_usage.sync.io import snapshot_file
from codex_usage.sync.models import (
    LocalInventory,
    ProjectResolutionRequest,
    RemoteIndex,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
)
from codex_usage.sync.planner import build_sync_plan
from codex_usage.threads import ThreadInfo


THREAD_ID = "task-1"


def test_pull_keeps_existing_counterpart_symlink_cwd_despite_metadata_mismatch(
    tmp_path: Path,
) -> None:
    actual_root = tmp_path / "actual-root"
    linked_root = tmp_path / "linked-root"
    actual_root.mkdir()
    try:
        linked_root.symlink_to(actual_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    sessions_dir = tmp_path / "codex" / "sessions"
    local_session = sessions_dir / "local.jsonl"
    local_session.parent.mkdir(parents=True)
    local_session.write_bytes(b"base")
    sync_dir = tmp_path / "sync"
    remote_session = sync_dir / "tasks" / f"{THREAD_ID}.jsonl"
    remote_session.parent.mkdir(parents=True)
    remote_session.write_bytes(b"base+remote")

    local_thread = ThreadInfo(
        thread_id=THREAD_ID,
        title="Local task",
        updated_at="2026-07-16T12:00:00Z",
        session_path=local_session,
        project_key="d:/local-machine/project",
        project_label="project",
        project_aliases=(),
        total_tokens=0,
        session_bytes=4,
        estimated_sync_bytes=4100,
        cwd=str(linked_root),
    )
    remote_entry = RemoteThreadEntry(
        thread_id=THREAD_ID,
        file=f"tasks/{THREAD_ID}.jsonl",
        source_relative_path=f"synced/{THREAD_ID}.jsonl",
        index_entry={"id": THREAD_ID},
        project_key="c:/remote-machine/project",
        project_label="project",
        project_aliases=("c:/remote-machine/project",),
        sha256="remote-sha",
        size_bytes=11,
        session_updated_at="2026-07-16T12:00:00Z",
        exported_at="2026-07-16T12:00:00Z",
        source_machine_id="source",
    )
    index = RemoteIndex(
        format_version=REMOTE_TRANSFER_FORMAT_VERSION,
        updated_at="2026-07-16T12:00:00Z",
        threads={THREAD_ID: remote_entry},
    )
    local_inventory = LocalInventory(
        session_dirs=(sessions_dir,),
        threads={THREAD_ID: local_thread},
        index_entries={},
        discovered_count=1,
    )
    remote_inventory = RemoteInventory(
        persisted_index=index,
        index=index,
        index_snapshot=SyncFileSnapshot(path=None, exists=False),
        files={THREAD_ID: snapshot_file(remote_session)},
        repaired_thread_ids=(),
        issues=(),
    )

    plan = build_sync_plan(
        local_inventory,
        remote_inventory,
        (THREAD_ID,),
        sync_dir,
        project_resolution=ProjectResolutionRequest(),
    )
    item = plan.items[0]

    assert (item.state, item.action) == ("fast_forward_pull", "pull")
    assert item.local_project_root == linked_root
    assert str(item.local_project_root) == str(linked_root)
    assert plan.issues == ()
