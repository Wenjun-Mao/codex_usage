"""Bounded fingerprint evidence for copies of one immutable physical rollout."""
from dataclasses import dataclass
import os

from codex_usage.session_parser_safety import CapturedPrefix, digest_range
from codex_usage.session_row_relevance import CHECKPOINT_DIGEST_BYTES


class ReplicaEvidenceError(ValueError):
    pass


@dataclass(slots=True)
class ReplicaReadBudget:
    remaining: int
    bytes_read: int = 0

    def reserve(self, size):
        if size > self.remaining:
            raise ReplicaEvidenceError("paginated_history_replica_read_budget")
        self.remaining -= size


class _MeasuredReader:
    def __init__(self, handle, budget):
        self.handle, self.budget = handle, budget

    def seek(self, offset):
        return self.handle.seek(offset)

    def read(self, size):
        value = self.handle.read(size)
        self.budget.bytes_read += len(value)
        return value


def prefix_width(offset):
    return 2 * min(CHECKPOINT_DIGEST_BYTES, offset)


def capture_prefix(entry, budget):
    budget.reserve(prefix_width(entry.size_bytes))
    try:
        with entry.path.open("rb", buffering=0) as handle:
            before = os.fstat(handle.fileno())
            _check_inventory(entry, before)
            reader = _MeasuredReader(handle, budget)
            head, _ = digest_range(reader, 0, min(CHECKPOINT_DIGEST_BYTES, entry.size_bytes))
            tail, _ = digest_range(reader, max(0, entry.size_bytes-CHECKPOINT_DIGEST_BYTES), entry.size_bytes)
            _check_stable(entry, before, os.fstat(handle.fileno()))
            return CapturedPrefix(entry.size_bytes, head, tail)
    except OSError as error:
        raise ReplicaEvidenceError("paginated_history_replica_source_unavailable") from error


def prove_prefixes(entry, prefixes, budget):
    prefixes = tuple(dict.fromkeys(prefixes))
    if any(prefix.byte_offset > entry.size_bytes for prefix in prefixes):
        raise ReplicaEvidenceError("paginated_history_replica_shorter_than_retained_prefix")
    budget.reserve(sum(prefix_width(p.byte_offset) for p in prefixes))
    try:
        with entry.path.open("rb", buffering=0) as handle:
            before = os.fstat(handle.fileno())
            _check_inventory(entry, before)
            reader = _MeasuredReader(handle, budget)
            for prefix in prefixes:
                head, _ = digest_range(reader, 0, min(CHECKPOINT_DIGEST_BYTES, prefix.byte_offset))
                tail, _ = digest_range(reader, max(0, prefix.byte_offset-CHECKPOINT_DIGEST_BYTES), prefix.byte_offset)
                if head != prefix.head_sha256 or tail != prefix.boundary_sha256:
                    raise ReplicaEvidenceError("paginated_history_replica_prefix_conflict")
            _check_stable(entry, before, os.fstat(handle.fileno()))
    except OSError as error:
        raise ReplicaEvidenceError("paginated_history_replica_source_unavailable") from error


def _check_inventory(entry, stat):
    if (not entry.source_device or not entry.source_inode or
            (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) !=
            (entry.source_device, entry.source_inode, entry.size_bytes, entry.mtime_ns)):
        raise ReplicaEvidenceError("paginated_history_replica_source_changed")


def _check_stable(entry, before, after):
    def version(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    if version(before) != version(after) or version(after) != version(entry.path.stat()):
        raise ReplicaEvidenceError("paginated_history_replica_source_changed")
