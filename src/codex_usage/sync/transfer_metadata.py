from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from codex_usage.models import SessionMetadata
from codex_usage.parser import parse_timestamp
from codex_usage.session_provenance import (
    is_structured_subagent,
    parent_thread_id_from_source,
)
from codex_usage.sync.identity import is_canonical_thread_id
from codex_usage.sync.io import _is_transient_filesystem_error

# Real session_meta records are normally the first JSONL row. One MiB leaves room for
# unusually large base instructions while keeping browse work independent of history size.
TRANSFER_METADATA_HEADER_MAX_BYTES = 1024 * 1024


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def read_transfer_metadata(path: Path) -> SessionMetadata | None:
    try:
        with path.open("rb", buffering=0) as handle:
            header = handle.read(TRANSFER_METADATA_HEADER_MAX_BYTES)
    except OSError as error:
        if _is_transient_filesystem_error(error):
            raise
        return None
    return parse_transfer_metadata_bytes(path, header)


def parse_transfer_metadata_bytes(
    path: Path,
    contents: bytes,
) -> SessionMetadata | None:
    header = contents[:TRANSFER_METADATA_HEADER_MAX_BYTES]
    for raw_line in header.splitlines():
        try:
            value = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(value, dict) or value.get("type") != "session_meta":
            continue
        payload = value.get("payload")
        if not isinstance(payload, dict):
            return None
        thread_id = payload.get("id")
        if not is_canonical_thread_id(thread_id):
            return None
        return _metadata_from_payload(path, value, payload, thread_id)
    return None


def _metadata_from_payload(
    path: Path,
    value: dict[str, Any],
    payload: dict[str, Any],
    thread_id: str,
) -> SessionMetadata:
    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    return SessionMetadata(
        session_id=thread_id,
        file_path=path,
        timestamp=parse_timestamp(payload.get("timestamp"))
        or parse_timestamp(value.get("timestamp")),
        cwd=str(payload.get("cwd") or ""),
        originator=str(payload.get("originator") or ""),
        source=str(payload.get("source") or ""),
        cli_version=str(payload.get("cli_version") or ""),
        model_provider=str(payload.get("model_provider") or ""),
        forked_from_id=str(payload.get("forked_from_id") or ""),
        parent_thread_id=parent_thread_id_from_source(payload),
        memory_mode=str(payload.get("memory_mode") or ""),
        has_base_instructions=payload.get("base_instructions") is not None,
        git_repository_url=str(git.get("repository_url") or ""),
        git_branch=str(git.get("branch") or ""),
        git_commit_hash=str(git.get("commit_hash") or ""),
        is_subagent=is_structured_subagent(payload),
    )
