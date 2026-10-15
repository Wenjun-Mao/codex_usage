"""Typed slice outcomes keep I/O activity separate from committed progress."""
from dataclasses import dataclass
from enum import StrEnum
import json


class RebuildOutcome(StrEnum):
    COMPLETE = "complete"
    PROGRESS = "progress"
    BLOCKED = "blocked"
    FAILED = "failed"


class RebuildReason(StrEnum):
    NONE = "none"
    NO_PROGRESS = "no-progress"


@dataclass(frozen=True, slots=True)
class RebuildSliceResult:
    source_key: str
    outcome: RebuildOutcome
    captured_bytes: int
    target_bytes: int
    bytes_read: int
    reason: RebuildReason = RebuildReason.NONE

    def __post_init__(self):
        if not isinstance(self.outcome, RebuildOutcome) or not isinstance(self.reason, RebuildReason):
            raise ValueError("rebuild outcomes and reasons must be typed")
        if any(type(value) is not int or value < 0 for value in (self.captured_bytes, self.target_bytes, self.bytes_read)):
            raise ValueError("rebuild byte counters must be nonnegative integers")
        if self.complete and self.captured_bytes != self.target_bytes:
            raise ValueError("complete rebuild must cover its target")
        if (self.outcome == RebuildOutcome.BLOCKED) != (self.reason == RebuildReason.NO_PROGRESS):
            raise ValueError("blocked rebuild must disclose no progress")

    @property
    def complete(self):
        return self.outcome == RebuildOutcome.COMPLETE


def checkpoint_progress(checkpoint):
    if checkpoint is None:
        return 0, 0, 0, "{}"
    return (checkpoint.byte_offset, checkpoint.next_record_index, checkpoint.next_candidate_index,
            json.dumps(checkpoint.state.row_drain, sort_keys=True))


def checkpoint_advanced(before, after):
    return all(new >= old for old, new in zip(before[:3], after[:3])) and after != before
