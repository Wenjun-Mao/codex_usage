from __future__ import annotations

from pathlib import Path

from codex_usage.models import ROOT_USAGE_ROLE, SUBAGENT_USAGE_ROLE, UsageRole
from codex_usage.storage_content import StorageContentMetrics
from codex_usage.storage_content_cache import StorageContentDiagnostic
from codex_usage.storage_insights import build_task_storage_insights
from codex_usage.storage_metadata import StorageFile


def test_complete_threshold_analysis_marks_history_media_and_active_root_risk(
    tmp_path: Path,
) -> None:
    size = 2 << 30
    root = _file(
        tmp_path,
        task_id="root",
        size=size,
        compacted_bytes=1 << 30,
        media_occurrences=2,
    )

    tree = build_task_storage_insights([root], [tmp_path]).task_trees[0]

    assert tree.analysis_status == "complete"
    assert tree.analysis_coverage == 1.0
    assert tree.compacted_share == 0.5
    assert tree.has_history_amplification is True
    assert tree.has_media_amplification is True
    assert tree.has_active_root_history_risk is True
    assert tree.can_prepare_rollover is True


def test_partial_analysis_never_claims_amplification_and_counts_large_descendants(
    tmp_path: Path,
) -> None:
    root = _file(
        tmp_path,
        task_id="root",
        size=2 << 30,
        compacted_bytes=2 << 30,
        analyzed_offset=(2 << 30) - 1,
    )
    child = _file(
        tmp_path,
        task_id="child",
        parent_task_id="root",
        size=1 << 30,
        usage_role=SUBAGENT_USAGE_ROLE,
        compacted_bytes=1 << 30,
    )

    tree = build_task_storage_insights([root, child], [tmp_path]).task_trees[0]

    assert tree.analysis_status == "partial"
    assert tree.has_history_amplification is False
    assert tree.has_media_amplification is False
    assert tree.has_active_root_history_risk is False
    assert tree.large_descendant_file_count == 1
    assert tree.large_descendant_bytes == 1 << 30


def _file(
    root: Path,
    *,
    task_id: str,
    size: int,
    compacted_bytes: int,
    analyzed_offset: int | None = None,
    parent_task_id: str = "",
    usage_role: UsageRole = ROOT_USAGE_ROLE,
    media_occurrences: int = 0,
) -> StorageFile:
    path = root / f"{task_id}.jsonl"
    offset = size if analyzed_offset is None else analyzed_offset
    diagnostic = StorageContentDiagnostic(
        path=str(path),
        task_id=task_id,
        analyzed_offset=offset,
        source_device=1,
        source_inode=1,
        source_mtime_ns=1,
        head_sha256="head",
        boundary_sha256="boundary",
        metrics=StorageContentMetrics(
            compacted_record_count=int(compacted_bytes > 0),
            compacted_bytes=compacted_bytes,
            largest_compacted_record_bytes=compacted_bytes,
            media_compacted_record_count=int(media_occurrences > 0),
            embedded_media_occurrence_count=media_occurrences,
        ),
        last_analyzed_at="2026-08-08T00:00:00+00:00",
    )
    return StorageFile(
        path=str(path),
        session_dir=str(root),
        storage_state="active",
        size_bytes=size,
        mtime_ns=1,
        task_id=task_id,
        parent_task_id=parent_task_id,
        usage_role=usage_role,
        project_key="repo",
        project_label="Repo",
        project_aliases=(),
        task_title="Task",
        metadata_diagnostic="",
        content_diagnostic=diagnostic,
    )
