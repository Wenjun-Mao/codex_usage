from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import codex_usage.project_transition_evidence as evidence_module
from codex_usage.parser import parse_timestamp


@dataclass(frozen=True, slots=True)
class RawRepoPathCandidate:
    raw_path: str
    timestamp: datetime
    thread_id: str
    source: str


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
    candidates: list[RawRepoPathCandidate] = []
    current_thread_id = path.stem
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                obj = _parse_json_line(raw_line)
                if obj is None:
                    continue

                payload = (
                    obj.get("payload")
                    if isinstance(obj.get("payload"), dict)
                    else {}
                )
                event_type = obj.get("type")
                if event_type == "session_meta":
                    current_thread_id = (
                        _thread_id_from_payload(payload) or current_thread_id
                    )

                timestamp = parse_timestamp(obj.get("timestamp"))
                if timestamp is None:
                    continue

                for source, text, preserve_exact_field in _jsonl_candidate_texts(
                    event_type, payload
                ):
                    for raw_path in evidence_module.extract_repo_paths(
                        text,
                        preserve_exact_field=preserve_exact_field,
                    ):
                        candidates.append(
                            RawRepoPathCandidate(
                                raw_path=raw_path,
                                timestamp=timestamp,
                                thread_id=current_thread_id,
                                source=source,
                            )
                        )
    except (OSError, UnicodeDecodeError) as error:
        raise PartialTransitionReadError(tuple(candidates), error) from error
    return candidates


def _parse_json_line(raw_line: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw_line)
    except (ValueError, RecursionError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _thread_id_from_payload(payload: dict[str, Any]) -> str:
    return str(payload.get("id") or "")


def _jsonl_candidate_texts(
    event_type: object,
    payload: dict[str, Any],
) -> list[tuple[str, str, bool]]:
    """Return only execution context that can act as project-switch evidence."""
    source_event = str(event_type) if event_type else "event"
    payload_type = str(payload.get("type") or "")
    if source_event != "response_item":
        return []
    if payload_type == "function_call":
        workdir = _function_call_workdir(payload.get("arguments"))
        return [
            ("jsonl:response_item:function_call_workdir", workdir, True)
        ] if workdir else []
    return []


def _function_call_workdir(arguments: object) -> str:
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except ValueError:
            return ""
    else:
        parsed = arguments
    if not isinstance(parsed, dict):
        return ""
    workdir = parsed.get("workdir")
    return workdir if isinstance(workdir, str) else ""
