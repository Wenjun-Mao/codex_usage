from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.parser import parse_timestamp
from codex_usage.project_transitions import (
    ProjectTransition,
    collect_repo_path_observations,
    infer_project_transitions,
)
from codex_usage.session_cache_models import CachedFileSummary
from codex_usage.session_cache_schema import (
    _CLEAN_VALUE,
    _DIRTY_VALUE,
    _PROJECT_TRANSITIONS_DIRTY_KEY,
)
from codex_usage.session_files import owning_session_dir
from codex_usage.session_inventory import SessionFileInventoryEntry


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
