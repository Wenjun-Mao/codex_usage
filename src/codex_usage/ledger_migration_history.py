from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal


HistoryRelation = Literal["identical", "extends", "prefix", "conflict"]

_USAGE_COLUMNS = (
    "record_index",
    "timestamp",
    "timestamp_us",
    "session_id",
    "turn_id",
    "model",
    "effort",
    "collaboration_mode",
    "project_key",
    "project_label",
    "project_aliases_json",
    "cwd",
    "git_repository_url",
    "git_branch",
    "parent_thread_id",
    "usage_role",
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)

_METADATA_COLUMNS = (
    "session_id",
    "cwd",
    "project_key",
    "project_label",
    "project_aliases_json",
    "git_repository_url",
    "git_branch",
    "memory_mode",
    "has_base_instructions",
)

_CANDIDATE_COLUMNS = (
    "candidate_index",
    "timestamp",
    "timestamp_us",
    "thread_id",
    "raw_path",
    "source",
)


@dataclass(frozen=True, slots=True)
class GenerationHistory:
    usage: tuple[tuple[object, ...], ...]
    metadata: tuple[object, ...] | None
    transition_candidates: tuple[tuple[object, ...], ...]
    parsed_offset: int | None

    @property
    def empty(self) -> bool:
        return not self.usage and self.metadata is None and not self.transition_candidates


def load_generation_history(
    connection: sqlite3.Connection,
    file_key: str,
) -> GenerationHistory:
    usage = _ordered_rows(
        connection,
        "usage_records",
        _USAGE_COLUMNS,
        file_key,
        "record_index",
    )
    metadata_row = connection.execute(
        f"select {', '.join(_METADATA_COLUMNS)} from session_metadata "
        "where file_key = ?",
        (file_key,),
    ).fetchone()
    candidates = _ordered_rows(
        connection,
        "transition_candidates",
        _CANDIDATE_COLUMNS,
        file_key,
        "candidate_index",
    )
    checkpoint = connection.execute(
        "select byte_offset from parser_checkpoints where file_key = ?",
        (file_key,),
    ).fetchone()
    return GenerationHistory(
        usage=usage,
        metadata=(
            tuple(metadata_row[column] for column in _METADATA_COLUMNS)
            if metadata_row is not None
            else None
        ),
        transition_candidates=candidates,
        parsed_offset=int(checkpoint["byte_offset"]) if checkpoint is not None else None,
    )


def compare_generation_history(
    existing: GenerationHistory,
    incoming: GenerationHistory,
) -> HistoryRelation:
    if _same_semantics(existing, incoming):
        if _offset_precedes(existing.parsed_offset, incoming.parsed_offset):
            return "extends"
        if _offset_precedes(incoming.parsed_offset, existing.parsed_offset):
            return "prefix"
        return "identical"
    if existing.empty:
        return "extends"
    if incoming.empty:
        return "prefix"
    if existing.metadata != incoming.metadata:
        return "conflict"
    if _is_prefix(existing.usage, incoming.usage) and _is_prefix(
        existing.transition_candidates,
        incoming.transition_candidates,
    ):
        return "extends"
    if _is_prefix(incoming.usage, existing.usage) and _is_prefix(
        incoming.transition_candidates,
        existing.transition_candidates,
    ):
        return "prefix"
    return "conflict"


def _same_semantics(left: GenerationHistory, right: GenerationHistory) -> bool:
    return (
        left.usage == right.usage
        and left.metadata == right.metadata
        and left.transition_candidates == right.transition_candidates
    )


def _offset_precedes(left: int | None, right: int | None) -> bool:
    return left is not None and right is not None and left < right


def _ordered_rows(
    connection: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    file_key: str,
    order_column: str,
) -> tuple[tuple[object, ...], ...]:
    rows = connection.execute(
        f"select {', '.join(columns)} from {table} "
        f"where file_key = ? order by {order_column}",
        (file_key,),
    )
    return tuple(tuple(row[column] for column in columns) for row in rows)


def _is_prefix(
    prefix: tuple[tuple[object, ...], ...],
    complete: tuple[tuple[object, ...], ...],
) -> bool:
    return len(prefix) <= len(complete) and complete[: len(prefix)] == prefix
