from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from codex_usage.aggregation import filter_records_by_project_keys, summarize_records
from codex_usage.discovery import collect_jsonl_files
from codex_usage.models import SessionMetadata, UsageRecord
from codex_usage.parser import parse_session_files
from codex_usage.project_identity import ProjectIdentity, normalize_project_key, resolve_project_identity
from codex_usage.project_transitions import (
    apply_project_transitions,
    collect_repo_path_observations,
    infer_project_transitions,
)
from codex_usage.session_cache import CachedFileSummary, CachedSessionData
from codex_usage.session_files import (
    file_size,
    load_all_index_entries,
    read_session_metadata,
    session_updated_at,
    timestamp_key,
)
from codex_usage.sync_constants import SYNC_METADATA_OVERHEAD_BYTES


@dataclass(frozen=True)
class ThreadInfo:
    thread_id: str
    title: str
    updated_at: str
    session_path: Path
    project_key: str
    project_label: str
    project_aliases: tuple[str, ...]
    total_tokens: int
    session_bytes: int
    estimated_sync_bytes: int
    memory_mode: str = ""
    has_base_instructions: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "thread_id": self.thread_id,
            "title": self.title,
            "updated_at": self.updated_at,
            "session_path": str(self.session_path),
            "project_key": self.project_key,
            "project_label": self.project_label,
            "project_aliases": list(self.project_aliases),
            "total_tokens": self.total_tokens,
            "session_bytes": self.session_bytes,
            "estimated_sync_bytes": self.estimated_sync_bytes,
            "memory_mode": self.memory_mode,
            "has_base_instructions": self.has_base_instructions,
        }


def list_threads(
    session_dirs: list[Path],
    project_keys: list[str] | None = None,
    *,
    auto_transitions: bool = True,
) -> list[ThreadInfo]:
    index_entries = load_all_index_entries(session_dirs)
    session_paths = collect_jsonl_files(session_dirs)
    selected_project_keys = _normalize_project_filter_keys(project_keys)
    parsed_records = parse_session_files(session_paths)
    if auto_transitions:
        observations = collect_repo_path_observations(session_dirs, session_paths)
        transitions = infer_project_transitions(parsed_records, observations)
        parsed_records = apply_project_transitions(parsed_records, transitions)

    records_by_path: dict[Path, list[UsageRecord]] = {}
    for record in parsed_records:
        records_by_path.setdefault(record.file_path, []).append(record)

    threads: dict[str, ThreadInfo] = {}
    for path in session_paths:
        metadata = read_session_metadata(path)
        if metadata is None:
            continue
        records = records_by_path.get(path, [])
        identity = _thread_identity(metadata, records)
        if selected_project_keys and not filter_records_by_project_keys(records, selected_project_keys):
            aliases = {identity.key, *identity.aliases}
            if not aliases.intersection(selected_project_keys):
                continue

        entry = index_entries.get(metadata.session_id, {})
        session_bytes = file_size(path)
        thread = ThreadInfo(
            thread_id=metadata.session_id,
            title=str(entry.get("thread_name") or identity.label or metadata.session_id),
            updated_at=str(entry.get("updated_at") or session_updated_at(path, metadata.timestamp)),
            session_path=path,
            project_key=identity.key,
            project_label=identity.label,
            project_aliases=identity.aliases,
            total_tokens=summarize_records(records).usage.total_tokens if records else 0,
            session_bytes=session_bytes,
            estimated_sync_bytes=session_bytes + SYNC_METADATA_OVERHEAD_BYTES,
            memory_mode=metadata.memory_mode,
            has_base_instructions=metadata.has_base_instructions,
        )
        _store_latest_thread(threads, thread)
    return _sort_threads(threads)


def list_threads_from_cached_data(
    data: CachedSessionData,
    project_keys: list[str] | None = None,
) -> list[ThreadInfo]:
    index_entries = load_all_index_entries(data.session_dirs)
    selected_project_keys = _normalize_project_filter_keys(project_keys)
    records_by_path: dict[Path, list[UsageRecord]] = {}
    for record in data.records:
        records_by_path.setdefault(record.file_path, []).append(record)

    threads: dict[str, ThreadInfo] = {}
    for path in data.files:
        summary = data.file_summaries.get(path)
        if summary is None:
            continue
        records = records_by_path.get(path, [])
        identity = _summary_identity(summary, records)
        if selected_project_keys and not filter_records_by_project_keys(records, selected_project_keys):
            aliases = {identity.key, *identity.aliases}
            if not aliases.intersection(selected_project_keys):
                continue
        thread = _thread_from_summary(summary, records, index_entries.get(summary.session_id, {}), identity)
        _store_latest_thread(threads, thread)
    return _sort_threads(threads)


def _thread_from_summary(
    summary: CachedFileSummary,
    records: list[UsageRecord],
    index_entry: dict[str, object],
    identity: ProjectIdentity,
) -> ThreadInfo:
    token_total = summarize_records(records).usage.total_tokens if records else 0
    title = str(index_entry.get("thread_name") or index_entry.get("title") or identity.label or summary.session_id)
    updated_at = str(index_entry.get("updated_at") or _latest_record_timestamp(records) or session_updated_at(summary.file_path, None))
    return ThreadInfo(
        thread_id=summary.session_id,
        title=title,
        updated_at=updated_at,
        session_path=summary.file_path,
        project_key=identity.key,
        project_label=identity.label,
        project_aliases=identity.aliases,
        total_tokens=token_total,
        session_bytes=summary.session_bytes,
        estimated_sync_bytes=summary.estimated_sync_bytes,
        memory_mode=summary.memory_mode,
        has_base_instructions=summary.has_base_instructions,
    )


def _thread_identity(metadata: SessionMetadata, records: list[UsageRecord]) -> ProjectIdentity:
    if records:
        return _identity_from_records(records)
    return resolve_project_identity(metadata)


def _summary_identity(summary: CachedFileSummary, records: list[UsageRecord]) -> ProjectIdentity:
    if records:
        return _identity_from_records(records)
    return ProjectIdentity(
        key=summary.project_key,
        label=summary.project_label,
        aliases=summary.project_aliases,
        git_repository_url=summary.git_repository_url,
    )


def _identity_from_records(records: list[UsageRecord]) -> ProjectIdentity:
    latest = max(records, key=_record_identity_key)
    return ProjectIdentity(
        key=latest.project_key,
        label=latest.project_label,
        aliases=latest.project_aliases,
        git_repository_url=latest.git_repository_url,
    )


def _record_identity_key(record: UsageRecord) -> tuple[datetime, str, str, str]:
    return (record.timestamp, record.turn_id, record.project_key, record.project_label)


def _normalize_project_filter_keys(project_keys: list[str] | None) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in project_keys or []:
        key = normalize_project_key(value)
        if not key or key in seen:
            continue
        seen.add(key)
        selected.append(key)
    return selected


def _latest_record_timestamp(records: list[UsageRecord]) -> str:
    if not records:
        return ""
    return max(record.timestamp for record in records).isoformat()


def _store_latest_thread(threads: dict[str, ThreadInfo], thread: ThreadInfo) -> None:
    existing = threads.get(thread.thread_id)
    if existing is None or timestamp_key(thread.updated_at) >= timestamp_key(existing.updated_at):
        threads[thread.thread_id] = thread


def _sort_threads(threads: dict[str, ThreadInfo]) -> list[ThreadInfo]:
    return sorted(threads.values(), key=lambda item: timestamp_key(item.updated_at), reverse=True)
