from __future__ import annotations

import json
from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codex_usage.models import SessionMetadata
from codex_usage.parser import parse_timestamp
from codex_usage.session_provenance import (
    is_structured_subagent,
    parent_thread_id_from_source,
)


_MAX_SESSION_METADATA_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class SessionMetadataRead:
    metadata: SessionMetadata | None
    diagnostic: str = ""


def read_session_metadata(path: Path) -> SessionMetadata | None:
    return read_session_metadata_bounded(path).metadata


def read_session_metadata_bounded(
    path: Path,
    *,
    max_bytes: int = _MAX_SESSION_METADATA_BYTES,
) -> SessionMetadataRead:
    """Read only the small metadata prefix used to identify a session file."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    consumed = 0
    try:
        with path.open("rb") as handle:
            while consumed < max_bytes:
                remaining = max_bytes - consumed
                raw_line = handle.readline(remaining + 1)
                if not raw_line:
                    break
                consumed += len(raw_line)
                if len(raw_line) > remaining:
                    return SessionMetadataRead(None, "session_meta_limit_exceeded")
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                obj = _parse_json_line(line)
                if obj is None or obj.get("type") != "session_meta":
                    continue
                payload = (
                    obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
                )
                git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
                return SessionMetadataRead(
                    SessionMetadata(
                        session_id=str(payload.get("id") or path.stem),
                        file_path=path,
                        timestamp=parse_timestamp(payload.get("timestamp"))
                        or parse_timestamp(obj.get("timestamp")),
                        cwd=str(payload.get("cwd") or ""),
                        originator=str(payload.get("originator") or ""),
                        source=str(payload.get("source") or ""),
                        cli_version=str(payload.get("cli_version") or ""),
                        model_provider=str(payload.get("model_provider") or ""),
                        forked_from_id=str(payload.get("forked_from_id") or ""),
                        parent_thread_id=parent_thread_id_from_source(payload),
                        memory_mode=str(payload.get("memory_mode") or ""),
                        has_base_instructions=payload.get("base_instructions")
                        is not None,
                        git_repository_url=str(git.get("repository_url") or ""),
                        git_branch=str(git.get("branch") or ""),
                        git_commit_hash=str(git.get("commit_hash") or ""),
                        is_subagent=is_structured_subagent(payload),
                    )
                )
    except OSError:
        return SessionMetadataRead(None, "session_meta_unreadable")
    return SessionMetadataRead(None, "session_meta_missing")


def load_all_index_entries(session_dirs: list[Path]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    index_paths = dict.fromkeys(
        session_index_path_for_session_dir(session_dir) for session_dir in session_dirs
    )
    for index_path in index_paths:
        for entry in read_index_entries(index_path):
            thread_id = str(entry.get("id") or "")
            if not thread_id:
                continue
            existing = entries.get(thread_id)
            if existing is None or timestamp_key(
                str(entry.get("updated_at") or "")
            ) >= timestamp_key(str(existing.get("updated_at") or "")):
                entries[thread_id] = entry
    return entries


def read_index_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not path.is_file():
        return entries
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                obj = _parse_json_line(line)
                if obj is not None:
                    entries.append(obj)
    except (OSError, UnicodeDecodeError):
        return []
    return entries


def owning_session_dir(path: Path, session_dirs: list[Path]) -> Path:
    resolved = path.resolve(strict=False)
    for session_dir in session_dirs:
        session_root = session_dir.resolve(strict=False)
        if resolved == session_root or session_root in resolved.parents:
            return session_dir
    return session_dirs[0] if session_dirs else path.parent


def codex_home_from_session_dir(session_dir: Path) -> Path:
    return (
        session_dir.parent
        if session_dir.name.casefold() in {"sessions", "archived_sessions"}
        else session_dir
    )


def session_index_path_for_session_dir(session_dir: Path) -> Path:
    return codex_home_from_session_dir(session_dir) / "session_index.jsonl"


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def session_updated_at(path: Path, timestamp: datetime | None) -> str:
    if timestamp is not None:
        return timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return (
        datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def timestamp_key(value: str) -> datetime:
    return parse_timestamp(value) or datetime.min.replace(tzinfo=UTC)


def _parse_json_line(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
