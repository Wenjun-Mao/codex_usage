"""Checkpoint integrity checks shared by full and append session parsing."""

from __future__ import annotations

import hashlib
from typing import Any

from codex_usage.session_generation_models import RawRepoPathCandidate
from codex_usage.session_parser_models import SessionParseCheckpoint
from codex_usage.session_row_relevance import CHECKPOINT_DIGEST_BYTES


class AppendCheckpointMismatch(ValueError):
    pass


class PartialSessionGenerationReadError(OSError):
    def __init__(
        self,
        candidates: tuple[RawRepoPathCandidate, ...],
        cause: OSError | UnicodeDecodeError,
    ) -> None:
        super().__init__(str(cause))
        self.candidates = candidates
        self.cause = cause


def validate_append_checkpoint(
    handle: Any,
    checkpoint: SessionParseCheckpoint,
    *,
    source_device: int,
    source_inode: int,
    stop_offset: int,
) -> int:
    if not source_device or not source_inode:
        raise AppendCheckpointMismatch("source file identity is unavailable")
    if source_device != checkpoint.source_device or source_inode != checkpoint.source_inode:
        raise AppendCheckpointMismatch("source file identity changed")
    if stop_offset < checkpoint.byte_offset:
        raise AppendCheckpointMismatch("source file was truncated")
    expected_session_id = (
        checkpoint.state.root_metadata or checkpoint.state.metadata
    ).session_id
    if not checkpoint.session_id or checkpoint.session_id != expected_session_id:
        raise AppendCheckpointMismatch("checkpoint task identity is inconsistent")
    head_sha256, head_bytes = digest_range(
        handle, 0, min(CHECKPOINT_DIGEST_BYTES, checkpoint.byte_offset)
    )
    boundary_start = max(0, checkpoint.byte_offset - CHECKPOINT_DIGEST_BYTES)
    boundary_sha256, boundary_bytes = digest_range(
        handle, boundary_start, checkpoint.byte_offset
    )
    if head_sha256 != checkpoint.head_sha256:
        raise AppendCheckpointMismatch("source file header changed")
    if boundary_sha256 != checkpoint.boundary_sha256:
        raise AppendCheckpointMismatch("source file checkpoint boundary changed")
    return head_bytes + boundary_bytes


def digest_range(handle: Any, start: int, end: int) -> tuple[str, int]:
    handle.seek(start)
    remaining = max(0, end - start)
    digest = hashlib.sha256()
    total = 0
    while remaining:
        chunk = handle.read(min(64 * 1024, remaining))
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
        remaining -= len(chunk)
    if remaining:
        raise OSError("session file ended before checkpoint digest range")
    return digest.hexdigest(), total
