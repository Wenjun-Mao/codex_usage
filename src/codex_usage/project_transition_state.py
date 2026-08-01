from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import codex_usage.project_transition_evidence as evidence_module
from codex_usage.parser import parse_timestamp
from codex_usage.project_transition_evidence import (
    RepoPathObservation,
    VerificationCache,
)


_SQLITE_THREAD_TIMESTAMP_FIELDS = (
    "updated_at_ms",
    "updated_at",
    "created_at_ms",
    "created_at",
)
_SQLITE_THREAD_TEXT_FIELDS = ("cwd",)


def collect_state_repo_path_observations(
    session_dirs: list[Path],
    *,
    verification_cache: VerificationCache,
) -> list[RepoPathObservation]:
    observations: list[RepoPathObservation] = []
    for session_dir in session_dirs:
        db_path = _codex_home_from_session_dir(session_dir) / "state_5.sqlite"
        if not db_path.is_file():
            continue

        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            try:
                rows = _read_thread_rows(con)
            finally:
                con.close()
        except sqlite3.Error:
            continue

        for row in rows:
            timestamp = _sqlite_row_timestamp(row)
            if timestamp is None:
                continue

            thread_id = str(row["id"] or "")
            if not thread_id:
                continue

            text = "\n".join(
                str(row[field])
                for field in _SQLITE_THREAD_TEXT_FIELDS
                if field in row.keys() and row[field] is not None
            )
            for raw_path in evidence_module.extract_repo_paths(
                text,
                preserve_exact_field=True,
            ):
                observation = evidence_module._cached_verified_repo_observation(
                    raw_path=raw_path,
                    timestamp=timestamp,
                    thread_id=thread_id,
                    source="state_5.sqlite:threads",
                    cache=verification_cache,
                )
                if observation is not None:
                    observations.append(observation)
    return observations


def _read_thread_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    columns = _thread_table_columns(con)
    if "id" not in columns:
        return []

    selected = ["id"]
    selected.extend(
        field for field in _SQLITE_THREAD_TIMESTAMP_FIELDS if field in columns
    )
    selected.extend(field for field in _SQLITE_THREAD_TEXT_FIELDS if field in columns)
    if len(selected) == 1:
        return []

    sql = f"select {', '.join(selected)} from threads"
    return list(con.execute(sql))


def _thread_table_columns(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("pragma table_info(threads)").fetchall()
    return {str(row["name"]).casefold() for row in rows if row["name"]}


def _sqlite_row_timestamp(row: sqlite3.Row) -> datetime | None:
    keys = row.keys()
    for field in _SQLITE_THREAD_TIMESTAMP_FIELDS:
        if field not in keys:
            continue
        timestamp = _sqlite_timestamp(row[field])
        if timestamp is not None:
            return timestamp
    return None


def _sqlite_timestamp(value: object) -> datetime | None:
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    return parse_timestamp(value)


def _codex_home_from_session_dir(session_dir: Path) -> Path:
    return session_dir.parent
