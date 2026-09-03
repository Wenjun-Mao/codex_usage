from __future__ import annotations

from typing import BinaryIO

from codex_usage.session_row_relevance import (
    RELEVANT_PREFIX_BYTES,
    SESSION_READ_BUFFER_BYTES,
    RowRelevance,
    classify_row_prefix,
)


def read_candidate_row(
    handle: BinaryIO,
    stop_offset: int,
) -> tuple[bytes, bool, int, RowRelevance]:
    """Read relevant rows exactly and stream-drain known irrelevant payloads."""
    row_start = handle.tell()
    remaining = stop_offset - row_start
    if remaining <= 0:
        return b"", False, 0, "unclassified"
    prefix = handle.readline(min(RELEVANT_PREFIX_BYTES, remaining))
    if not prefix:
        return b"", False, 0, "unclassified"
    complete = prefix.endswith(b"\n")
    relevance = classify_row_prefix(prefix, complete=complete)
    if complete or handle.tell() >= stop_offset:
        return prefix, complete, len(prefix), relevance
    if relevance == "irrelevant":
        return _drain_irrelevant_row(handle, stop_offset, prefix, relevance)
    return _read_relevant_row(handle, stop_offset, prefix, relevance)


def _drain_irrelevant_row(
    handle: BinaryIO,
    stop_offset: int,
    prefix: bytes,
    relevance: RowRelevance,
) -> tuple[bytes, bool, int, RowRelevance]:
    bytes_read = len(prefix)
    while handle.tell() < stop_offset:
        chunk = handle.readline(
            min(SESSION_READ_BUFFER_BYTES, stop_offset - handle.tell())
        )
        if not chunk:
            break
        bytes_read += len(chunk)
        if chunk.endswith(b"\n"):
            return prefix, True, bytes_read, relevance
    return prefix, False, bytes_read, relevance


def _read_relevant_row(
    handle: BinaryIO,
    stop_offset: int,
    prefix: bytes,
    relevance: RowRelevance,
) -> tuple[bytes, bool, int, RowRelevance]:
    parts = [prefix]
    total = len(prefix)
    while handle.tell() < stop_offset:
        chunk = handle.readline(
            min(SESSION_READ_BUFFER_BYTES, stop_offset - handle.tell())
        )
        if not chunk:
            break
        parts.append(chunk)
        total += len(chunk)
        if chunk.endswith(b"\n"):
            return b"".join(parts), True, total, relevance
    return b"".join(parts), False, total, relevance
