from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import batched
from pathlib import Path
from typing import BinaryIO, Literal

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from codex_usage.parallel.execution import DEFAULT_MAX_WORKERS, OrderedProcessMapper, WorkerSpan
from codex_usage.session_row_relevance import (
    CHECKPOINT_DIGEST_BYTES,
    SESSION_READ_BUFFER_BYTES,
)
from codex_usage.session_cache import CACHE_DB_NAME, resolve_cache_dir
from codex_usage.session_cache_schema import _ensure_schema
from codex_usage.session_inventory import SessionFileInventoryEntry
from codex_usage.storage_content import StorageContentMetrics, observe_storage_row
from codex_usage.storage_content_cache import (
    StorageContentDiagnostic,
    load_content_diagnostic,
    upsert_content_diagnostic,
)
from codex_usage.storage_context import StorageContext, load_storage_context

type AnalysisOutcome = Literal["unchanged", "append", "full", "full_fallback"]
ProgressCallback = Callable[[dict[str, object]], None]


class StorageAnalysisError(RuntimeError):
    pass


class StorageAnalysisCancelled(StorageAnalysisError):
    pass


@dataclass(frozen=True, slots=True)
class StorageAnalysisRequest:
    ordinal: int
    path: Path
    task_id: str
    storage_state: str
    size_bytes: int
    mtime_ns: int
    source_device: int
    source_inode: int
    existing: StorageContentDiagnostic | None

    @property
    def estimated_bytes(self) -> int:
        if _can_attempt_append(self):
            assert self.existing is not None
            return max(0, self.size_bytes - self.existing.analyzed_offset)
        return self.size_bytes


@dataclass(frozen=True, slots=True)
class StorageAnalysisResult:
    request: StorageAnalysisRequest
    diagnostic: StorageContentDiagnostic | None
    outcome: AnalysisOutcome
    bytes_read: int
    error: str
    span: WorkerSpan


@dataclass(frozen=True, slots=True)
class StorageAnalysisSummary:
    tree_id: str
    files_total: int
    files_analyzed: int
    files_unchanged: int
    files_appended: int
    full_scans: int
    append_fallbacks: int
    source_bytes_read: int
    worker_count: int
    diagnostics: tuple[StorageContentDiagnostic, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "tree_id": self.tree_id,
            "files_total": self.files_total,
            "files_analyzed": self.files_analyzed,
            "files_unchanged": self.files_unchanged,
            "files_appended": self.files_appended,
            "full_scans": self.full_scans,
            "append_fallbacks": self.append_fallbacks,
            "source_bytes_read": self.source_bytes_read,
            "worker_count": self.worker_count,
        }


def analyze_storage_tree(
    tree_id: str,
    *,
    session_dirs: list[Path] | None = None,
    cache_dir: Path | None = None,
    cache_database_path: Path | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    progress: ProgressCallback | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> StorageAnalysisSummary:
    context = load_storage_context(
        session_dirs=session_dirs,
        cache_dir=cache_dir,
        cache_database_path=cache_database_path,
    )
    tree = next(
        (candidate for candidate in context.insights.task_trees if candidate.root_task_id == tree_id),
        None,
    )
    if tree is None:
        raise StorageAnalysisError(f"Task tree not found: {tree_id}")
    entries = _selected_inventory(context, {file.path for file in tree.storage_files})
    if cache_dir is not None and cache_database_path is not None:
        raise ValueError("cache_dir and cache_database_path are mutually exclusive")
    resolved_cache = resolve_cache_dir(list(context.session_dirs), cache_dir)
    database_path = cache_database_path or resolved_cache / CACHE_DB_NAME
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        _ensure_schema(connection)
        task_ids_by_path = {file.path: file.task_id for file in tree.storage_files}
        requests = tuple(
            StorageAnalysisRequest(
                ordinal=index,
                path=entry.path,
                task_id=task_ids_by_path[str(entry.path)],
                storage_state=entry.storage_state,
                size_bytes=entry.size_bytes,
                mtime_ns=entry.mtime_ns,
                source_device=entry.source_device,
                source_inode=entry.source_inode,
                existing=load_content_diagnostic(connection, entry.path),
            )
            for index, entry in enumerate(entries)
        )
        results, worker_count = _run_analysis(
            requests,
            max_workers=max_workers,
            progress=progress,
            cancelled=cancelled,
        )
        if cancelled is not None and cancelled():
            raise StorageAnalysisCancelled("Storage analysis was cancelled")
        failures = tuple(result for result in results if result.error)
        if failures:
            details = "; ".join(
                f"{result.request.path}: {result.error}" for result in failures
            )
            raise StorageAnalysisError(details)
        connection.execute("begin immediate")
        try:
            for result in results:
                if result.diagnostic is not None:
                    upsert_content_diagnostic(connection, result.diagnostic)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    finally:
        connection.close()

    diagnostics = tuple(
        result.diagnostic
        for result in results
        if result.diagnostic is not None
    )
    return StorageAnalysisSummary(
        tree_id=tree_id,
        files_total=len(results),
        files_analyzed=sum(result.outcome != "unchanged" for result in results),
        files_unchanged=sum(result.outcome == "unchanged" for result in results),
        files_appended=sum(result.outcome == "append" for result in results),
        full_scans=sum(result.outcome in {"full", "full_fallback"} for result in results),
        append_fallbacks=sum(result.outcome == "full_fallback" for result in results),
        source_bytes_read=sum(result.bytes_read for result in results),
        worker_count=worker_count,
        diagnostics=diagnostics,
    )


def analyze_storage_request(request: StorageAnalysisRequest) -> StorageAnalysisResult:
    started = time.monotonic_ns()
    try:
        diagnostic, outcome, bytes_read = _analyze_request(request)
        error = ""
    except Exception as exc:  # noqa: BLE001 - one file must not crash the pool.
        diagnostic = None
        outcome = "full"
        bytes_read = 0
        error = f"{type(exc).__name__}: {exc}"
    return StorageAnalysisResult(
        request=request,
        diagnostic=diagnostic,
        outcome=outcome,
        bytes_read=bytes_read,
        error=error,
        span=WorkerSpan(os.getpid(), started, time.monotonic_ns()),
    )


def _run_analysis(
    requests: tuple[StorageAnalysisRequest, ...],
    *,
    max_workers: int,
    progress: ProgressCallback | None,
    cancelled: Callable[[], bool] | None,
) -> tuple[tuple[StorageAnalysisResult, ...], int]:
    scheduled = tuple(sorted(requests, key=lambda request: (-request.estimated_bytes, request.ordinal)))
    completed: list[StorageAnalysisResult] = []
    with OrderedProcessMapper(
        analyze_storage_request,
        task_count=len(scheduled),
        max_workers=min(DEFAULT_MAX_WORKERS, max_workers),
    ) as mapper:
        for request_group in batched(scheduled, max(1, mapper.worker_count)):
            if cancelled is not None and cancelled():
                raise StorageAnalysisCancelled("Storage analysis was cancelled")
            for result in mapper.map_batch(request_group):
                completed.append(result)
                if progress is not None:
                    progress(
                        {
                            "phase": "analyzing",
                            "completed_files": len(completed),
                            "total_files": len(scheduled),
                            "completed_bytes": sum(item.bytes_read for item in completed),
                            "total_bytes": sum(item.estimated_bytes for item in scheduled),
                            "path": str(result.request.path),
                        }
                    )
        worker_count = mapper.worker_count
    return (
        tuple(sorted(completed, key=lambda result: result.request.ordinal)),
        worker_count,
    )


@retry(
    retry=retry_if_exception_type(OSError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.01, min=0.01, max=0.04),
    reraise=True,
)
def _analyze_request(
    request: StorageAnalysisRequest,
) -> tuple[StorageContentDiagnostic, AnalysisOutcome, int]:
    existing = request.existing
    if (
        existing is not None
        and request.source_device
        and request.source_inode
        and existing.task_id == request.task_id
        and existing.analyzed_offset == request.size_bytes
        and existing.source_device == request.source_device
        and existing.source_inode == request.source_inode
        and existing.source_mtime_ns == request.mtime_ns
    ):
        return existing, "unchanged", 0

    fallback = False
    if _can_attempt_append(request):
        assert existing is not None
        try:
            metrics, offset, head, boundary, bytes_read = _scan_file(
                request,
                start_offset=existing.analyzed_offset,
                expected=existing,
            )
            combined = existing.metrics + metrics
            outcome: AnalysisOutcome = "append"
        except _GuardMismatch:
            fallback = True
        else:
            return (
                _diagnostic(request, offset, head, boundary, combined),
                outcome,
                bytes_read,
            )

    metrics, offset, head, boundary, bytes_read = _scan_file(
        request,
        start_offset=0,
        expected=None,
    )
    return (
        _diagnostic(request, offset, head, boundary, metrics),
        "full_fallback" if fallback else "full",
        bytes_read,
    )


class _GuardMismatch(ValueError):
    pass


def _scan_file(
    request: StorageAnalysisRequest,
    *,
    start_offset: int,
    expected: StorageContentDiagnostic | None,
) -> tuple[StorageContentMetrics, int, str, str, int]:
    metrics = StorageContentMetrics()
    bytes_read = 0
    checkpoint_offset = start_offset
    with request.path.open("rb", buffering=SESSION_READ_BUFFER_BYTES) as handle:
        opened = os.fstat(handle.fileno())
        if opened.st_size < request.size_bytes:
            raise OSError("source file shrank before analysis")
        if (
            request.source_device
            and int(opened.st_dev) != request.source_device
        ) or (
            request.source_inode
            and int(opened.st_ino) != request.source_inode
        ):
            raise OSError("source file identity changed before analysis")
        if expected is not None:
            bytes_read += _verify_guard(handle, expected, request.size_bytes)
        handle.seek(start_offset)
        while handle.tell() < request.size_bytes:
            line_start = handle.tell()
            raw_line = handle.readline(request.size_bytes - line_start)
            if not raw_line:
                break
            bytes_read += len(raw_line)
            line_end = handle.tell()
            if line_end == request.size_bytes and not raw_line.endswith(b"\n"):
                handle.seek(line_start)
                break
            metrics += observe_storage_row(raw_line).metrics
            checkpoint_offset = line_end
        current = request.path.stat()
        if (
            request.source_device
            and int(current.st_dev) != request.source_device
        ) or (
            request.source_inode
            and int(current.st_ino) != request.source_inode
        ):
            raise OSError("source file identity changed during analysis")
        if current.st_size < request.size_bytes:
            raise OSError("source file shrank during analysis")
        head, head_bytes = _digest_range(handle, 0, min(CHECKPOINT_DIGEST_BYTES, checkpoint_offset))
        boundary_start = max(0, checkpoint_offset - CHECKPOINT_DIGEST_BYTES)
        boundary, boundary_bytes = _digest_range(handle, boundary_start, checkpoint_offset)
        bytes_read += head_bytes + boundary_bytes
    return metrics, checkpoint_offset, head, boundary, bytes_read


def _verify_guard(
    handle: BinaryIO,
    expected: StorageContentDiagnostic,
    stop_offset: int,
) -> int:
    if stop_offset < expected.analyzed_offset:
        raise _GuardMismatch("source file was truncated")
    head, head_bytes = _digest_range(
        handle, 0, min(CHECKPOINT_DIGEST_BYTES, expected.analyzed_offset)
    )
    boundary_start = max(0, expected.analyzed_offset - CHECKPOINT_DIGEST_BYTES)
    boundary, boundary_bytes = _digest_range(handle, boundary_start, expected.analyzed_offset)
    if head != expected.head_sha256 or boundary != expected.boundary_sha256:
        raise _GuardMismatch("source file guard changed")
    return head_bytes + boundary_bytes


def _digest_range(handle: BinaryIO, start: int, end: int) -> tuple[str, int]:
    handle.seek(start)
    remaining = max(0, end - start)
    digest = hashlib.sha256()
    total = 0
    while remaining:
        chunk = handle.read(min(CHECKPOINT_DIGEST_BYTES, remaining))
        if not chunk:
            raise OSError("source file ended before guard range")
        digest.update(chunk)
        total += len(chunk)
        remaining -= len(chunk)
    return digest.hexdigest(), total


def _can_attempt_append(request: StorageAnalysisRequest) -> bool:
    existing = request.existing
    return bool(
        existing is not None
        and request.storage_state == "active"
        and existing.task_id == request.task_id
        and request.size_bytes > existing.analyzed_offset
        and request.source_device
        and request.source_inode
        and existing.source_device == request.source_device
        and existing.source_inode == request.source_inode
    )


def _diagnostic(
    request: StorageAnalysisRequest,
    offset: int,
    head: str,
    boundary: str,
    metrics: StorageContentMetrics,
) -> StorageContentDiagnostic:
    return StorageContentDiagnostic(
        path=str(request.path),
        task_id=request.task_id,
        analyzed_offset=offset,
        source_device=request.source_device,
        source_inode=request.source_inode,
        source_mtime_ns=request.mtime_ns,
        head_sha256=head,
        boundary_sha256=boundary,
        metrics=metrics,
        last_analyzed_at=datetime.now(UTC).isoformat(),
    )


def _selected_inventory(
    context: StorageContext,
    paths: set[str],
) -> tuple[SessionFileInventoryEntry, ...]:
    entries = tuple(entry for entry in context.inventory if str(entry.path) in paths)
    if len(entries) != len(paths):
        raise StorageAnalysisError("Selected task tree changed during inventory")
    return entries
