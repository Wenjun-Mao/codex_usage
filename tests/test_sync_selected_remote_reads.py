from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import codex_usage.sync.io as sync_io
import codex_usage.sync.remote_reconciliation as reconciliation
from codex_usage.sync.constants import (
    LEGACY_REMOTE_TRANSFER_FORMAT_VERSION,
    REMOTE_TRANSFER_FORMAT_VERSION,
)
from codex_usage.sync.directional_preflight import prepare_status_plan
from codex_usage.sync.local_session_probe import load_local_transfer_probe
from codex_usage.sync.models import (
    LocalInventory,
    ProjectResolutionRequest,
    RemoteIndex,
    RemoteThreadEntry,
)
from codex_usage.sync.runner import pull_sync
from codex_usage.sync.store import RemoteStore

PROJECT_KEY = "https://github.com/example/selected-reads"


def test_v3_pull_fully_reads_and_hashes_only_selected_remote_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    _write_git_origin(project)
    sessions = tmp_path / "codex" / "sessions"
    selected_local = _write_session(sessions / "selected.jsonl", "selected", project)
    local = load_local_transfer_probe([sessions]).inventory
    sync_dir = tmp_path / "sync"
    selected_remote = _write_session(
        sync_dir / "tasks" / "selected.jsonl",
        "selected",
        project,
    )
    unrelated_indexed = _write_session(
        sync_dir / "tasks" / "indexed.jsonl",
        "indexed",
        project,
    )
    unrelated_unindexed = _write_session(
        sync_dir / "tasks" / "unindexed.jsonl",
        "unindexed",
        project,
    )
    _write_index(
        sync_dir,
        REMOTE_TRANSFER_FORMAT_VERSION,
        {
            "selected": _entry("selected", selected_remote, "tasks"),
            "indexed": _entry("indexed", unrelated_indexed, "tasks"),
        },
    )
    assert selected_local.read_bytes() == selected_remote.read_bytes()
    full_reads, hashes = _spy_complete_reads(monkeypatch, sync_dir)

    result = pull_sync(
        local=local,
        sync_dir=sync_dir,
        thread_ids=("selected",),
        project_resolution=ProjectResolutionRequest(),
        project_key=PROJECT_KEY,
    )

    assert result.outcome == "completed"
    assert result.pulled == ()
    assert selected_remote in full_reads
    assert selected_remote in hashes
    assert unrelated_indexed not in full_reads
    assert unrelated_indexed not in hashes
    assert unrelated_unindexed not in full_reads
    assert unrelated_unindexed not in hashes


def test_v3_selected_unindexed_recovery_is_the_only_complete_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    _write_git_origin(project)
    sync_dir = tmp_path / "sync"
    selected = _write_session(
        sync_dir / "tasks" / "selected-unindexed.jsonl",
        "selected-unindexed",
        project,
    )
    unrelated = _write_session(
        sync_dir / "tasks" / "unrelated-unindexed.jsonl",
        "unrelated-unindexed",
        project,
    )
    _write_index(sync_dir, REMOTE_TRANSFER_FORMAT_VERSION, {})
    full_reads, hashes = _spy_complete_reads(monkeypatch, sync_dir)

    remote, plan = prepare_status_plan(
        _empty_local(tmp_path / "target" / "sessions"),
        RemoteStore(sync_dir),
        sync_dir,
        ("selected-unindexed",),
        ProjectResolutionRequest(),
    )

    assert plan.items[0].remote.sha256 == hashlib.sha256(selected.read_bytes()).hexdigest()
    assert remote.files["selected-unindexed"].sha256 == plan.items[0].remote.sha256
    assert selected in full_reads
    assert selected in hashes
    assert unrelated not in full_reads
    assert unrelated not in hashes


def test_v2_status_still_fully_reads_and_hashes_all_migration_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    _write_git_origin(project)
    sync_dir = tmp_path / "sync"
    selected = _write_session(
        sync_dir / "conversations" / "selected.jsonl",
        "selected",
        project,
    )
    unrelated = _write_session(
        sync_dir / "conversations" / "unrelated.jsonl",
        "unrelated",
        project,
    )
    _write_index(
        sync_dir,
        LEGACY_REMOTE_TRANSFER_FORMAT_VERSION,
        {
            "selected": _entry("selected", selected, "conversations"),
            "unrelated": _entry("unrelated", unrelated, "conversations"),
        },
    )
    full_reads, hashes = _spy_complete_reads(monkeypatch, sync_dir)

    prepare_status_plan(
        _empty_local(tmp_path / "target" / "sessions"),
        RemoteStore(sync_dir),
        sync_dir,
        ("selected",),
        ProjectResolutionRequest(),
    )

    assert {selected, unrelated} <= set(full_reads)
    assert {selected, unrelated} <= set(hashes)


def _spy_complete_reads(
    monkeypatch: pytest.MonkeyPatch,
    sync_dir: Path,
) -> tuple[list[Path], list[Path]]:
    full_reads: list[Path] = []
    hashes: list[Path] = []
    real_read = reconciliation.read_bytes_with_snapshot
    real_snapshot = sync_io._snapshot_from_bytes

    def read_bytes(path: Path | None):
        if path is not None and sync_dir in path.parents and path.suffix == ".jsonl":
            full_reads.append(path)
        return real_read(path)

    def snapshot(path: Path, contents: bytes):
        if sync_dir in path.parents and path.suffix == ".jsonl":
            hashes.append(path)
        return real_snapshot(path, contents)

    monkeypatch.setattr(reconciliation, "read_bytes_with_snapshot", read_bytes)
    monkeypatch.setattr(sync_io, "_snapshot_from_bytes", snapshot)
    return full_reads, hashes


def _empty_local(session_dir: Path) -> LocalInventory:
    return LocalInventory(
        session_dirs=(session_dir,),
        threads={},
        index_entries={},
        discovered_count=0,
    )


def _write_git_origin(project: Path) -> None:
    git_dir = project / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = {PROJECT_KEY}.git\n',
        encoding="utf-8",
    )


def _write_session(path: Path, thread_id: str, project: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": "2026-07-31T12:00:00Z",
        "type": "session_meta",
        "payload": {
            "id": thread_id,
            "timestamp": "2026-07-31T12:00:00Z",
            "cwd": str(project),
            "source": "cli",
            "git": {"repository_url": PROJECT_KEY},
        },
    }
    path.write_text(
        json.dumps(row, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def _entry(thread_id: str, path: Path, directory: str) -> RemoteThreadEntry:
    contents = path.read_bytes()
    return RemoteThreadEntry(
        thread_id=thread_id,
        file=f"{directory}/{path.name}",
        source_relative_path=f"synced/{path.name}",
        index_entry={"id": thread_id},
        project_key=PROJECT_KEY,
        project_label="selected-reads",
        project_aliases=(),
        sha256=hashlib.sha256(contents).hexdigest(),
        size_bytes=len(contents),
        session_updated_at="2026-07-31T12:00:00Z",
        exported_at="2026-07-31T12:00:00Z",
        source_machine_id="source",
    )


def _write_index(
    sync_dir: Path,
    format_version: int,
    entries: dict[str, RemoteThreadEntry],
) -> None:
    sync_dir.mkdir(parents=True, exist_ok=True)
    index = RemoteIndex(format_version, "2026-07-31T12:00:00Z", entries)
    (sync_dir / "sync-index.json").write_text(
        json.dumps(index.to_dict(), separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
