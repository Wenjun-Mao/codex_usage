from __future__ import annotations

import errno
import json
from pathlib import Path

import pytest

from codex_usage.sync.constants import REMOTE_TRANSFER_FORMAT_VERSION
from codex_usage.sync.format_migration_layout import guard_task_file
from codex_usage.sync.models import (
    RemoteIndex,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
)
from codex_usage.sync.remote_inventory_probe import probe_remote_inventory
from codex_usage.sync.remote_reconciliation import (
    materialize_remote_metadata_for_selection,
    materialize_selected_remote,
)

_TRANSFER_METADATA_HEADER_READ_LIMIT = 1024 * 1024


def _write_session_meta(
    path: Path,
    thread_id: str | None,
    *,
    source: object,
) -> None:
    payload: dict[str, object] = {
        "cwd": "/repo/demo",
        "source": source,
    }
    if thread_id is not None:
        payload["id"] = thread_id
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-31T12:00:00Z",
                "type": "session_meta",
                "payload": payload,
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


def test_selected_unindexed_remote_subagent_is_rejected_from_execution(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sync"
    path = root / "tasks" / "review.jsonl"
    path.parent.mkdir(parents=True)
    _write_session_meta(path, "review", source={"subagent": {"other": "review"}})
    remote = probe_remote_inventory(root)

    materialized = materialize_selected_remote(
        root,
        remote,
        ("review",),
        lambda candidate: guard_task_file(root, candidate),
    )

    assert len(remote.files["review"].sha256) == 64
    assert any(
        issue.code == "subagent_not_transferable" and issue.thread_id == "review"
        for issue in materialized.issues
    )


def test_indexed_metadata_browse_retries_transient_session_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sync"
    path = root / "tasks" / "review.jsonl"
    path.parent.mkdir(parents=True)
    _write_session_meta(path, "review", source="cli")
    entry = _remote_entry("review", "tasks/review.jsonl")
    index = RemoteIndex(REMOTE_TRANSFER_FORMAT_VERSION, "", {"review": entry})
    remote = RemoteInventory(index, index, SyncFileSnapshot(None, False), {}, (), ())
    original_open = Path.open
    attempts = 0

    def flaky_open(candidate: Path, *args: object, **kwargs: object):
        nonlocal attempts
        if candidate == path:
            attempts += 1
            if attempts < 3:
                raise OSError(errno.EBUSY, "remote metadata is busy")
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)

    materialized = materialize_remote_metadata_for_selection(root, remote)

    assert attempts == 3
    assert materialized.files["review"].exists
    assert materialized.issues == ()


def test_unindexed_metadata_probe_retries_transient_session_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sync"
    path = root / "tasks" / "review.jsonl"
    path.parent.mkdir(parents=True)
    _write_session_meta(path, "review", source="cli")
    original_open = Path.open
    attempts = 0

    def flaky_open(candidate: Path, *args: object, **kwargs: object):
        nonlocal attempts
        if candidate == path:
            attempts += 1
            if attempts < 3:
                raise OSError(errno.EBUSY, "remote metadata is busy")
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)

    browse = probe_remote_inventory(root, metadata_only=True)

    assert attempts == 3
    assert browse.files["review"].exists
    assert browse.issues == ()


def test_indexed_metadata_browse_rejects_missing_explicit_id(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    path = root / "tasks" / "review.jsonl"
    path.parent.mkdir(parents=True)
    _write_session_meta(path, None, source="cli")
    entry = _remote_entry("review", "tasks/review.jsonl")
    index = RemoteIndex(REMOTE_TRANSFER_FORMAT_VERSION, "", {"review": entry})
    remote = RemoteInventory(index, index, SyncFileSnapshot(None, False), {}, (), ())

    materialized = materialize_remote_metadata_for_selection(root, remote)

    assert materialized.files == {}
    assert len(materialized.issues) == 1
    assert materialized.issues[0].code == "unindexed_unreadable"
    assert materialized.issues[0].thread_id == "review"


def test_unindexed_metadata_probe_rejects_missing_explicit_id(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    path = root / "tasks" / "missing-id.jsonl"
    path.parent.mkdir(parents=True)
    _write_session_meta(path, None, source="cli")

    browse = probe_remote_inventory(root, metadata_only=True)

    assert browse.index.threads == {}
    assert browse.files == {}
    assert len(browse.issues) == 1
    assert browse.issues[0].code == "unindexed_unreadable"


def test_remote_metadata_browse_does_not_scan_past_bounded_header(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sync"
    path = root / "tasks" / "late-metadata.jsonl"
    path.parent.mkdir(parents=True)
    late_metadata = json.dumps(
        {
            "timestamp": "2026-07-31T12:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "late-metadata",
                "cwd": "/repo/demo",
                "source": "cli",
            },
        }
    ).encode()
    path.write_bytes(
        b'{"type":"event_msg","payload":{}}\n'
        + b"x" * (_TRANSFER_METADATA_HEADER_READ_LIMIT + 1)
        + b"\n"
        + late_metadata
        + b"\n"
    )

    browse = probe_remote_inventory(root, metadata_only=True)

    assert browse.index.threads == {}
    assert browse.files == {}
    assert [issue.code for issue in browse.issues] == ["unindexed_unreadable"]


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
