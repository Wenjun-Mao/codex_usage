from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.parser import parse_session_file, parse_timestamp
from codex_usage.project_identity import resolve_project_identity
from codex_usage.project_transitions import (
    ProjectTransition,
    collect_repo_path_observations,
    infer_project_transitions,
)
from codex_usage.session_cache_models import CacheStats, CachedFileSummary
from codex_usage.session_cache_schema import (
    _CLEAN_VALUE,
    _DIRTY_VALUE,
    _PROJECT_TRANSITIONS_DIRTY_KEY,
    _REPARSE_REQUIRED_ERROR,
)
from codex_usage.session_files import owning_session_dir, read_session_metadata
from codex_usage.session_inventory import SessionFileInventoryEntry

_ESTIMATED_SYNC_METADATA_BYTES = 4096


def _refresh_files(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    inventory: list[SessionFileInventoryEntry],
    *,
    rebuilt: bool,
) -> CacheStats:
    now = datetime.now(UTC).isoformat()
    cached_rows = {
        str(row["file_key"]): row
        for row in connection.execute("select file_key, path, size_bytes, mtime_ns, is_missing, error from files")
    }
    current_keys = {entry.file_key for entry in inventory}
    missing_marked = 0
    for file_key, row in cached_rows.items():
        if file_key not in current_keys and int(row["is_missing"]) == 0:
            connection.execute(
                """
                update files
                set is_missing = 1, missing_since = ?, last_seen_at = ?,
                    error = case when error = ? then '' else error end
                where file_key = ?
                """,
                (now, now, _REPARSE_REQUIRED_ERROR, file_key),
            )
            connection.execute("update session_metadata set is_missing = 1 where file_key = ?", (file_key,))
            missing_marked += 1

    parsed = 0
    reused = 0
    errors = 0
    for entry in inventory:
        cached = cached_rows.get(entry.file_key)
        if (
            not rebuilt
            and cached
            and str(cached["path"]) == str(entry.path)
            and int(cached["size_bytes"]) == entry.size_bytes
            and int(cached["mtime_ns"]) == entry.mtime_ns
            and int(cached["is_missing"]) == 0
            and not cached["error"]
        ):
            reused += 1
            connection.execute("update files set last_seen_at = ? where file_key = ?", (now, entry.file_key))
            continue
        path = entry.path
        try:
            records = parse_session_file(path)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            record_file_error(connection, session_dirs, entry, error)
            parsed += 1
            errors += 1
            continue
        replace_file_generation(connection, session_dirs, entry, tuple(records))
        parsed += 1
    if rebuilt or parsed or missing_marked:
        _set_project_transitions_dirty(connection, dirty=True)
    connection.commit()
    missing_count = connection.execute("select count(*) from files where is_missing = 1").fetchone()[0]
    return CacheStats(
        files_total=len(inventory),
        files_current=len(inventory),
        files_archived=sum(1 for entry in inventory if entry.storage_state == "archived"),
        files_parsed=parsed,
        files_reused=reused,
        files_removed=missing_marked,
        files_missing_retained=int(missing_count),
        file_errors=errors,
        rebuilt=rebuilt,
    )


def replace_file_generation(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    entry: SessionFileInventoryEntry,
    records: tuple[UsageRecord, ...],
) -> None:
    path = entry.path
    _delete_same_path_alias_rows(connection, entry)
    _delete_file_rows(connection, entry.file_key)
    for index, record in enumerate(records):
        _insert_record(connection, entry.file_key, path, index, record)
    _insert_file_summary(connection, session_dirs, entry, records)
    now = datetime.now(UTC).isoformat()
    connection.execute(
        """
        insert or replace into files
            (
                file_key, path, session_dir, storage_state, size_bytes, mtime_ns,
                parsed_at, last_seen_at, missing_since, is_missing, session_id, error
            )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.file_key,
            str(path),
            str(owning_session_dir(path, session_dirs)),
            entry.storage_state,
            entry.size_bytes,
            entry.mtime_ns,
            now,
            now,
            "",
            0,
            records[0].session_id if records else path.stem,
            "",
        ),
    )


def record_file_error(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    entry: SessionFileInventoryEntry,
    error: str,
) -> None:
    now = datetime.now(UTC).isoformat()
    existing = connection.execute("select 1 from files where file_key = ?", (entry.file_key,)).fetchone()
    if existing is not None:
        connection.execute(
            """
            update files
            set last_seen_at = ?, missing_since = null, is_missing = 0, error = ?
            where file_key = ?
            """,
            (now, error, entry.file_key),
        )
        connection.execute("update session_metadata set is_missing = 0 where file_key = ?", (entry.file_key,))
        return
    connection.execute(
        """
        insert into files
            (
                file_key, path, session_dir, storage_state, size_bytes, mtime_ns,
                parsed_at, last_seen_at, missing_since, is_missing, session_id, error
            )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            entry.path.stem,
            error,
        ),
    )


def _delete_file_rows(connection: sqlite3.Connection, file_key: str) -> None:
    connection.execute("delete from usage_records where file_key = ?", (file_key,))
    connection.execute("delete from session_metadata where file_key = ?", (file_key,))


def _delete_same_path_alias_rows(
    connection: sqlite3.Connection,
    entry: SessionFileInventoryEntry,
) -> None:
    alias_keys = tuple(
        str(row["file_key"])
        for row in connection.execute(
            "select file_key from files where path = ? and file_key != ?",
            (str(entry.path), entry.file_key),
        )
    )
    for alias_key in alias_keys:
        _delete_file_rows(connection, alias_key)
        connection.execute("delete from files where file_key = ?", (alias_key,))


def _insert_record(connection: sqlite3.Connection, file_key: str, file_path: Path, index: int, record: UsageRecord) -> None:
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
            file_key,
            str(file_path),
            index,
            record.timestamp.isoformat(),
            int(record.timestamp.timestamp() * 1_000_000),
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


def _insert_file_summary(
    connection: sqlite3.Connection,
    session_dirs: list[Path],
    entry: SessionFileInventoryEntry,
    records: tuple[UsageRecord, ...],
) -> None:
    path = entry.path
    metadata = read_session_metadata(path)
    selected = records[-1] if records else None
    identity = None if selected is not None or metadata is None else resolve_project_identity(metadata)
    session_id = selected.session_id if selected else (metadata.session_id if metadata else path.stem)
    project_key = selected.project_key if selected else (identity.key if identity else "")
    project_label = selected.project_label if selected else (identity.label if identity else "")
    project_aliases = selected.project_aliases if selected else (identity.aliases if identity else ())
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
            str(path),
            str(owning_session_dir(path, session_dirs)),
            entry.storage_state,
            0,
            session_id,
            selected.cwd if selected else (metadata.cwd if metadata else ""),
            project_key,
            project_label,
            json.dumps(list(project_aliases)),
            selected.git_repository_url if selected else (metadata.git_repository_url if metadata else ""),
            selected.git_branch if selected else (metadata.git_branch if metadata else ""),
            metadata.memory_mode if metadata else "",
            1 if metadata and metadata.has_base_instructions else 0,
            entry.size_bytes,
            entry.size_bytes + _ESTIMATED_SYNC_METADATA_BYTES,
        ),
    )


def _load_records_by_file_key(connection: sqlite3.Connection, selected_keys: set[str]) -> dict[str, list[UsageRecord]]:
    if not selected_keys:
        return {}
    records_by_file: dict[str, list[UsageRecord]] = {}
    for row in connection.execute("select * from usage_records order by file_key, record_index"):
        if row["file_key"] not in selected_keys:
            continue
        records_by_file.setdefault(str(row["file_key"]), []).append(_row_to_record(row))
    return records_by_file


def _row_to_record(row: sqlite3.Row) -> UsageRecord:
    return UsageRecord(
        timestamp=parse_timestamp(row["timestamp"]) or datetime.fromtimestamp(0, tz=UTC),
        usage=TokenUsage(
            input_tokens=int(row["input_tokens"]),
            cached_input_tokens=int(row["cached_input_tokens"]),
            cache_write_input_tokens=int(row["cache_write_input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            reasoning_output_tokens=int(row["reasoning_output_tokens"]),
            total_tokens=int(row["total_tokens"]),
        ),
        session_id=row["session_id"],
        file_path=Path(row["file_path"]),
        model=row["model"],
        turn_id=row["turn_id"] or "",
        effort=row["effort"] or "",
        collaboration_mode=row["collaboration_mode"] or "",
        project_key=row["project_key"],
        project_label=row["project_label"],
        project_aliases=tuple(json.loads(row["project_aliases_json"] or "[]")),
        cwd=row["cwd"] or "",
        git_repository_url=row["git_repository_url"] or "",
        git_branch=row["git_branch"] or "",
        parent_thread_id=row["parent_thread_id"] or "",
    )


def _refresh_or_load_transitions(
    connection: sqlite3.Connection,
    *,
    session_dirs: list[Path],
    session_files: list[Path],
    records: list[UsageRecord],
    auto_transitions: bool,
) -> list[ProjectTransition]:
    dirty = _project_transitions_are_dirty(connection)
    if not auto_transitions:
        if dirty:
            _set_project_transitions_dirty(connection, dirty=True)
            connection.commit()
        return []
    if dirty:
        observations = collect_repo_path_observations(session_dirs, session_files)
        transitions = infer_project_transitions(records, observations)
        _replace_project_transitions(connection, transitions)
        return transitions
    return _load_transitions(connection)


def _project_transitions_are_dirty(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "select value from schema_meta where key = ?",
        (_PROJECT_TRANSITIONS_DIRTY_KEY,),
    ).fetchone()
    return row is None or str(row["value"]) != _CLEAN_VALUE


def _set_project_transitions_dirty(connection: sqlite3.Connection, *, dirty: bool) -> None:
    connection.execute(
        """
        insert into schema_meta (key, value) values (?, ?)
        on conflict(key) do update set value = excluded.value
        """,
        (_PROJECT_TRANSITIONS_DIRTY_KEY, _DIRTY_VALUE if dirty else _CLEAN_VALUE),
    )


def _replace_project_transitions(
    connection: sqlite3.Connection,
    transitions: list[ProjectTransition],
) -> None:
    connection.execute("begin immediate")
    try:
        connection.execute("delete from project_transitions")
        for transition in transitions:
            connection.execute(
                """
                insert into project_transitions (
                    owner_thread_id, source_key, source_label, target_key, target_label,
                    effective_from, confidence, evidence_json, thread_ids_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "",
                    transition.source_key,
                    transition.source_label,
                    transition.target_key,
                    transition.target_label,
                    transition.effective_from.isoformat(),
                    transition.confidence,
                    json.dumps(list(transition.evidence)),
                    json.dumps(list(transition.thread_ids)),
                ),
            )
        _set_project_transitions_dirty(connection, dirty=False)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _load_transitions(connection: sqlite3.Connection) -> list[ProjectTransition]:
    transitions: list[ProjectTransition] = []
    for row in connection.execute("select * from project_transitions order by effective_from, source_key, target_key"):
        timestamp = parse_timestamp(row["effective_from"])
        if timestamp is None:
            continue
        transitions.append(
            ProjectTransition(
                source_key=row["source_key"],
                source_label=row["source_label"],
                target_key=row["target_key"],
                target_label=row["target_label"],
                effective_from=timestamp,
                confidence=int(row["confidence"]),
                evidence=tuple(json.loads(row["evidence_json"] or "[]")),
                thread_ids=tuple(json.loads(row["thread_ids_json"] or "[]")),
            )
        )
    return transitions


def _load_file_summaries(
    connection: sqlite3.Connection,
    inventory: list[SessionFileInventoryEntry],
    session_dirs: list[Path],
) -> dict[Path, CachedFileSummary]:
    selected = {entry.file_key for entry in inventory}
    summaries: dict[Path, CachedFileSummary] = {}
    for row in connection.execute("select * from session_metadata"):
        if row["file_key"] not in selected:
            continue
        path = Path(row["file_path"])
        summaries[path] = CachedFileSummary(
            file_path=path,
            session_dir=Path(row["session_dir"]) if row["session_dir"] else owning_session_dir(path, session_dirs),
            session_id=row["session_id"],
            cwd=row["cwd"] or "",
            project_key=row["project_key"] or "",
            project_label=row["project_label"] or "",
            project_aliases=tuple(json.loads(row["project_aliases_json"] or "[]")),
            git_repository_url=row["git_repository_url"] or "",
            git_branch=row["git_branch"] or "",
            memory_mode=row["memory_mode"] or "",
            has_base_instructions=bool(row["has_base_instructions"]),
            session_bytes=int(row["session_bytes"]),
            estimated_sync_bytes=int(row["estimated_sync_bytes"]),
            file_key=row["file_key"] or "",
            storage_state=row["storage_state"] or "active",
            is_missing=bool(row["is_missing"]),
        )
    return summaries


def _load_file_errors(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row["path"]): str(row["error"])
        for row in connection.execute("select path, error from files where error is not null and error != ''")
    }


def _missing_file_keys(connection: sqlite3.Connection) -> set[str]:
    return {str(row["file_key"]) for row in connection.execute("select file_key from files where is_missing = 1")}


def _retained_missing_files(connection: sqlite3.Connection) -> list[Path]:
    return [
        Path(row["path"])
        for row in connection.execute("select path from files where is_missing = 1 order by path")
    ]
