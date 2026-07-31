from __future__ import annotations

import json
from pathlib import Path

from codex_usage.sync.constants import REMOTE_TRANSFER_FORMAT_VERSION
from codex_usage.sync.format_migration_layout import guard_task_file
from codex_usage.sync.models import (
    RemoteIndex,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
)
from codex_usage.sync.remote_inventory_probe import probe_remote_inventory
from codex_usage.sync.remote_reconciliation import materialize_selected_remote


def _write_session_meta(path: Path, thread_id: str, *, source: object) -> None:
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-31T12:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": thread_id,
                    "cwd": "/repo/demo",
                    "source": source,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _remote_entry(thread_id: str, file: str) -> RemoteThreadEntry:
    return RemoteThreadEntry(
        thread_id=thread_id,
        file=file,
        source_relative_path=f"2026/07/31/{thread_id}.jsonl",
        index_entry={"id": thread_id, "thread_name": "Review"},
        project_key="https://github.com/example/demo",
        project_label="demo",
        project_aliases=(),
        sha256="indexed-sha",
        size_bytes=1,
        session_updated_at="2026-07-31T12:00:00Z",
        exported_at="2026-07-31T12:00:00Z",
        source_machine_id="machine-a",
    )


def test_selected_remote_subagent_is_rejected_from_execution(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    path = root / "tasks" / "review.jsonl"
    path.parent.mkdir(parents=True)
    _write_session_meta(path, "review", source={"subagent": {"other": "review"}})
    entry = _remote_entry("review", "tasks/review.jsonl")
    index = RemoteIndex(REMOTE_TRANSFER_FORMAT_VERSION, "", {"review": entry})
    remote = RemoteInventory(index, index, SyncFileSnapshot(None, False), {}, (), ())

    materialized = materialize_selected_remote(
        root,
        remote,
        ("review",),
        lambda candidate: guard_task_file(root, candidate),
    )

    assert any(
        issue.code == "subagent_not_transferable" and issue.thread_id == "review"
        for issue in materialized.issues
    )


def test_unindexed_v3_metadata_probe_skips_hash_but_execution_probe_hashes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sync"
    path = root / "tasks" / "root.jsonl"
    path.parent.mkdir(parents=True)
    _write_session_meta(path, "root", source="cli")

    browse = probe_remote_inventory(root, metadata_only=True)
    execution = probe_remote_inventory(root)

    assert browse.files["root"].exists
    assert browse.files["root"].size_bytes == path.stat().st_size
    assert browse.files["root"].sha256 == ""
    assert len(execution.files["root"].sha256) == 64
