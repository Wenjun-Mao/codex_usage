from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from codex_usage.models import SessionMetadata, TokenUsage


@dataclass(frozen=True, slots=True)
class SessionParserState:
    metadata: SessionMetadata
    root_metadata: SessionMetadata | None
    previous_usage: TokenUsage | None
    root_session_id: str
    root_session_is_fork: bool
    counted_root_fork_usage: bool
    current_model: str
    current_turn_id: str
    current_effort: str
    current_mode: str


@dataclass(frozen=True, slots=True)
class SessionParseCheckpoint:
    byte_offset: int
    next_record_index: int
    next_candidate_index: int
    source_device: int
    source_inode: int
    head_sha256: str
    boundary_sha256: str
    session_id: str
    state: SessionParserState


def parser_state_to_json(state: SessionParserState) -> str:
    return json.dumps(
        {
            "metadata": _metadata_to_dict(state.metadata),
            "root_metadata": (
                None
                if state.root_metadata is None
                else _metadata_to_dict(state.root_metadata)
            ),
            "previous_usage": (
                None
                if state.previous_usage is None
                else _token_usage_to_dict(state.previous_usage)
            ),
            "root_session_id": state.root_session_id,
            "root_session_is_fork": state.root_session_is_fork,
            "counted_root_fork_usage": state.counted_root_fork_usage,
            "current_model": state.current_model,
            "current_turn_id": state.current_turn_id,
            "current_effort": state.current_effort,
            "current_mode": state.current_mode,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def parser_state_from_json(value: str, path: Path) -> SessionParserState:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("parser checkpoint state must be an object")
    root_value = parsed.get("root_metadata")
    usage_value = parsed.get("previous_usage")
    return SessionParserState(
        metadata=_metadata_from_dict(_mapping(parsed.get("metadata")), path),
        root_metadata=(
            None
            if root_value is None
            else _metadata_from_dict(_mapping(root_value), path)
        ),
        previous_usage=(
            None
            if usage_value is None
            else TokenUsage.from_mapping(_mapping(usage_value))
        ),
        root_session_id=_text(parsed.get("root_session_id")),
        root_session_is_fork=bool(parsed.get("root_session_is_fork")),
        counted_root_fork_usage=bool(parsed.get("counted_root_fork_usage")),
        current_model=_text(parsed.get("current_model")),
        current_turn_id=_text(parsed.get("current_turn_id")),
        current_effort=_text(parsed.get("current_effort")),
        current_mode=_text(parsed.get("current_mode")),
    )


def _metadata_to_dict(metadata: SessionMetadata) -> dict[str, object]:
    return {
        "session_id": metadata.session_id,
        "timestamp": metadata.timestamp.isoformat() if metadata.timestamp else None,
        "cwd": metadata.cwd,
        "originator": metadata.originator,
        "source": metadata.source,
        "cli_version": metadata.cli_version,
        "model_provider": metadata.model_provider,
        "forked_from_id": metadata.forked_from_id,
        "parent_thread_id": metadata.parent_thread_id,
        "memory_mode": metadata.memory_mode,
        "has_base_instructions": metadata.has_base_instructions,
        "git_repository_url": metadata.git_repository_url,
        "git_branch": metadata.git_branch,
        "git_commit_hash": metadata.git_commit_hash,
        "is_subagent": metadata.is_subagent,
    }


def _metadata_from_dict(value: dict[str, Any], path: Path) -> SessionMetadata:
    timestamp_value = value.get("timestamp")
    timestamp = (
        datetime.fromisoformat(timestamp_value)
        if isinstance(timestamp_value, str) and timestamp_value
        else None
    )
    return SessionMetadata(
        session_id=_text(value.get("session_id")) or path.stem,
        file_path=path,
        timestamp=timestamp,
        cwd=_text(value.get("cwd")),
        originator=_text(value.get("originator")),
        source=_text(value.get("source")),
        cli_version=_text(value.get("cli_version")),
        model_provider=_text(value.get("model_provider")),
        forked_from_id=_text(value.get("forked_from_id")),
        parent_thread_id=_text(value.get("parent_thread_id")),
        memory_mode=_text(value.get("memory_mode")),
        has_base_instructions=bool(value.get("has_base_instructions")),
        git_repository_url=_text(value.get("git_repository_url")),
        git_branch=_text(value.get("git_branch")),
        git_commit_hash=_text(value.get("git_commit_hash")),
        is_subagent=bool(value.get("is_subagent")),
    )


def _token_usage_to_dict(usage: TokenUsage) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
        "cache_write_input_tokens": usage.cache_write_input_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_output_tokens": usage.reasoning_output_tokens,
        "total_tokens": usage.total_tokens,
    }


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("parser checkpoint field must be an object")
    return value


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""
