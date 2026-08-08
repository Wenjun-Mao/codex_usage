from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import codex_usage.task_rollover as rollover
from codex_usage.storage_insights import TaskStorageTree
from codex_usage.task_backup.models import BackupResult, BackupSelection


def test_rollover_requires_complete_analysis(tmp_path: Path, monkeypatch) -> None:
    tree = _tree(analysis_status="partial")
    monkeypatch.setattr(rollover, "load_storage_context", lambda **_kwargs: _context(tree))

    with pytest.raises(
        rollover.RolloverPreparationError,
        match="Complete History Amplification analysis",
    ):
        rollover.prepare_task_rollover(
            "root",
            tmp_path / "new.codex-task-backup",
            session_dirs=[tmp_path],
        )


def test_rollover_refuses_salvage_and_existing_archive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tree = _tree()
    monkeypatch.setattr(rollover, "load_storage_context", lambda **_kwargs: _context(tree))
    monkeypatch.setattr(
        rollover,
        "select_backup_tree",
        lambda *_args: _selection(recovery_ready=False),
    )

    with pytest.raises(rollover.RolloverPreparationError, match="recovery-ready"):
        rollover.prepare_task_rollover(
            "root",
            tmp_path / "new.codex-task-backup",
            session_dirs=[tmp_path],
        )

    existing = tmp_path / "existing.codex-task-backup"
    existing.write_bytes(b"keep")
    with pytest.raises(rollover.RolloverPreparationError, match="new backup path"):
        rollover.prepare_task_rollover(
            "root",
            existing,
            session_dirs=[tmp_path],
        )
    assert existing.read_bytes() == b"keep"


def test_rollover_creates_new_verified_backup_and_text_only_handoff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tree = _tree()
    output = tmp_path / "rollover.codex-task-backup"
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rollover, "load_storage_context", lambda **_kwargs: _context(tree))
    monkeypatch.setattr(
        rollover,
        "select_backup_tree",
        lambda *_args: _selection(recovery_ready=True),
    )

    def create(_selection, path: Path, **kwargs):
        calls.append({"path": path, **kwargs})
        path.write_bytes(b"verified")
        return BackupResult(
            archive_path=path,
            source_bytes=10_000,
            archive_bytes=8,
            file_count=2,
            recovery_ready=True,
            warnings=(),
            archive_sha256="a" * 64,
            compression="maximum",
        )

    monkeypatch.setattr(rollover, "create_task_backup", create)

    result = rollover.prepare_task_rollover(
        "root",
        output,
        session_dirs=[tmp_path],
    )

    assert output.read_bytes() == b"verified"
    assert calls[0]["replace_existing"] is False
    assert "Goal:" in result.starter_prompt
    assert "Current state:" in result.starter_prompt
    assert "Verification completed:" in result.starter_prompt
    assert "Remaining work:" in result.starter_prompt
    assert "Key paths:" in result.starter_prompt
    assert "a" * 64 in result.starter_prompt
    assert any("Only after verification" in item for item in result.checklist)


def _tree(*, analysis_status: str = "complete") -> TaskStorageTree:
    return TaskStorageTree(
        root_task_id="root",
        title="Long task",
        project_key="repo",
        project_label="Repo",
        project_aliases=(),
        root_bytes=1,
        descendant_bytes=1,
        descendant_count=1,
        active_file_count=2,
        archived_file_count=0,
        active_bytes=2,
        archived_bytes=0,
        physical_file_count=2,
        total_bytes=2,
        share=1.0,
        has_missing_root=False,
        has_relationship_cycle=False,
        duplicate_file_count=0,
        metadata_diagnostics=(),
        is_large_root=False,
        is_large_tree=True,
        analysis_status=analysis_status,
    )


def _context(tree: TaskStorageTree):
    return SimpleNamespace(
        insights=SimpleNamespace(task_trees=(tree,)),
        files=(),
    )


def _selection(*, recovery_ready: bool) -> BackupSelection:
    return BackupSelection(
        tree_id="root",
        root_task_id="root",
        title="Long task",
        project_key="repo",
        project_label="Repo",
        project_aliases=(),
        recovery_ready=recovery_ready,
        diagnostics=() if recovery_ready else ("root_missing",),
        sources=(),
        session_index_bytes=b"",
        session_index_entry_count=0,
    )
