from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.models import UsageRecord
from codex_usage.project_identity import resolve_project_identity
from codex_usage.session_files import owning_session_dir
from codex_usage.session_generation_models import (
    ParsedSessionGeneration,
    RawRepoPathCandidate,
)
from codex_usage.session_inventory import SessionFileInventoryEntry

_ESTIMATED_SYNC_METADATA_BYTES = 4096


def replace_file_generation(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    entry: SessionFileInventoryEntry,
    generation: ParsedSessionGeneration,
) -> set[str]:
    affected = affected_task_ids_for_file(connection, entry.file_key)
    for alias_key in _same_path_alias_keys(connection, entry):
        affected.update(affected_task_ids_for_file(connection, alias_key))
        delete_file_generation(connection, alias_key)
        connection.execute("delete from files where file_key = ?", (alias_key,))
    delete_file_generation(connection, entry.file_key)
    insert_usage_records(connection, entry, generation.records)
    insert_session_metadata(connection, session_dirs, entry, generation)
    insert_transition_candidates(
        connection, entry.file_key, generation.candidates
    )
    upsert_file_fingerprint(
        connection, session_dirs, entry, generation.metadata.session_id
    )
    return affected | generation_task_ids(generation)


def remove_candidate_generation(
    connection: sqlite3.Connection, file_key: str
) -> set[str]:
    affected = {
        str(row["thread_id"])
        for row in connection.execute(
            "select distinct thread_id from transition_candidates where file_key = ?",
            (file_key,),
        )
        if row["thread_id"]
    }
    connection.execute(
        "delete from transition_candidates where file_key = ?", (file_key,)
    )
    return affected


def affected_task_ids_for_file(
    connection: sqlite3.Connection, file_key: str
) -> set[str]:
    return {
        task_id
        for task_id in query_generation_task_ids(connection, file_key)
        if task_id
    }


def query_generation_task_ids(
    connection: sqlite3.Connection, file_key: str
) -> set[str]:
    queries = (
        "select distinct session_id as task_id from usage_records where file_key = ?",
        "select distinct thread_id as task_id from transition_candidates where file_key = ?",
        "select session_id as task_id from session_metadata where file_key = ?",
    )
    return {
        str(row["task_id"])
        for query in queries
        for row in connection.execute(query, (file_key,))
        if row["task_id"]
    }


def generation_task_ids(generation: ParsedSessionGeneration) -> set[str]:
    return {
        task_id
        for task_id in (
            generation.metadata.session_id,
            *(record.session_id for record in generation.records),
            *(candidate.thread_id for candidate in generation.candidates),
        )
        if task_id
    }


def delete_file_generation(connection: sqlite3.Connection, file_key: str) -> None:
    connection.execute("delete from usage_records where file_key = ?", (file_key,))
    connection.execute(
        "delete from session_metadata where file_key = ?", (file_key,)
    )
    connection.execute(
        "delete from transition_candidates where file_key = ?", (file_key,)
    )


def insert_usage_records(
    connection: sqlite3.Connection,
    entry: SessionFileInventoryEntry,
    records: tuple[UsageRecord, ...],
) -> None:
    for index, record in enumerate(records):
        usage = record.usage
        connection.execute(
            """
            insert into usage_records (
                file_key, file_path, record_index, timestamp, timestamp_us, session_id, turn_id, model, effort,
                collaboration_mode, project_key, project_label, project_aliases_json,
                cwd, git_repository_url, git_branch, parent_thread_id,
                input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens,
                reasoning_output_tokens, total_tokens
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.file_key,
                str(entry.path),
                index,
                record.timestamp.isoformat(),
                _timestamp_us(record.timestamp),
                record.session_id,
                record.turn_id,
                record.model,
                record.effort,
                record.collaboration_mode,
                record.project_key,
                record.project_label,
                json.dumps(list(record.project_aliases)),
                record.cwd,
                record.git_repository_url,
                record.git_branch,
                record.parent_thread_id,
                usage.input_tokens,
                usage.cached_input_tokens,
                usage.cache_write_input_tokens,
                usage.output_tokens,
                usage.reasoning_output_tokens,
                usage.total_tokens,
            ),
        )


def insert_session_metadata(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    entry: SessionFileInventoryEntry,
    generation: ParsedSessionGeneration,
) -> None:
    metadata = generation.metadata
    selected = generation.records[-1] if generation.records else None
    identity = (
        None if selected is not None else resolve_project_identity(metadata)
    )
    session_id = selected.session_id if selected else metadata.session_id
    project_key = selected.project_key if selected else identity.key
    project_label = selected.project_label if selected else identity.label
    project_aliases = selected.project_aliases if selected else identity.aliases
    connection.execute(
        """
        insert or replace into session_metadata (
            file_key, file_path, session_dir, storage_state, is_missing, session_id, cwd, project_key, project_label,
            project_aliases_json, git_repository_url, git_branch, memory_mode,
            has_base_instructions, session_bytes, estimated_sync_bytes
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.file_key,
            str(entry.path),
            str(owning_session_dir(entry.path, session_dirs)),
            entry.storage_state,
            0,
            session_id,
            selected.cwd if selected else metadata.cwd,
            project_key,
            project_label,
            json.dumps(list(project_aliases)),
            selected.git_repository_url
            if selected
            else metadata.git_repository_url or identity.git_repository_url,
            selected.git_branch if selected else metadata.git_branch,
            metadata.memory_mode,
            1 if metadata.has_base_instructions else 0,
            entry.size_bytes,
            entry.size_bytes + _ESTIMATED_SYNC_METADATA_BYTES,
        ),
    )


def insert_transition_candidates(
    connection: sqlite3.Connection,
    file_key: str,
    candidates: tuple[RawRepoPathCandidate, ...],
) -> None:
    for index, candidate in enumerate(candidates):
        connection.execute(
            """
            insert into transition_candidates (
                file_key, candidate_index, timestamp, timestamp_us, thread_id,
                raw_path, source
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_key,
                index,
                candidate.timestamp.isoformat(),
                _timestamp_us(candidate.timestamp),
                candidate.thread_id,
                candidate.raw_path,
                candidate.source,
            ),
        )


def upsert_file_fingerprint(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    entry: SessionFileInventoryEntry,
    session_id: str,
) -> None:
    now = datetime.now(UTC).isoformat()
    connection.execute(
        """
        insert or replace into files (
            file_key, path, session_dir, storage_state, size_bytes, mtime_ns,
            parsed_at, last_seen_at, missing_since, is_missing, session_id, error
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.file_key,
            str(entry.path),
            str(owning_session_dir(entry.path, session_dirs)),
            entry.storage_state,
            entry.size_bytes,
            entry.mtime_ns,
            now,
            now,
            "",
            0,
            session_id or entry.path.stem,
            "",
        ),
    )


def _same_path_alias_keys(
    connection: sqlite3.Connection, entry: SessionFileInventoryEntry
) -> tuple[str, ...]:
    return tuple(
        str(row["file_key"])
        for row in connection.execute(
            "select file_key from files where path = ? and file_key != ?",
            (str(entry.path), entry.file_key),
        )
    )


def _timestamp_us(timestamp: datetime) -> int:
    return int(timestamp.astimezone(UTC).timestamp() * 1_000_000)
