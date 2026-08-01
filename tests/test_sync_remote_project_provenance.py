from __future__ import annotations

import hashlib
import json
from pathlib import Path

from codex_usage.project_identity import normalize_project_key
from codex_usage.sync.constants import REMOTE_TRANSFER_FORMAT_VERSION
from codex_usage.sync.local_session_probe import load_local_transfer_probe
from codex_usage.sync.models import (
    LocalInventory,
    ProjectResolutionRequest,
    RemoteIndex,
    RemoteInventory,
    RemoteThreadEntry,
    SyncFileSnapshot,
)
from codex_usage.sync.remote_reconciliation import materialize_selected_remote
from codex_usage.sync.runner import pull_sync, push_sync, sync_status

PROJECT_A = "https://github.com/example/project-a"
PROJECT_B = "https://github.com/example/project-b"
THREAD_ID = "same-session-id"


def test_status_blocks_selected_remote_with_mismatched_project_provenance(
    tmp_path: Path,
) -> None:
    sync_dir = tmp_path / "sync"
    remote_path = _write_remote_store(
        sync_dir,
        indexed_project=PROJECT_A,
        actual_project=PROJECT_B,
    )
    remote_before = remote_path.read_bytes()
    index_before = (sync_dir / "sync-index.json").read_bytes()

    plan = sync_status(
        local=_empty_local(tmp_path / "target-home" / "sessions"),
        sync_dir=sync_dir,
        thread_ids=(THREAD_ID,),
        project_resolution=ProjectResolutionRequest(),
    )

    issue = next(
        issue
        for issue in plan.issues
        if issue.code == "remote_project_identity_mismatch"
    )
    assert issue.thread_id == THREAD_ID
    assert PROJECT_A not in issue.message
    assert PROJECT_B not in issue.message
    assert plan.items[0].action == "issue"
    assert remote_path.read_bytes() == remote_before
    assert (sync_dir / "sync-index.json").read_bytes() == index_before


def test_pull_blocks_mismatched_remote_before_creating_new_local_task(
    tmp_path: Path,
) -> None:
    sync_dir = tmp_path / "sync"
    _write_remote_store(
        sync_dir,
        indexed_project=PROJECT_A,
        actual_project=PROJECT_B,
    )
    target_home = tmp_path / "target-home"
    target_project = tmp_path / "target-project"
    _write_git_origin(target_project, PROJECT_A)
    local = _empty_local(target_home / "sessions")

    result = pull_sync(
        local=local,
        sync_dir=sync_dir,
        thread_ids=(THREAD_ID,),
        project_resolution=ProjectResolutionRequest(
            candidate_roots=(target_project,)
        ),
        project_key=PROJECT_A,
    )

    assert result.outcome == "issue"
    assert [issue.code for issue in result.issues] == [
        "remote_project_identity_mismatch"
    ]
    assert result.pulled == ()
    assert not (target_home / "sessions" / "synced" / f"{THREAD_ID}.jsonl").exists()


def test_pull_blocks_mismatched_remote_before_replacing_existing_counterpart(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / "source-home"
    sessions = source_home / "sessions"
    source_project = tmp_path / "source-project"
    _write_git_origin(source_project, PROJECT_A)
    local_path = _write_local_session(sessions, source_project)
    local = load_local_transfer_probe([sessions]).inventory
    sync_dir = tmp_path / "sync"
    pushed = push_sync(
        local=local,
        sync_dir=sync_dir,
        thread_ids=(THREAD_ID,),
        machine_id="source",
        project_key=PROJECT_A,
    )
    assert pushed.outcome == "completed"
    assert pushed.pushed == (THREAD_ID,)

    remote_path = sync_dir / "tasks" / f"{THREAD_ID}.jsonl"
    remote_path.write_bytes(_session_bytes(THREAD_ID, PROJECT_B, "/remote/project-b"))
    local_before = local_path.read_bytes()
    index_before = (sync_dir / "sync-index.json").read_bytes()

    result = pull_sync(
        local=local,
        sync_dir=sync_dir,
        thread_ids=(THREAD_ID,),
        project_resolution=ProjectResolutionRequest(),
        project_key=PROJECT_A,
    )

    assert result.outcome == "issue"
    assert [issue.code for issue in result.issues] == [
        "remote_project_identity_mismatch"
    ]
    assert result.pulled == ()
    assert local_path.read_bytes() == local_before
    assert (sync_dir / "sync-index.json").read_bytes() == index_before


def test_selected_remote_accepts_actual_project_matching_index_alias(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sync"
    path = root / "tasks" / f"{THREAD_ID}.jsonl"
    path.parent.mkdir(parents=True)
    actual_path_identity = normalize_project_key(str(tmp_path / "retired-checkout"))
    contents = _session_bytes(THREAD_ID, "", actual_path_identity)
    path.write_bytes(contents)
    entry = _remote_entry(
        indexed_project=PROJECT_A,
        aliases=(actual_path_identity,),
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

    materialized = materialize_selected_remote(
        root,
        inventory,
        (THREAD_ID,),
        lambda candidate: None,
    )

    assert not any(
        issue.code == "remote_project_identity_mismatch"
        for issue in materialized.issues
    )


def _write_remote_store(
    sync_dir: Path,
    *,
    indexed_project: str,
    actual_project: str,
) -> Path:
    contents = _session_bytes(THREAD_ID, actual_project, "/remote/project")
    remote_path = sync_dir / "tasks" / f"{THREAD_ID}.jsonl"
    remote_path.parent.mkdir(parents=True)
    remote_path.write_bytes(contents)
    index = RemoteIndex(
        REMOTE_TRANSFER_FORMAT_VERSION,
        "2026-07-31T12:00:00Z",
        {
            THREAD_ID: _remote_entry(
                indexed_project=indexed_project,
                aliases=(),
                contents=contents,
            )
        },
    )
    (sync_dir / "sync-index.json").write_text(
        json.dumps(index.to_dict(), separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return remote_path


def _remote_entry(
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


def _empty_local(session_dir: Path) -> LocalInventory:
    return LocalInventory(
        session_dirs=(session_dir,),
        threads={},
        index_entries={},
        discovered_count=0,
    )


def _write_local_session(sessions: Path, project: Path) -> Path:
    path = sessions / "2026" / "07" / "31" / f"{THREAD_ID}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(_session_bytes(THREAD_ID, PROJECT_A, str(project)))
    return path


def _write_git_origin(project: Path, repository_url: str) -> None:
    git_dir = project / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = {repository_url}.git\n',
        encoding="utf-8",
    )


def _session_bytes(thread_id: str, repository_url: str, cwd: str) -> bytes:
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
