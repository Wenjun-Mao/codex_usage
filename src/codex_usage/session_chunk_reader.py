from __future__ import annotations

from typing import BinaryIO
from dataclasses import dataclass, field
from codex_usage.speed_projection import StructuralProjection

from codex_usage.session_row_relevance import (
    RELEVANT_PREFIX_BYTES,
    SESSION_READ_BUFFER_BYTES,
    RowRelevance,
    classify_row_prefix,
)


class RecoveryRowBudgetExceeded(OSError):
    def __init__(self, bytes_read):
        super().__init__("row exceeds bounded recovery budget")
        self.bytes_read = bytes_read


@dataclass(frozen=True)
class CandidateRow:
    raw: bytes
    complete: bool
    bytes_read: int
    relevance: RowRelevance
    drain_state: dict = field(default_factory=dict)
    projection: tuple[dict, bool] | None = None


def read_candidate_row(
    handle: BinaryIO,
    stop_offset: int,
    *, max_row_bytes: int | None = None,
    drain_state: dict | None = None,
) -> CandidateRow:
    """Read relevant rows exactly and stream-drain known irrelevant payloads."""
    row_start = handle.tell()
    remaining = stop_offset - row_start
    if drain_state:
        projection = StructuralProjection(drain_state["projection"])
        return _drain_irrelevant_row(handle, stop_offset, b"", drain_state["relevance"],
                                     max_row_bytes, projection)
    if remaining <= 0:
        return CandidateRow(b"", False, 0, "unclassified")
    prefix = handle.readline(min(RELEVANT_PREFIX_BYTES, remaining, max_row_bytes if max_row_bytes is not None else remaining))
    if not prefix:
        return CandidateRow(b"", False, 0, "unclassified")
    complete = prefix.endswith(b"\n")
    relevance = classify_row_prefix(prefix, complete=complete)
    if complete or handle.tell() >= stop_offset:
        return CandidateRow(prefix, complete, len(prefix), relevance)
    if relevance in {"bounded", "irrelevant"}:
        projection = StructuralProjection()
        projection.feed(prefix)
        return _drain_irrelevant_row(handle, stop_offset, prefix, relevance, max_row_bytes, projection)
    return _read_relevant_row(handle, stop_offset, prefix, relevance, max_row_bytes)


def _drain_irrelevant_row(
    handle: BinaryIO,
    stop_offset: int,
    prefix: bytes,
    relevance: RowRelevance,
    max_row_bytes: int | None,
    projection: StructuralProjection,
) -> CandidateRow:
    bytes_read = len(prefix)
    while handle.tell() < stop_offset:
        if max_row_bytes is not None and bytes_read >= max_row_bytes:
            break
        chunk = handle.readline(
            min(SESSION_READ_BUFFER_BYTES, stop_offset - handle.tell(),
                max_row_bytes - bytes_read if max_row_bytes is not None else SESSION_READ_BUFFER_BYTES)
        )
        if not chunk:
            break
        bytes_read += len(chunk)
        projection.feed(chunk)
        if chunk.endswith(b"\n"):
            # The source row is complete, but the returned prefix is not.  The
            # parser must not try to JSON-decode a prefix that deliberately
            # omitted a large payload.
            return CandidateRow(prefix, True, bytes_read, relevance, projection=projection.result())
    return CandidateRow(prefix, False, bytes_read, relevance,
                        {"relevance": relevance, "projection": projection.state})


def _read_relevant_row(
    handle: BinaryIO,
    stop_offset: int,
    prefix: bytes,
    relevance: RowRelevance,
    max_row_bytes: int | None,
) -> CandidateRow:
    parts = [prefix]
    total = len(prefix)
    while handle.tell() < stop_offset:
        chunk = handle.readline(
            min(SESSION_READ_BUFFER_BYTES, stop_offset - handle.tell(),
                max_row_bytes - total + 1 if max_row_bytes is not None else SESSION_READ_BUFFER_BYTES)
        )
        if not chunk:
            break
        parts.append(chunk)
        total += len(chunk)
        if max_row_bytes is not None and total > max_row_bytes:
            raise RecoveryRowBudgetExceeded(total)
        if chunk.endswith(b"\n"):
            return CandidateRow(b"".join(parts), True, total, relevance)
    return CandidateRow(b"".join(parts), False, total, relevance)
