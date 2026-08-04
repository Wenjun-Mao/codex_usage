from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from codex_usage.models import UsageRecord
from codex_usage.parallel.execution import WorkerSpan
from codex_usage.parser import parse_session_generation
from codex_usage.session_generation_models import ParsedSessionGeneration


@dataclass(frozen=True, slots=True)
class UsageParseRequest:
    ordinal: int
    file_key: str
    path: Path
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class UsageParseResult:
    request: UsageParseRequest
    generation: ParsedSessionGeneration | None
    error: str
    span: WorkerSpan

    def __post_init__(self) -> None:
        if self.generation is not None and self.error:
            raise ValueError("usage parse result cannot contain a generation and an error")

    @property
    def records(self) -> tuple[UsageRecord, ...]:
        return self.generation.records if self.generation is not None else ()


def parse_usage_request(request: UsageParseRequest) -> UsageParseResult:
    started_ns = time.monotonic_ns()
    pid = os.getpid()
    try:
        generation = _parse_session_generation_with_retry(request.path)
        error = ""
    # A malformed session must not abort sibling files in the worker batch.
    except Exception as exc:  # noqa: BLE001
        generation = None
        error = f"{type(exc).__name__}: {exc}"
    return UsageParseResult(
        request=request,
        generation=generation,
        error=error,
        span=WorkerSpan(
            pid=pid,
            started_ns=started_ns,
            finished_ns=time.monotonic_ns(),
        ),
    )


@retry(
    retry=retry_if_exception_type(OSError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.2),
    reraise=True,
)
def _parse_session_generation_with_retry(path: Path) -> ParsedSessionGeneration:
    return parse_session_generation(path)
