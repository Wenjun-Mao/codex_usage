from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from codex_usage.parser import parse_timestamp
from codex_usage.project_identity import normalize_project_key


_WINDOWS_PATH_PATTERN = r"[A-Za-z]:[\\/](?:[^\\/:*?\"<>|\r\n`]+[\\/])*[^\\/:*?\"<>|\r\n`]+"
_DELIMITED_WINDOWS_PATH_PATTERN = re.compile(rf"(?P<delimiter>[`\"])(?P<path>{_WINDOWS_PATH_PATTERN})(?P=delimiter)")
_BARE_WINDOWS_PATH_PATTERN = re.compile(r"[A-Za-z]:[\\/](?:[^\\/:*?\"<>|\s\r\n`]+[\\/])*[^\\/:*?\"<>|\s\r\n`]+")


@dataclass(frozen=True)
class RepoPathObservation:
    raw_path: str
    resolved_path: str
    project_key: str
    project_label: str
    timestamp: datetime
    thread_id: str
    source: str

    def to_evidence_text(self) -> str:
        return (
            f"verified repo path {self.resolved_path} -> {self.project_key} "
            f"(thread {self.thread_id}, source {self.source})"
        )


def extract_windows_paths(text: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    candidates: list[tuple[int, str, bool]] = []
    delimited_spans: list[tuple[int, int]] = []

    for match in _DELIMITED_WINDOWS_PATH_PATTERN.finditer(text):
        delimited_spans.append(match.span())
        candidates.append((match.start("path"), match.group("path"), False))

    for match in _BARE_WINDOWS_PATH_PATTERN.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in delimited_spans):
            continue
        candidates.append((match.start(), match.group(0), True))

    for _, candidate, trim_trailing_punctuation in sorted(candidates, key=lambda item: item[0]):
        value = candidate.rstrip(".,;:)]}'\"") if trim_trailing_punctuation else candidate
        if value and value not in seen:
            seen.add(value)
            paths.append(value)
    return paths


def verified_repo_observation_from_path(
    raw_path: str | Path,
    timestamp: datetime,
    thread_id: str,
    source: str,
) -> RepoPathObservation | None:
    raw_path_text = str(raw_path)
    try:
        path = Path(raw_path).expanduser()
        if not path.exists():
            return None
        resolved_path = path.resolve()
        project_key = normalize_project_key(str(resolved_path))
    except (OSError, RuntimeError, ValueError):
        return None

    if not project_key.startswith("https://"):
        return None

    return RepoPathObservation(
        raw_path=raw_path_text,
        resolved_path=str(resolved_path),
        project_key=project_key,
        project_label=_label_from_project_key(project_key),
        timestamp=timestamp,
        thread_id=thread_id,
        source=source,
    )


def collect_repo_path_observations(
    session_dirs: list[Path],
    session_files: list[Path],
) -> list[RepoPathObservation]:
    observations: list[RepoPathObservation] = []
    verification_cache: _VerificationCache = {}
    observations.extend(_collect_jsonl_observations(session_files, verification_cache))
    observations.extend(_collect_state_sqlite_observations(session_dirs, verification_cache))
    return _dedupe_observations(observations)


_VerifiedRepoDetails = tuple[str, str, str]
_VerificationCache = dict[str, _VerifiedRepoDetails | None]


def _collect_jsonl_observations(
    session_files: list[Path],
    verification_cache: _VerificationCache,
) -> list[RepoPathObservation]:
    observations: list[RepoPathObservation] = []
    for path in session_files:
        current_thread_id = path.stem
        try:
            handle = path.open("r", encoding="utf-8", errors="ignore")
        except OSError:
            continue

        try:
            with handle:
                for raw_line in handle:
                    obj = _parse_json_line(raw_line)
                    if obj is None:
                        continue

                    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
                    event_type = obj.get("type")
                    if event_type == "session_meta":
                        current_thread_id = _thread_id_from_payload(payload) or current_thread_id

                    timestamp = parse_timestamp(obj.get("timestamp"))
                    if timestamp is None:
                        continue

                    for source, text in _jsonl_observation_texts(event_type, payload):
                        for raw_path in extract_windows_paths(text):
                            observation = _cached_verified_repo_observation(
                                raw_path=raw_path,
                                timestamp=timestamp,
                                thread_id=current_thread_id,
                                source=source,
                                cache=verification_cache,
                            )
                            if observation is not None:
                                observations.append(observation)
        except (OSError, UnicodeDecodeError):
            continue
    return observations


def _collect_state_sqlite_observations(
    session_dirs: list[Path],
    verification_cache: _VerificationCache,
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
            for raw_path in extract_windows_paths(text):
                observation = _cached_verified_repo_observation(
                    raw_path=raw_path,
                    timestamp=timestamp,
                    thread_id=thread_id,
                    source="state_5.sqlite:threads",
                    cache=verification_cache,
                )
                if observation is not None:
                    observations.append(observation)
    return observations


_SQLITE_THREAD_TIMESTAMP_FIELDS = ("updated_at_ms", "updated_at", "created_at_ms", "created_at")
_SQLITE_THREAD_TEXT_FIELDS = ("cwd",)


def _read_thread_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    columns = _thread_table_columns(con)
    if "id" not in columns:
        return []

    selected = ["id"]
    selected.extend(field for field in _SQLITE_THREAD_TIMESTAMP_FIELDS if field in columns)
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


def _parse_json_line(raw_line: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw_line)
    except (ValueError, RecursionError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _cached_verified_repo_observation(
    raw_path: str,
    timestamp: datetime,
    thread_id: str,
    source: str,
    cache: _VerificationCache,
) -> RepoPathObservation | None:
    if raw_path not in cache:
        observation = verified_repo_observation_from_path(
            raw_path=raw_path,
            timestamp=timestamp,
            thread_id=thread_id,
            source=source,
        )
        cache[raw_path] = (
            None
            if observation is None
            else (observation.resolved_path, observation.project_key, observation.project_label)
        )

    details = cache[raw_path]
    if details is None:
        return None

    resolved_path, project_key, project_label = details
    return RepoPathObservation(
        raw_path=raw_path,
        resolved_path=resolved_path,
        project_key=project_key,
        project_label=project_label,
        timestamp=timestamp,
        thread_id=thread_id,
        source=source,
    )


def _thread_id_from_payload(payload: dict[str, Any]) -> str:
    return str(payload.get("id") or "")


def _source_event_type(value: object) -> str:
    return str(value) if value else "event"


def _jsonl_observation_texts(event_type: object, payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Return only execution context that can act as project-switch evidence."""
    source_event = _source_event_type(event_type)
    payload_type = str(payload.get("type") or "")

    if source_event != "response_item":
        return []

    if payload_type == "function_call":
        workdir = _function_call_workdir(payload.get("arguments"))
        return [("jsonl:response_item:function_call_workdir", workdir)] if workdir else []

    return []


def _function_call_workdir(arguments: object) -> str:
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except ValueError:
            return ""
    else:
        parsed = arguments

    if not isinstance(parsed, dict):
        return ""

    workdir = parsed.get("workdir")
    return workdir if isinstance(workdir, str) else ""


def _codex_home_from_session_dir(session_dir: Path) -> Path:
    return session_dir.parent


def _dedupe_observations(observations: list[RepoPathObservation]) -> list[RepoPathObservation]:
    unique: list[RepoPathObservation] = []
    seen: set[tuple[str, str, str, datetime]] = set()
    for observation in observations:
        key = (
            observation.thread_id,
            observation.project_key,
            observation.resolved_path,
            observation.timestamp,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(observation)
    return sorted(unique, key=lambda item: (item.timestamp, item.thread_id, item.project_key, item.source))


def _label_from_project_key(value: str) -> str:
    cleaned = value.strip().rstrip("/").removesuffix(".git")
    return cleaned.rsplit("/", 1)[-1] or cleaned
