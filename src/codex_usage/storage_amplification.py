from __future__ import annotations

from dataclasses import dataclass

from codex_usage.storage_metadata import StorageFile


HISTORY_AMPLIFICATION_BYTES = 1 << 30
HISTORY_AMPLIFICATION_SHARE = 0.5
LARGE_DESCENDANT_FILE_BYTES = 1 << 30


@dataclass(frozen=True, slots=True)
class StorageContentSummary:
    analysis_status: str
    analyzed_bytes: int
    compacted_record_count: int
    compacted_bytes: int
    largest_compacted_record_bytes: int
    media_compacted_record_count: int
    embedded_media_occurrence_count: int
    large_descendant_file_count: int
    large_descendant_bytes: int
    active_root_compacted_bytes: int
    has_active_root_history_risk: bool


def summarize_storage_content(
    files: list[StorageFile],
    root_key: str,
    has_root: bool,
) -> StorageContentSummary:
    diagnostics = [file.content_diagnostic for file in files]
    analyzed_bytes = sum(
        min(file.size_bytes, diagnostic.analyzed_offset)
        for file, diagnostic in zip(files, diagnostics, strict=True)
        if diagnostic is not None
    )
    complete = all(
        diagnostic is not None
        and diagnostic.path == file.path
        and diagnostic.task_id == file.task_id
        and diagnostic.analyzed_offset == file.size_bytes
        and diagnostic.source_mtime_ns == file.mtime_ns
        and not diagnostic.error
        and diagnostic.metrics.complete
        for file, diagnostic in zip(files, diagnostics, strict=True)
    )
    if complete:
        analysis_status = "complete"
    elif any(diagnostic is not None for diagnostic in diagnostics):
        analysis_status = "partial"
    else:
        analysis_status = "not_analyzed"
    metrics = [
        diagnostic.metrics for diagnostic in diagnostics if diagnostic is not None
    ]
    large_descendants = [
        file
        for file in files
        if (not has_root or file.task_id != root_key)
        and file.size_bytes >= LARGE_DESCENDANT_FILE_BYTES
    ]
    active_root_files = [
        file
        for file in files
        if has_root
        and file.task_id == root_key
        and file.storage_state == "active"
    ]
    active_root_compacted_bytes = sum(
        file.content_diagnostic.metrics.compacted_bytes
        for file in active_root_files
        if file.content_diagnostic is not None
    )
    active_root_bytes = sum(file.size_bytes for file in active_root_files)
    return StorageContentSummary(
        analysis_status=analysis_status,
        analyzed_bytes=analyzed_bytes,
        compacted_record_count=sum(item.compacted_record_count for item in metrics),
        compacted_bytes=sum(item.compacted_bytes for item in metrics),
        largest_compacted_record_bytes=max(
            (item.largest_compacted_record_bytes for item in metrics), default=0
        ),
        media_compacted_record_count=sum(
            item.media_compacted_record_count for item in metrics
        ),
        embedded_media_occurrence_count=sum(
            item.embedded_media_occurrence_count for item in metrics
        ),
        large_descendant_file_count=len(large_descendants),
        large_descendant_bytes=sum(file.size_bytes for file in large_descendants),
        active_root_compacted_bytes=active_root_compacted_bytes,
        has_active_root_history_risk=(
            complete
            and active_root_compacted_bytes >= HISTORY_AMPLIFICATION_BYTES
            and active_root_bytes > 0
            and active_root_compacted_bytes / active_root_bytes
            >= HISTORY_AMPLIFICATION_SHARE
        ),
    )
