from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import codex_usage.cli as cli_module
import codex_usage.sync.runner as runner_module
from codex_usage.sync.constants import LEGACY_REMOTE_TRANSFER_FORMAT_VERSION
from codex_usage.sync.io import snapshot_file
from codex_usage.sync.models import (
    LocalInventory,
    ProjectResolutionRequest,
    RemoteIndex,
    RemoteThreadEntry,
)
from codex_usage.sync.runner import pull_sync, push_sync, sync_status
from codex_usage.threads import ThreadInfo


@pytest.mark.parametrize("direction", ["pull", "push"])
def test_mismatched_scope_leaves_missing_transfer_tree_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    direction: str,
) -> None:
    local = _local_inventory(_local_task(tmp_path, "task-1", "repo-a"))
    monkeypatch.setattr(runner_module, "build_local_inventory", lambda data: local)
    before = _tree_snapshot(tmp_path)

    result = _run_direction(
        direction,
        sync_dir=tmp_path / "transfer",
        thread_ids=("task-1",),
        project_key="repo-b",
    )

    assert result.outcome == "issue"
    assert [issue.code for issue in result.issues] == ["project_scope_mismatch"]
    assert _tree_snapshot(tmp_path) == before
    assert not (tmp_path / ".transfer.codex-usage.lock").exists()


@pytest.mark.parametrize("direction", ["pull", "push"])
def test_mismatched_scope_does_not_migrate_v2_transfer_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    direction: str,
) -> None:
    sync_dir = tmp_path / "transfer"
    _write_v2_store(sync_dir, "task-1", "repo-a")
    local = (
        _local_inventory(_local_task(tmp_path, "task-1", "repo-a"))
        if direction == "push"
        else _local_inventory()
    )
    monkeypatch.setattr(runner_module, "build_local_inventory", lambda data: local)
    before = _tree_snapshot(tmp_path)

    result = _run_direction(
        direction,
        sync_dir=sync_dir,
        thread_ids=("task-1",),
        project_key="repo-b",
    )

    assert result.outcome == "issue"
    assert [issue.code for issue in result.issues] == ["project_scope_mismatch"]
    assert _tree_snapshot(tmp_path) == before
    assert json.loads((sync_dir / "sync-index.json").read_bytes())["format_version"] == 2
    assert not (sync_dir / "tasks").exists()
    assert not (tmp_path / ".transfer.codex-usage.lock").exists()


def test_review_of_v2_transfer_store_is_byte_for_byte_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_dir = tmp_path / "transfer"
    _write_v2_store(sync_dir, "task-1", "repo-a")
    monkeypatch.setattr(
        runner_module,
        "build_local_inventory",
        lambda data: _local_inventory(),
    )
    before = _tree_snapshot(tmp_path)

    plan = sync_status(
        data=object(),
        sync_dir=sync_dir,
        thread_ids=("task-1",),
        project_resolution=ProjectResolutionRequest(),
    )

    assert [item.thread_id for item in plan.items] == ["task-1"]
    assert _tree_snapshot(tmp_path) == before
    assert json.loads((sync_dir / "sync-index.json").read_bytes())["format_version"] == 2
    assert not (sync_dir / "tasks").exists()
    assert not (tmp_path / ".transfer.codex-usage.lock").exists()


def test_mixed_known_and_unknown_selection_is_rejected_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = _local_inventory(_local_task(tmp_path, "known", "repo-a"))
    monkeypatch.setattr(runner_module, "build_local_inventory", lambda data: local)
    before = _tree_snapshot(tmp_path)

    result = push_sync(
        data=object(),
        sync_dir=tmp_path / "transfer",
        thread_ids=("known", "unknown"),
        machine_id="machine-a",
        project_key="repo-a",
    )

    assert result.outcome == "issue"
    assert [issue.code for issue in result.issues] == ["unresolved_selected_task"]
    assert result.issues[0].thread_id == "unknown"
    assert _tree_snapshot(tmp_path) == before


def test_cli_scope_rejection_does_not_create_sessions_or_migrate_v2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    codex_home = tmp_path / "codex-home"
    sync_dir = tmp_path / "transfer"
    _write_v2_store(sync_dir, "task-1", "repo-a")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    before = _tree_snapshot(tmp_path)

    exit_code = cli_module.main(
        [
            "sync",
            "pull",
            "--sync-dir",
            str(sync_dir),
            "--thread-id",
            "task-1",
            "--project-key",
            "repo-b",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert [issue["code"] for issue in payload["issues"]] == [
        "project_scope_mismatch"
    ]
    assert not (codex_home / "sessions").exists()
    assert _tree_snapshot(tmp_path) == before


def _run_direction(
    direction: str,
    *,
    sync_dir: Path,
    thread_ids: tuple[str, ...],
    project_key: str,
):
    if direction == "pull":
        return pull_sync(
            data=object(),
            sync_dir=sync_dir,
            thread_ids=thread_ids,
            project_resolution=ProjectResolutionRequest(),
            project_key=project_key,
        )
    return push_sync(
        data=object(),
        sync_dir=sync_dir,
        thread_ids=thread_ids,
        machine_id="machine-a",
        project_key=project_key,
    )


def _local_inventory(*tasks: ThreadInfo) -> LocalInventory:
    session_dirs = tuple(
        dict.fromkeys(task.session_path.parent for task in tasks)
    ) or (Path("sessions"),)
    return LocalInventory(
        session_dirs=session_dirs,
        threads={task.thread_id: task for task in tasks},
        index_entries={},
        discovered_count=len(tasks),
    )


def _local_task(root: Path, thread_id: str, project_key: str) -> ThreadInfo:
    session_path = root / "sessions" / f"{thread_id}.jsonl"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_bytes(_session_jsonl(thread_id))
    return ThreadInfo(
        thread_id=thread_id,
        title=thread_id,
        updated_at="2026-07-23T12:00:00Z",
        session_path=session_path,
        project_key=project_key,
        project_label=project_key,
        project_aliases=(),
        total_tokens=0,
        session_bytes=100,
        estimated_sync_bytes=4196,
        cwd=str(root / project_key),
    )


def _write_v2_store(
    sync_dir: Path,
    thread_id: str,
    project_key: str,
) -> None:
    task_path = sync_dir / "conversations" / f"{thread_id}.jsonl"
    task_path.parent.mkdir(parents=True)
    task_path.write_bytes(_session_jsonl(thread_id))
    task_snapshot = snapshot_file(task_path)
    entry = RemoteThreadEntry(
        thread_id=thread_id,
        file=f"conversations/{thread_id}.jsonl",
        source_relative_path=f"2026/07/23/{thread_id}.jsonl",
        index_entry={"id": thread_id},
        project_key=project_key,
        project_label=project_key,
        project_aliases=(),
        sha256=task_snapshot.sha256,
        size_bytes=task_snapshot.size_bytes,
        session_updated_at="2026-07-23T12:00:00Z",
        exported_at="2026-07-23T12:00:00Z",
        source_machine_id="machine-a",
    )
    index = RemoteIndex(
        format_version=LEGACY_REMOTE_TRANSFER_FORMAT_VERSION,
        updated_at="2026-07-23T12:00:00Z",
        threads={thread_id: entry},
    )
    (sync_dir / "sync-index.json").write_bytes(
        (json.dumps(index.to_dict(), separators=(",", ":")) + "\n").encode()
    )


def _session_jsonl(thread_id: str) -> bytes:
    event = {
        "timestamp": "2026-07-23T12:00:00Z",
        "type": "session_meta",
        "payload": {
            "id": thread_id,
            "timestamp": "2026-07-23T12:00:00Z",
            "cwd": "/repo/a",
        },
    }
    return (json.dumps(event, separators=(",", ":")) + "\n").encode()


def _tree_snapshot(root: Path) -> tuple[tuple[str, str, bytes], ...]:
    entries: list[tuple[str, str, bytes]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((relative, "symlink", os.readlink(path).encode()))
        elif path.is_dir():
            entries.append((relative, "directory", b""))
        else:
            entries.append((relative, "file", path.read_bytes()))
    return tuple(entries)
