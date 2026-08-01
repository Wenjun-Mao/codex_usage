from __future__ import annotations

import hashlib
import json
from pathlib import Path

from codex_usage.models import SessionMetadata
from codex_usage.project_identity import ProjectIdentity, resolve_project_identity
from codex_usage.sync.constants import REMOTE_TRANSFER_FORMAT_VERSION
from codex_usage.sync.models import (
    RemoteIndex,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
)
from codex_usage.sync.remote_reconciliation import materialize_selected_remote

PROJECT_A = "https://github.com/example/project-a"
PROJECT_B = "https://github.com/example/project-b"
THREAD_ID = "same-session-id"


def resolved_repository_identity(repository: str) -> ProjectIdentity:
    return resolve_project_identity(
        SessionMetadata(
            session_id=THREAD_ID,
            file_path=Path("session.jsonl"),
            cwd="/remote/example-project",
            git_repository_url=repository,
        )
    )


def materialize_direct(
    root: Path,
    *,
    indexed_project: str,
    aliases: tuple[str, ...],
    actual_project: str,
    actual_cwd: str,
) -> RemoteInventory:
    path = root / "tasks" / f"{THREAD_ID}.jsonl"
    path.parent.mkdir(parents=True)
    contents = session_bytes(THREAD_ID, actual_project, actual_cwd)
    path.write_bytes(contents)
    entry = remote_entry(
        indexed_project=indexed_project,
        aliases=aliases,
        contents=contents,
    )
    index = RemoteIndex(REMOTE_TRANSFER_FORMAT_VERSION, "", {THREAD_ID: entry})
    inventory = RemoteInventory(
        persisted_index=index,
        index=index,
        index_snapshot=SyncFileSnapshot(None, False),
        files={},
        repaired_thread_ids=(),
        issues=(),
    )
    return materialize_selected_remote(
        root,
        inventory,
        (THREAD_ID,),
        lambda candidate: None,
    )


def remote_entry(
    *,
    indexed_project: str,
    aliases: tuple[str, ...],
    contents: bytes,
) -> RemoteThreadEntry:
    return RemoteThreadEntry(
        thread_id=THREAD_ID,
        file=f"tasks/{THREAD_ID}.jsonl",
        source_relative_path=f"synced/{THREAD_ID}.jsonl",
        index_entry={"id": THREAD_ID},
        project_key=indexed_project,
        project_label="indexed project",
        project_aliases=aliases,
        sha256=hashlib.sha256(contents).hexdigest(),
        size_bytes=len(contents),
        session_updated_at="2026-07-31T12:00:00Z",
        exported_at="2026-07-31T12:00:00Z",
        source_machine_id="source",
    )


def session_bytes(thread_id: str, repository_url: str, cwd: str) -> bytes:
    payload: dict[str, object] = {
        "id": thread_id,
        "timestamp": "2026-07-31T12:00:00Z",
        "cwd": cwd,
        "source": "cli",
    }
    if repository_url:
        payload["git"] = {"repository_url": repository_url}
    row = {
        "timestamp": "2026-07-31T12:00:00Z",
        "type": "session_meta",
        "payload": payload,
    }
    return (json.dumps(row, separators=(",", ":")) + "\n").encode()
