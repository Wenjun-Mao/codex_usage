from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from codex_usage.models import UsageRecord
from codex_usage.parallel.execution import (
    EMPTY_PARALLEL_RUN_REPORT,
    ParallelRunReport,
)
from codex_usage.project_transitions import ProjectTransition


@dataclass(frozen=True)
class CacheStats:
    files_total: int = 0
    files_current: int = 0
    files_archived: int = 0
    files_parsed: int = 0
    files_reused: int = 0
    files_removed: int = 0
    files_missing_retained: int = 0
    file_errors: int = 0
    rebuilt: bool = False
    legacy_cleanup_errors: int = 0
    cache_errors: int = 0
    worker_infrastructure_errors: int = 0
    worker_serial_fallbacks: int = 0
    direct_fallback: bool = False


@dataclass(frozen=True, slots=True)
class CacheRefreshOutcome:
    stats: CacheStats
    usage_run: ParallelRunReport
    affected_task_ids: frozenset[str]


@dataclass(frozen=True)
class CachedFileSummary:
    file_path: Path
    session_dir: Path
    session_id: str
    cwd: str
    project_key: str
    project_label: str
    project_aliases: tuple[str, ...]
    git_repository_url: str
    git_branch: str
    memory_mode: str
    has_base_instructions: bool
    session_bytes: int
    estimated_sync_bytes: int
    file_key: str = ""
    storage_state: str = "active"
    is_missing: bool = False


@dataclass(frozen=True)
class CachedSessionData:
    session_dirs: list[Path]
    files: list[Path]
    records: list[UsageRecord]
    file_summaries: dict[Path, CachedFileSummary]
    project_transitions: list[ProjectTransition]
    stats: CacheStats
    file_errors: dict[str, str]
    retained_missing_files: list[Path] = field(default_factory=list)
    usage_run: ParallelRunReport = EMPTY_PARALLEL_RUN_REPORT
    transition_run: ParallelRunReport = EMPTY_PARALLEL_RUN_REPORT
