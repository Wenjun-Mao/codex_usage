from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.project_identity import resolve_project_identity
from codex_usage.session_files import (
    file_size,
    load_all_index_entries,
    session_updated_at,
)
from codex_usage.session_inventory import storage_state_for_session_dir
from codex_usage.sync.models import LocalInventory, SyncIssue
from codex_usage.sync.project_roots import discover_project_roots
from codex_usage.sync.transfer_metadata import read_transfer_metadata
from codex_usage.threads import ThreadInfo

_ESTIMATED_SYNC_METADATA_BYTES = 4096


@dataclass(frozen=True)
class LocalTransferProbe:
    inventory: LocalInventory
    issues: tuple[SyncIssue, ...]


def load_local_transfer_probe(session_dirs: list[Path]) -> LocalTransferProbe:
    index_entries = load_all_index_entries(session_dirs)
    threads: dict[str, ThreadInfo] = {}
    metadata_timestamps: dict[str, datetime] = {}
    issues: list[SyncIssue] = []
    for session_dir in session_dirs:
        if storage_state_for_session_dir(session_dir) != "active" or not session_dir.is_dir():
            continue
        for path in sorted(session_dir.rglob("*.jsonl"), key=lambda item: str(item).casefold()):
            if not path.is_file():
                continue
            metadata = read_transfer_metadata(path)
            if metadata is None:
                issues.append(
                    SyncIssue(
                        "local_session_metadata_unreadable",
                        f"Local task {path} has no readable session_meta identity",
                    )
                )
                continue
            if metadata.is_subagent:
                continue
            identity = resolve_project_identity(metadata)
            index_entry = index_entries.get(metadata.session_id, {})
            size = file_size(path)
            thread = ThreadInfo(
                thread_id=metadata.session_id,
                title=str(
                    index_entry.get("thread_name")
                    or index_entry.get("title")
                    or identity.label
                    or metadata.session_id
                ),
                updated_at=str(
                    index_entry.get("updated_at")
                    or session_updated_at(path, metadata.timestamp)
                ),
                session_path=path,
                project_key=identity.key,
                project_label=identity.label,
                project_aliases=identity.aliases,
                total_tokens=0,
                session_bytes=size,
                estimated_sync_bytes=size + _ESTIMATED_SYNC_METADATA_BYTES,
                memory_mode=metadata.memory_mode,
                has_base_instructions=metadata.has_base_instructions,
                cwd=metadata.cwd,
            )
            metadata_timestamp = metadata.timestamp or datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=UTC,
            )
            previous_timestamp = metadata_timestamps.get(thread.thread_id)
            if previous_timestamp is None or metadata_timestamp >= previous_timestamp:
                threads[thread.thread_id] = thread
                metadata_timestamps[thread.thread_id] = metadata_timestamp
    inventory = LocalInventory(
        session_dirs=tuple(session_dirs),
        threads=threads,
        index_entries=index_entries,
        discovered_count=len(threads),
        project_roots=discover_project_roots(tuple(session_dirs)),
    )
    return LocalTransferProbe(inventory, tuple(issues))
