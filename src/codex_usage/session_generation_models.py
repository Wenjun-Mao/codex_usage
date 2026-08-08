from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from codex_usage.models import SessionMetadata, UsageRecord
from codex_usage.session_parser_models import SessionParseCheckpoint
from codex_usage.storage_content import StorageContentMetrics


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
    checkpoint: SessionParseCheckpoint
    bytes_read: int
    content_metrics: StorageContentMetrics = StorageContentMetrics()


@dataclass(frozen=True, slots=True)
class ParsedSessionAppend:
    records: tuple[UsageRecord, ...]
    metadata: SessionMetadata
    candidates: tuple[RawRepoPathCandidate, ...]
    checkpoint: SessionParseCheckpoint
    bytes_read: int
    content_metrics: StorageContentMetrics = StorageContentMetrics()
    start_offset: int = 0
