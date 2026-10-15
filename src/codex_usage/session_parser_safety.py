"""Checkpoint integrity checks shared by full and append session parsing."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
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
        bytes_read: int = 0,
    ) -> None:
        super().__init__(str(cause))
        self.candidates = candidates
        self.cause = cause
        self.bytes_read = bytes_read


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
    if source_inode != checkpoint.source_inode:
        raise AppendCheckpointMismatch("source file inode changed")
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


def matches_captured_prefix(path: Path, *, source_device: int, source_inode: int,
                            byte_offset: int, head_sha256: str, boundary_sha256: str) -> bool:
    """Match the established bounded checkpoint guards, not only a header."""
    return matches_captured_prefixes(path, source_device=source_device, source_inode=source_inode,
        prefixes=(CapturedPrefix(byte_offset, head_sha256, boundary_sha256),))


@dataclass(frozen=True, slots=True)
class CapturedPrefix:
    byte_offset: int
    head_sha256: str
    boundary_sha256: str


def matches_captured_prefixes(path: Path, *, source_device: int, source_inode: int,
                             prefixes: tuple[CapturedPrefix, ...]) -> bool:
    """All retained checkpoints must match one stable source snapshot."""
    if not source_device or not source_inode or not prefixes or any(p.byte_offset < 0 for p in prefixes):
        return False
    try:
        with path.open("rb", buffering=0) as handle:
            before = os.fstat(handle.fileno())
            if (before.st_size < max(p.byte_offset for p in prefixes)
                    or before.st_dev != source_device or before.st_ino != source_inode):
                return False
            for prefix in dict.fromkeys(prefixes):
                head, _ = digest_range(handle, 0, min(CHECKPOINT_DIGEST_BYTES, prefix.byte_offset))
                boundary, _ = digest_range(handle, max(0, prefix.byte_offset-CHECKPOINT_DIGEST_BYTES), prefix.byte_offset)
                if head != prefix.head_sha256 or boundary != prefix.boundary_sha256:
                    return False
            if _version(before) != _version(os.fstat(handle.fileno())) or _version(before) != _version(path.stat()):
                return False
            return True
    except OSError:
        return False


def _version(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
