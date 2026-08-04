from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from codex_usage.parser import (
    _PartialSessionGenerationReadError,
    parse_session_generation,
)
from codex_usage.session_generation_models import RawRepoPathCandidate


class PartialTransitionReadError(OSError):
    candidates: tuple[RawRepoPathCandidate, ...]
    cause: OSError | UnicodeDecodeError

    def __init__(
        self,
        candidates: tuple[RawRepoPathCandidate, ...],
        cause: OSError | UnicodeDecodeError,
    ) -> None:
        super().__init__(str(cause))
        self.candidates = candidates
        self.cause = cause


@retry(
    retry=retry_if_exception_type(PartialTransitionReadError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.2),
    reraise=True,
)
def collect_jsonl_repo_path_candidates(path: Path) -> list[RawRepoPathCandidate]:
    return read_jsonl_repo_path_candidates_once(path)


def read_jsonl_repo_path_candidates_once(path: Path) -> list[RawRepoPathCandidate]:
    try:
        return list(
            parse_session_generation(
                path,
                _capture_partial_candidates=True,
            ).candidates
        )
    except _PartialSessionGenerationReadError as error:
        raise PartialTransitionReadError(error.candidates, error.cause) from error


def _parse_json_line(raw_line: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw_line)
    except (ValueError, RecursionError):
        return None
    return parsed if isinstance(parsed, dict) else None
