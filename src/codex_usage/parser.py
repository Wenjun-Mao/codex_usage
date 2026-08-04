from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codex_usage.models import (
    UNKNOWN,
    SessionMetadata,
    TokenUsage,
    UsageRecord,
    usage_role_from_is_subagent,
)
from codex_usage.project_identity import resolve_project_identity
from codex_usage.project_transition_evidence import extract_repo_paths
from codex_usage.session_generation_models import (
    ParsedSessionGeneration,
    RawRepoPathCandidate,
)
from codex_usage.session_provenance import (
    is_structured_subagent,
    parent_thread_id_from_source,
)

_USAGE_EVENT_MARKERS = (
    '"session_meta"',
    '"turn_context"',
    '"token_count"',
    '"task_started"',
)
_FUNCTION_CALL_MARKERS = ('"response_item"', '"function_call"')


class _PartialSessionGenerationReadError(OSError):
    def __init__(
        self,
        candidates: tuple[RawRepoPathCandidate, ...],
        cause: OSError | UnicodeDecodeError,
    ) -> None:
        super().__init__(str(cause))
        self.candidates = candidates
        self.cause = cause


def _line_may_affect_usage(raw_line: str) -> bool:
    return (
        any(marker in raw_line for marker in _USAGE_EVENT_MARKERS)
        or all(marker in raw_line for marker in _FUNCTION_CALL_MARKERS)
        or r"\u" in raw_line
        or r"\U" in raw_line
    )


def parse_session_files(paths: Iterable[Path]) -> list[UsageRecord]:
    return finalize_session_records([parse_session_file(path) for path in paths])


def finalize_session_records(
    records_by_file: Iterable[list[UsageRecord]],
    *,
    identity_records: Iterable[UsageRecord] = (),
) -> list[UsageRecord]:
    grouped = list(records_by_file)
    identity_by_session: dict[str, UsageRecord] = {}
    for file_records in grouped:
        for record in file_records:
            if record.git_repository_url:
                identity_by_session[record.session_id] = record
    for record in identity_records:
        if record.git_repository_url:
            identity_by_session[record.session_id] = record

    records: list[UsageRecord] = []
    for file_records in grouped:
        for record in file_records:
            parent_identity = identity_by_session.get(record.parent_thread_id)
            if parent_identity is not None and not record.git_repository_url:
                records.append(_inherit_parent_project_identity(record, parent_identity))
            else:
                records.append(record)
    return records


def parse_session_file(path: Path) -> list[UsageRecord]:
    return list(parse_session_generation(path).records)


def parse_session_generation(
    path: Path,
    *,
    _capture_partial_candidates: bool = False,
) -> ParsedSessionGeneration:
    metadata = SessionMetadata(session_id=path.stem, file_path=path)
    root_metadata: SessionMetadata | None = None
    records: list[UsageRecord] = []
    candidates: list[RawRepoPathCandidate] = []
    previous_usage: TokenUsage | None = None
    root_session_id = ""
    root_session_is_fork = False
    counted_root_fork_usage = False
    current_model = UNKNOWN
    current_turn_id = ""
    current_effort = ""
    current_mode = ""

    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                if not _line_may_affect_usage(raw_line):
                    continue
                obj = _parse_json_line(raw_line)
                if obj is None:
                    continue

                event_timestamp = parse_timestamp(obj.get("timestamp"))
                event_type = obj.get("type")
                payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}

                if event_type == "session_meta":
                    metadata = _parse_session_metadata(payload, path, event_timestamp)
                    if root_metadata is None:
                        root_metadata = metadata
                        root_session_id = metadata.session_id
                        root_session_is_fork = bool(metadata.forked_from_id)
                    continue

                if event_type == "response_item":
                    candidates.extend(
                        _extract_repo_path_candidates(
                            payload,
                            event_timestamp,
                            metadata.session_id,
                        )
                    )
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
                        usage_role=usage_role_from_is_subagent(metadata.is_subagent),
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
                        parent_thread_id=metadata.parent_thread_id,
                    )
                )
                if root_session_is_fork and is_root_session:
                    counted_root_fork_usage = True
    except (OSError, UnicodeDecodeError) as error:
        if _capture_partial_candidates:
            raise _PartialSessionGenerationReadError(tuple(candidates), error) from error
        raise

    return ParsedSessionGeneration(
        records=tuple(records),
        metadata=root_metadata or SessionMetadata(session_id=path.stem, file_path=path),
        candidates=tuple(candidates),
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


def _parse_json_line(raw_line: str) -> dict[str, Any] | None:
    line = raw_line.strip()
    if not line:
        return None
    try:
        parsed = json.loads(line)
    except (json.JSONDecodeError, RecursionError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_repo_path_candidates(
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
        parent_thread_id=parent_thread_id_from_source(payload),
        memory_mode=str(payload.get("memory_mode") or ""),
        has_base_instructions=payload.get("base_instructions") is not None,
        git_repository_url=str(git.get("repository_url") or ""),
        git_branch=str(git.get("branch") or ""),
        git_commit_hash=str(git.get("commit_hash") or ""),
        is_subagent=is_structured_subagent(payload),
    )


def _inherit_parent_project_identity(record: UsageRecord, parent: UsageRecord) -> UsageRecord:
    aliases = _dedupe_aliases([record.project_key, *record.project_aliases, *parent.project_aliases], parent.project_key)
    return replace(
        record,
        project_key=parent.project_key,
        project_label=parent.project_label,
        project_aliases=aliases,
        git_repository_url=parent.git_repository_url,
        git_branch=parent.git_branch,
    )


def _dedupe_aliases(values: list[str], primary_key: str) -> tuple[str, ...]:
    aliases: list[str] = []
    seen = {primary_key}
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        aliases.append(value)
    return tuple(aliases)


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
