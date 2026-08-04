from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from codex_usage.models import SessionMetadata, UsageRecord


@dataclass(frozen=True, slots=True)
class RawRepoPathCandidate:
    raw_path: str
    timestamp: datetime
    thread_id: str
    source: str


@dataclass(frozen=True, slots=True)
class ParsedSessionGeneration:
    records: tuple[UsageRecord, ...]
    metadata: SessionMetadata
    candidates: tuple[RawRepoPathCandidate, ...]
