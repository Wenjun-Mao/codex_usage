from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal


BackupPhase = Literal["preparing", "compressing", "verifying"]


@dataclass(frozen=True, slots=True)
class BackupProgress:
    phase: BackupPhase
    completed_bytes: int
    total_bytes: int
    file_index: int = 0
    file_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "event": "progress",
            "phase": self.phase,
            "completed_bytes": self.completed_bytes,
            "total_bytes": self.total_bytes,
            "file_index": self.file_index,
            "file_count": self.file_count,
        }


ProgressCallback = Callable[[BackupProgress], None]


def emit_json_progress(progress: BackupProgress) -> None:
    print(json.dumps(progress.to_dict(), separators=(",", ":")), file=sys.stderr)


def ignore_progress(progress: BackupProgress) -> None:
    del progress


class ThrottledProgress:
    def __init__(
        self,
        callback: ProgressCallback,
        *,
        phase: BackupPhase,
        total_bytes: int,
        file_count: int,
        quantum_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        self._callback = callback
        self._phase = phase
        self._total_bytes = total_bytes
        self._file_count = file_count
        self._quantum_bytes = quantum_bytes
        self._completed_bytes = 0
        self._last_reported = -quantum_bytes
        self._file_index = 0

    @property
    def completed_bytes(self) -> int:
        return self._completed_bytes

    def begin_file(self, file_index: int) -> None:
        self._file_index = file_index
        self._emit(force=True)

    def advance(self, byte_count: int) -> None:
        self._completed_bytes += max(0, byte_count)
        self._emit(force=False)

    def finish(self) -> None:
        self._completed_bytes = self._total_bytes
        self._emit(force=True)

    def _emit(self, *, force: bool) -> None:
        if not force and self._completed_bytes - self._last_reported < self._quantum_bytes:
            return
        self._last_reported = self._completed_bytes
        self._callback(
            BackupProgress(
                phase=self._phase,
                completed_bytes=self._completed_bytes,
                total_bytes=self._total_bytes,
                file_index=self._file_index,
                file_count=self._file_count,
            )
        )
