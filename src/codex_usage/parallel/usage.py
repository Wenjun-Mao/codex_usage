from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from codex_usage.models import UsageRecord
from codex_usage.parallel.execution import WorkerSpan
from codex_usage.parser import (
    AppendCheckpointMismatch,
    parse_session_append,
    parse_session_generation,
)
from codex_usage.session_generation_models import (
    ParsedSessionAppend,
    ParsedSessionGeneration,
)
from codex_usage.session_parser_models import SessionParseCheckpoint

type ParseOutcome = Literal["full", "append", "full_fallback"]


@dataclass(frozen=True, slots=True)
class UsageParseRequest:
    ordinal: int
    file_key: str
    path: Path
    size_bytes: int
    mtime_ns: int
    checkpoint: SessionParseCheckpoint | None = None

    @property
    def estimated_bytes(self) -> int:
        if self.checkpoint is None:
            return self.size_bytes
        return max(0, self.size_bytes - self.checkpoint.byte_offset)


@dataclass(frozen=True, slots=True)
class UsageParseResult:
    request: UsageParseRequest
    generation: ParsedSessionGeneration | None
    appended: ParsedSessionAppend | None
    error: str
    span: WorkerSpan
    outcome: ParseOutcome = "full"
    fallback_reason: str = ""
    bytes_read: int = 0

    def __post_init__(self) -> None:
        successful_values = int(self.generation is not None) + int(
            self.appended is not None
        )
        if self.error and successful_values:
            raise ValueError("usage parse result cannot contain parsed data and an error")
        if not self.error and successful_values != 1:
            raise ValueError("successful usage parse result needs exactly one parsed value")

    @property
    def records(self) -> tuple[UsageRecord, ...]:
        if self.generation is not None:
            return self.generation.records
        return self.appended.records if self.appended is not None else ()

    @property
    def metadata(self):
        if self.generation is not None:
            return self.generation.metadata
        if self.appended is not None:
            return self.appended.metadata
        raise ValueError("successful usage parse result lacks parsed data")


def parse_usage_request(request: UsageParseRequest) -> UsageParseResult:
    started_ns = time.monotonic_ns()
    pid = os.getpid()
    try:
        generation, appended, outcome, fallback_reason = (
            _parse_usage_request_with_retry(request)
        )
        error = ""
    # A malformed session must not abort sibling files in the worker batch.
    except Exception as exc:  # noqa: BLE001
        generation = None
        appended = None
        outcome = "full"
        fallback_reason = ""
        error = f"{type(exc).__name__}: {exc}"
    bytes_read = (
        generation.bytes_read
        if generation is not None
        else appended.bytes_read if appended is not None else 0
    )
    return UsageParseResult(
        request=request,
        generation=generation,
        appended=appended,
        error=error,
        span=WorkerSpan(
            pid=pid,
            started_ns=started_ns,
            finished_ns=time.monotonic_ns(),
        ),
        outcome=outcome,
        fallback_reason=fallback_reason,
        bytes_read=bytes_read,
    )


@retry(
    retry=retry_if_exception_type(OSError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.2),
    reraise=True,
)
def _parse_usage_request_with_retry(
    request: UsageParseRequest,
) -> tuple[
    ParsedSessionGeneration | None,
    ParsedSessionAppend | None,
    ParseOutcome,
    str,
]:
    if request.checkpoint is not None:
        try:
            appended = parse_session_append(
                request.path,
                request.checkpoint,
                stop_offset=request.size_bytes,
            )
        except AppendCheckpointMismatch as error:
            generation = parse_session_generation(
                request.path,
                stop_offset=request.size_bytes,
            )
            return generation, None, "full_fallback", str(error)
        return None, appended, "append", ""
    generation = parse_session_generation(
        request.path,
        stop_offset=request.size_bytes,
    )
    return generation, None, "full", ""
