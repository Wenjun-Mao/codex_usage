from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codex_usage.models import SessionMetadata, UsageRecord
from codex_usage.project_transition_evidence import extract_repo_paths
from codex_usage.session_generation_models import RawRepoPathCandidate
from codex_usage.session_provenance import (
    is_structured_subagent,
    parent_thread_id_from_source,
)


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 2_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=UTC)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_json_line(raw_line: str | bytes) -> dict[str, Any] | None:
    line = raw_line.strip()
    if not line:
        return None
    try:
        parsed = json.loads(line)
    except (json.JSONDecodeError, RecursionError):
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_repo_path_candidates(
    payload: dict[str, Any],
    timestamp: datetime | None,
    thread_id: str,
) -> list[RawRepoPathCandidate]:
    if payload.get("type") != "function_call" or timestamp is None:
        return []
    workdir = _function_call_workdir(payload.get("arguments"))
    if not workdir:
        return []
    return [
        RawRepoPathCandidate(
            raw_path=raw_path,
            timestamp=timestamp,
            thread_id=thread_id,
            source="jsonl:response_item:function_call_workdir",
        )
        for raw_path in extract_repo_paths(workdir, preserve_exact_field=True)
    ]


def parse_session_metadata(
    payload: dict[str, Any],
    path: Path,
    timestamp: datetime | None,
) -> SessionMetadata:
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
        parent_thread_id=parent_thread_id_from_source(payload),
        memory_mode=str(payload.get("memory_mode") or ""),
        has_base_instructions=payload.get("base_instructions") is not None,
        git_repository_url=str(git.get("repository_url") or ""),
        git_branch=str(git.get("branch") or ""),
        git_commit_hash=str(git.get("commit_hash") or ""),
        is_subagent=is_structured_subagent(payload),
    )


def inherit_parent_project_identity(
    record: UsageRecord,
    parent: UsageRecord,
) -> UsageRecord:
    aliases = _dedupe_aliases(
        [record.project_key, *record.project_aliases, *parent.project_aliases],
        parent.project_key,
    )
    return replace(
        record,
        project_key=parent.project_key,
        project_label=parent.project_label,
        project_aliases=aliases,
        git_repository_url=parent.git_repository_url,
        git_branch=parent.git_branch,
    )


def extract_model(payload: dict[str, Any]) -> str:
    if payload.get("model"):
        return str(payload["model"])
    collaboration_mode = payload.get("collaboration_mode")
    if isinstance(collaboration_mode, dict):
        settings = collaboration_mode.get("settings")
        if isinstance(settings, dict) and settings.get("model"):
            return str(settings["model"])
    return ""


def extract_effort(payload: dict[str, Any]) -> str:
    if payload.get("effort"):
        return str(payload["effort"])
    collaboration_mode = payload.get("collaboration_mode")
    if isinstance(collaboration_mode, dict):
        settings = collaboration_mode.get("settings")
        if isinstance(settings, dict) and settings.get("reasoning_effort"):
            return str(settings["reasoning_effort"])
    return ""


def extract_collaboration_mode(payload: dict[str, Any]) -> str:
    collaboration_mode = payload.get("collaboration_mode")
    if isinstance(collaboration_mode, dict) and collaboration_mode.get("mode"):
        return str(collaboration_mode["mode"])
    return ""


def _function_call_workdir(arguments: object) -> str:
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except (ValueError, RecursionError):
            return ""
    else:
        parsed = arguments
    if not isinstance(parsed, dict):
        return ""
    workdir = parsed.get("workdir")
    return workdir if isinstance(workdir, str) else ""


def _dedupe_aliases(values: list[str], primary_key: str) -> tuple[str, ...]:
    aliases: list[str] = []
    seen = {primary_key}
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        aliases.append(value)
    return tuple(aliases)
