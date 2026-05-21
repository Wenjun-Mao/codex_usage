from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codex_usage.models import UNKNOWN, SessionMetadata, TokenUsage, UsageRecord
from codex_usage.project_identity import resolve_project_identity


def parse_session_files(paths: Iterable[Path]) -> list[UsageRecord]:
    records: list[UsageRecord] = []
    for path in paths:
        records.extend(parse_session_file(path))
    return records


def parse_session_file(path: Path) -> list[UsageRecord]:
    metadata = SessionMetadata(session_id=path.stem, file_path=path)
    records: list[UsageRecord] = []
    previous_usage: TokenUsage | None = None
    root_session_id = ""
    root_session_is_fork = False
    counted_root_fork_usage = False
    current_model = UNKNOWN
    current_turn_id = ""
    current_effort = ""
    current_mode = ""

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            obj = _parse_json_line(raw_line)
            if obj is None:
                continue

            event_timestamp = parse_timestamp(obj.get("timestamp"))
            event_type = obj.get("type")
            payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}

            if event_type == "session_meta":
                metadata = _parse_session_metadata(payload, path, event_timestamp)
                if not root_session_id:
                    root_session_id = metadata.session_id
                    root_session_is_fork = bool(metadata.forked_from_id)
                continue

            if event_type == "turn_context":
                current_turn_id = str(payload.get("turn_id") or current_turn_id)
                current_model = _extract_model(payload) or current_model
                current_effort = _extract_effort(payload) or current_effort
                current_mode = _extract_collaboration_mode(payload) or current_mode
                continue

            if event_type != "event_msg":
                continue

            payload_type = payload.get("type")
            if payload_type == "task_started":
                current_turn_id = str(payload.get("turn_id") or current_turn_id)
                current_mode = str(payload.get("collaboration_mode_kind") or current_mode)
                continue
            if payload_type != "token_count":
                continue

            info = payload.get("info")
            if not isinstance(info, dict):
                continue

            total_usage = TokenUsage.from_mapping(info.get("total_token_usage"))
            had_previous_usage = previous_usage is not None
            delta = total_usage.positive_delta(previous_usage)
            previous_usage = total_usage
            if delta is None:
                continue

            is_root_session = not root_session_id or metadata.session_id == root_session_id
            if root_session_is_fork and not is_root_session:
                continue
            # Fork files can replay imported parent history before actual fork work. A first root
            # snapshot without a prior baseline is inherited context, not newly consumed tokens.
            if root_session_is_fork and is_root_session and not counted_root_fork_usage and not had_previous_usage:
                continue

            timestamp = event_timestamp or metadata.timestamp
            if timestamp is None:
                continue

            project_identity = resolve_project_identity(metadata)
            records.append(
                UsageRecord(
                    timestamp=timestamp,
                    usage=delta,
                    session_id=metadata.session_id,
                    file_path=path,
                    model=current_model,
                    turn_id=current_turn_id,
                    effort=current_effort,
                    collaboration_mode=current_mode,
                    project_key=project_identity.key,
                    project_label=project_identity.label,
                    project_aliases=project_identity.aliases,
                    cwd=metadata.cwd,
                    git_repository_url=metadata.git_repository_url or project_identity.git_repository_url,
                    git_branch=metadata.git_branch,
                )
            )
            if root_session_is_fork and is_root_session:
                counted_root_fork_usage = True

    return records


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 2_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=UTC)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_json_line(raw_line: str) -> dict[str, Any] | None:
    line = raw_line.strip()
    if not line:
        return None
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_session_metadata(payload: dict[str, Any], path: Path, timestamp: datetime | None) -> SessionMetadata:
    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    return SessionMetadata(
        session_id=str(payload.get("id") or path.stem),
        file_path=path,
        timestamp=parse_timestamp(payload.get("timestamp")) or timestamp,
        cwd=str(payload.get("cwd") or ""),
        originator=str(payload.get("originator") or ""),
        source=str(payload.get("source") or ""),
        cli_version=str(payload.get("cli_version") or ""),
        model_provider=str(payload.get("model_provider") or ""),
        forked_from_id=str(payload.get("forked_from_id") or ""),
        git_repository_url=str(git.get("repository_url") or ""),
        git_branch=str(git.get("branch") or ""),
        git_commit_hash=str(git.get("commit_hash") or ""),
    )


def _extract_model(payload: dict[str, Any]) -> str:
    if payload.get("model"):
        return str(payload["model"])
    collaboration_mode = payload.get("collaboration_mode")
    if isinstance(collaboration_mode, dict):
        settings = collaboration_mode.get("settings")
        if isinstance(settings, dict) and settings.get("model"):
            return str(settings["model"])
    return ""


def _extract_effort(payload: dict[str, Any]) -> str:
    if payload.get("effort"):
        return str(payload["effort"])
    collaboration_mode = payload.get("collaboration_mode")
    if isinstance(collaboration_mode, dict):
        settings = collaboration_mode.get("settings")
        if isinstance(settings, dict) and settings.get("reasoning_effort"):
            return str(settings["reasoning_effort"])
    return ""


def _extract_collaboration_mode(payload: dict[str, Any]) -> str:
    collaboration_mode = payload.get("collaboration_mode")
    if isinstance(collaboration_mode, dict) and collaboration_mode.get("mode"):
        return str(collaboration_mode["mode"])
    return ""
