"""Public incremental session parser facade."""

from __future__ import annotations

from pathlib import Path

from codex_usage.image_capture_models import ImageCaptureState
from codex_usage.models import UNKNOWN, SessionMetadata
from codex_usage.session_generation_models import (
    ParsedSessionAppend,
    ParsedSessionGeneration,
)
from codex_usage.session_parser_api import (  # noqa: F401
    parse_session_file,
    parse_session_files,
)
from codex_usage.session_parser_events import parse_timestamp  # noqa: F401
from codex_usage.session_parser_incremental import _parse_session_chunk
from codex_usage.session_parser_models import (
    SessionParseCheckpoint,
    SessionParserState,
)
from codex_usage.session_parser_safety import (
    AppendCheckpointMismatch,  # noqa: F401
    PartialSessionGenerationReadError as _PartialSessionGenerationReadError,
)
from codex_usage.session_row_relevance import (  # noqa: F401
    CHECKPOINT_DIGEST_BYTES,
    SESSION_READ_BUFFER_BYTES,
)
from codex_usage.session_project_lineage import finalize_session_records  # noqa: F401


def parse_session_generation(
    path: Path,
    *,
    stop_offset: int | None = None,
    max_bytes: int | None = None,
    _capture_partial_candidates: bool = False,
) -> ParsedSessionGeneration:
    initial_metadata = SessionMetadata(session_id=path.stem, file_path=path)
    initial_state = SessionParserState(
        metadata=initial_metadata,
        root_metadata=None,
        previous_usage=None,
        root_session_id="",
        root_session_is_fork=False,
        counted_root_fork_usage=False,
        subagent_own_activity_started=False,
        current_model=UNKNOWN,
        current_turn_id="",
        current_effort="",
        current_mode="",
        image_capture=ImageCaptureState(),
    )
    try:
        chunk = _parse_session_chunk(
            path,
            initial_state,
            start_offset=0,
            stop_offset=stop_offset,
            next_record_index=0,
            next_candidate_index=0,
            expected_checkpoint=None,
            max_bytes=max_bytes,
        )
    except _PartialSessionGenerationReadError as error:
        if _capture_partial_candidates:
            raise
        raise error.cause from error
    return ParsedSessionGeneration(
        records=chunk.records,
        metadata=chunk.metadata,
        candidates=chunk.candidates,
        checkpoint=chunk.checkpoint,
        bytes_read=chunk.bytes_read,
        content_metrics=chunk.content_metrics,
        image_operations=chunk.image_operations,
    )


def parse_session_append(
    path: Path,
    checkpoint: SessionParseCheckpoint,
    *,
    stop_offset: int,
    max_bytes: int | None = None,
) -> ParsedSessionAppend:
    try:
        chunk = _parse_session_chunk(
            path,
            checkpoint.state,
            start_offset=checkpoint.byte_offset,
            stop_offset=stop_offset,
            next_record_index=checkpoint.next_record_index,
            next_candidate_index=checkpoint.next_candidate_index,
            expected_checkpoint=checkpoint,
            max_bytes=max_bytes,
        )
    except _PartialSessionGenerationReadError as error:
        raise error.cause from error
    return ParsedSessionAppend(
        records=chunk.records,
        metadata=chunk.metadata,
        candidates=chunk.candidates,
        checkpoint=chunk.checkpoint,
        bytes_read=chunk.bytes_read,
        content_metrics=chunk.content_metrics,
        start_offset=checkpoint.byte_offset,
        image_operations=chunk.image_operations,
    )
