from __future__ import annotations

import re
from dataclasses import dataclass

ROW_CLASSIFIER_BYTES = 4096

_TOP_LEVEL_TYPE = re.compile(
    rb'^\s*\{(?:(?!"payload"\s*:).){0,4096}?"type"\s*:\s*"([^"\\]+)"',
    re.DOTALL,
)
_INLINE_MEDIA_MARKERS = (
    b'"url":"data:image/',
    b'"url": "data:image/',
    b'"image_url":"data:image/',
    b'"image_url": "data:image/',
    b'"data":"data:image/',
    b'"data": "data:image/',
    b'"url":"data:audio/',
    b'"url": "data:audio/',
    b'"audio_url":"data:audio/',
    b'"audio_url": "data:audio/',
    b'"url":"data:video/',
    b'"url": "data:video/',
    b'"video_url":"data:video/',
    b'"video_url": "data:video/',
    b'"url":"data:application/pdf',
    b'"url": "data:application/pdf',
)


@dataclass(frozen=True, slots=True)
class StorageContentMetrics:
    compacted_record_count: int = 0
    compacted_bytes: int = 0
    largest_compacted_record_bytes: int = 0
    media_compacted_record_count: int = 0
    embedded_media_occurrence_count: int = 0
    unclassified_record_count: int = 0

    def __add__(self, other: "StorageContentMetrics") -> "StorageContentMetrics":
        return StorageContentMetrics(
            compacted_record_count=(
                self.compacted_record_count + other.compacted_record_count
            ),
            compacted_bytes=self.compacted_bytes + other.compacted_bytes,
            largest_compacted_record_bytes=max(
                self.largest_compacted_record_bytes,
                other.largest_compacted_record_bytes,
            ),
            media_compacted_record_count=(
                self.media_compacted_record_count
                + other.media_compacted_record_count
            ),
            embedded_media_occurrence_count=(
                self.embedded_media_occurrence_count
                + other.embedded_media_occurrence_count
            ),
            unclassified_record_count=(
                self.unclassified_record_count + other.unclassified_record_count
            ),
        )

    @property
    def complete(self) -> bool:
        return self.unclassified_record_count == 0


@dataclass(frozen=True, slots=True)
class StorageRowObservation:
    top_level_type: str
    metrics: StorageContentMetrics

    @property
    def is_compacted(self) -> bool:
        return self.top_level_type == "compacted"


def observe_storage_row(raw_line: bytes) -> StorageRowObservation:
    """Classify one accepted JSONL row without decoding or retaining its payload."""
    match = _TOP_LEVEL_TYPE.search(raw_line[:ROW_CLASSIFIER_BYTES])
    if match is None:
        return StorageRowObservation(
            top_level_type="",
            metrics=StorageContentMetrics(unclassified_record_count=1),
        )
    event_type = match.group(1).decode("ascii")
    if event_type != "compacted":
        return StorageRowObservation(event_type, StorageContentMetrics())

    media_occurrences = sum(raw_line.count(marker) for marker in _INLINE_MEDIA_MARKERS)
    return StorageRowObservation(
        top_level_type=event_type,
        metrics=StorageContentMetrics(
            compacted_record_count=1,
            compacted_bytes=len(raw_line),
            largest_compacted_record_bytes=len(raw_line),
            media_compacted_record_count=int(media_occurrences > 0),
            embedded_media_occurrence_count=media_occurrences,
        ),
    )
