from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codex_usage.models import (
    UNKNOWN,
    SessionMetadata,
    TokenUsage,
    UsageRecord,
    usage_role_from_is_subagent,
)
from codex_usage.project_identity import resolve_project_identity
from codex_usage.session_generation_models import (
    ParsedSessionAppend,
    ParsedSessionGeneration,
    RawRepoPathCandidate,
)
from codex_usage.session_parser_models import (
    SessionParseCheckpoint,
    SessionParserState,
)
from codex_usage.session_parser_events import (
    extract_collaboration_mode as _extract_collaboration_mode,
    extract_effort as _extract_effort,
    extract_model as _extract_model,
    extract_repo_path_candidates as _extract_repo_path_candidates,
    parse_json_line as _parse_json_line,
    parse_session_metadata as _parse_session_metadata,
    parse_timestamp,
)
from codex_usage.session_project_lineage import finalize_session_records
from codex_usage.session_chunk_reader import read_candidate_row
from codex_usage.session_row_relevance import (
    CHECKPOINT_DIGEST_BYTES,
    SESSION_READ_BUFFER_BYTES,
)
from codex_usage.storage_content import (
    StorageContentMetrics,
)


class AppendCheckpointMismatch(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _ParsedChunk:
    records: tuple[UsageRecord, ...]
    metadata: SessionMetadata
    candidates: tuple[RawRepoPathCandidate, ...]
    checkpoint: SessionParseCheckpoint
    bytes_read: int
    content_metrics: StorageContentMetrics


class _PartialSessionGenerationReadError(OSError):
    def __init__(
        self,
        candidates: tuple[RawRepoPathCandidate, ...],
        cause: OSError | UnicodeDecodeError,
    ) -> None:
        super().__init__(str(cause))
        self.candidates = candidates
        self.cause = cause


def parse_session_files(paths: Iterable[Path]) -> list[UsageRecord]:
    return finalize_session_records([parse_session_file(path) for path in paths])


def parse_session_file(path: Path) -> list[UsageRecord]:
    return list(parse_session_generation(path).records)


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
    )


def _parse_session_chunk(
    path: Path,
    initial_state: SessionParserState,
    *,
    start_offset: int,
    stop_offset: int | None,
    next_record_index: int,
    next_candidate_index: int,
    expected_checkpoint: SessionParseCheckpoint | None,
    max_bytes: int | None,
) -> _ParsedChunk:
    metadata = initial_state.metadata
    root_metadata = initial_state.root_metadata
    records: list[UsageRecord] = []
    candidates: list[RawRepoPathCandidate] = []
    previous_usage = initial_state.previous_usage
    root_session_id = initial_state.root_session_id
    root_session_is_fork = initial_state.root_session_is_fork
    counted_root_fork_usage = initial_state.counted_root_fork_usage
    subagent_own_activity_started = initial_state.subagent_own_activity_started
    current_model = initial_state.current_model
    current_turn_id = initial_state.current_turn_id
    current_effort = initial_state.current_effort
    current_mode = initial_state.current_mode
    bytes_read = 0
    checkpoint_offset = start_offset
    content_metrics = StorageContentMetrics()

    try:
        with path.open("rb", buffering=SESSION_READ_BUFFER_BYTES) as handle:
            opened_stat = os.fstat(handle.fileno())
            source_device = int(opened_stat.st_dev)
            source_inode = int(opened_stat.st_ino)
            captured_stop = opened_stat.st_size if stop_offset is None else stop_offset
            if captured_stop < start_offset or opened_stat.st_size < captured_stop:
                raise OSError("session file changed before its captured snapshot could be read")
            if expected_checkpoint is not None:
                bytes_read += _validate_append_checkpoint(
                    handle,
                    expected_checkpoint,
                    source_device=source_device,
                    source_inode=source_inode,
                    stop_offset=captured_stop,
                )
            handle.seek(start_offset)
            target_stop = (
                captured_stop
                if max_bytes is None
                else min(captured_stop, start_offset + max(1, max_bytes))
            )
            while handle.tell() < captured_stop and handle.tell() < target_stop:
                line_start = handle.tell()
                raw_line, complete_line, row_bytes, relevance = read_candidate_row(
                    handle,
                    captured_stop,
                )
                if not raw_line:
                    break
                bytes_read += row_bytes
                line_end = handle.tell()
                unterminated_tail = (
                    line_end == captured_stop and not complete_line
                )
                # A definitively irrelevant row is safe to checkpoint even when the
                # source has not written a trailing newline. Its discriminator cannot
                # become relevant by appending more payload bytes.
                if relevance == "irrelevant":
                    checkpoint_offset = line_end
                    continue
                try:
                    decoded_line = raw_line.decode("utf-8")
                except UnicodeDecodeError as exc:
                    if (
                        unterminated_tail
                        and exc.reason == "unexpected end of data"
                        and exc.end == len(raw_line)
                    ):
                        handle.seek(line_start)
                        break
                    raise
                obj = _parse_json_line(decoded_line)
                if obj is None:
                    if unterminated_tail:
                        handle.seek(line_start)
                        break
                    checkpoint_offset = line_end
                    continue

                event_timestamp = parse_timestamp(obj.get("timestamp"))
                event_type = obj.get("type")
                payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}

                if event_type == "session_meta":
                    metadata = _parse_session_metadata(payload, path, event_timestamp)
                    if root_metadata is None:
                        root_metadata = metadata
                        root_session_id = metadata.session_id
                        root_session_is_fork = bool(metadata.forked_from_id)
                        subagent_own_activity_started = not (
                            metadata.is_subagent and root_session_is_fork
                        )
                    checkpoint_offset = line_end
                    continue

                if event_type == "inter_agent_communication_metadata":
                    subagent_own_activity_started = True
                    checkpoint_offset = line_end
                    continue

                if event_type == "response_item":
                    candidates.extend(
                        _extract_repo_path_candidates(
                            payload,
                            event_timestamp,
                            metadata.session_id,
                        )
                    )
                    checkpoint_offset = line_end
                    continue

                if event_type == "turn_context":
                    current_turn_id = str(payload.get("turn_id") or current_turn_id)
                    current_model = _extract_model(payload) or current_model
                    current_effort = _extract_effort(payload) or current_effort
                    current_mode = _extract_collaboration_mode(payload) or current_mode
                    checkpoint_offset = line_end
                    continue

                if event_type != "event_msg":
                    checkpoint_offset = line_end
                    continue

                payload_type = payload.get("type")
                if payload_type == "task_started":
                    current_turn_id = str(payload.get("turn_id") or current_turn_id)
                    current_mode = str(payload.get("collaboration_mode_kind") or current_mode)
                    checkpoint_offset = line_end
                    continue
                if payload_type != "token_count":
                    checkpoint_offset = line_end
                    continue

                info = payload.get("info")
                if not isinstance(info, dict):
                    checkpoint_offset = line_end
                    continue

                total_usage = TokenUsage.from_mapping(info.get("total_token_usage"))
                had_previous_usage = previous_usage is not None
                delta = total_usage.positive_delta(previous_usage)
                previous_usage = total_usage
                if delta is None:
                    checkpoint_offset = line_end
                    continue

                # New structured subagent forks replay their parent's cumulative
                # usage before this file's own inter-agent activity begins. The
                # replay establishes the baseline but is not newly consumed usage.
                if (
                    root_metadata is not None
                    and root_metadata.is_subagent
                    and root_session_is_fork
                    and not subagent_own_activity_started
                ):
                    checkpoint_offset = line_end
                    continue

                is_root_session = not root_session_id or metadata.session_id == root_session_id
                if root_session_is_fork and not is_root_session:
                    checkpoint_offset = line_end
                    continue
                # Fork files can replay imported parent history before actual fork work. A first root
                # snapshot without a prior baseline is inherited context, not newly consumed tokens.
                if root_session_is_fork and is_root_session and not counted_root_fork_usage and not had_previous_usage:
                    checkpoint_offset = line_end
                    continue

                timestamp = event_timestamp or metadata.timestamp
                if timestamp is None:
                    checkpoint_offset = line_end
                    continue

                project_identity = resolve_project_identity(metadata)
                records.append(
                    UsageRecord(
                        timestamp=timestamp,
                        usage=delta,
                        session_id=metadata.session_id,
                        file_path=path,
                        usage_role=usage_role_from_is_subagent(metadata.is_subagent),
                        model=current_model,
                        turn_id=current_turn_id,
                        effort=current_effort,
                        collaboration_mode=current_mode,
                        project_key=project_identity.key,
                        project_label=project_identity.label,
                        project_aliases=project_identity.aliases,
                        cwd=metadata.cwd,
                        git_repository_url=(
                            project_identity.git_repository_url
                            if project_identity.uses_current_checkout_origin
                            else metadata.git_repository_url
                            or project_identity.git_repository_url
                        ),
                        git_branch=metadata.git_branch,
                        parent_thread_id=metadata.parent_thread_id,
                    )
                )
                if root_session_is_fork and is_root_session:
                    counted_root_fork_usage = True
                checkpoint_offset = line_end

            current_path_stat = path.stat()
            if (
                int(current_path_stat.st_dev) != source_device
                or int(current_path_stat.st_ino) != source_inode
                or current_path_stat.st_size < captured_stop
            ):
                raise OSError("session file identity changed during parsing")
            state = SessionParserState(
                metadata=metadata,
                root_metadata=root_metadata,
                previous_usage=previous_usage,
                root_session_id=root_session_id,
                root_session_is_fork=root_session_is_fork,
                counted_root_fork_usage=counted_root_fork_usage,
                subagent_own_activity_started=subagent_own_activity_started,
                current_model=current_model,
                current_turn_id=current_turn_id,
                current_effort=current_effort,
                current_mode=current_mode,
            )
            head_sha256, head_bytes = _digest_range(
                handle, 0, min(CHECKPOINT_DIGEST_BYTES, checkpoint_offset)
            )
            boundary_start = max(0, checkpoint_offset - CHECKPOINT_DIGEST_BYTES)
            boundary_sha256, boundary_bytes = _digest_range(
                handle, boundary_start, checkpoint_offset
            )
            bytes_read += head_bytes + boundary_bytes
    except (OSError, UnicodeDecodeError) as error:
        raise _PartialSessionGenerationReadError(tuple(candidates), error) from error

    selected_metadata = root_metadata or SessionMetadata(
        session_id=path.stem,
        file_path=path,
    )
    checkpoint = SessionParseCheckpoint(
        byte_offset=checkpoint_offset,
        next_record_index=next_record_index + len(records),
        next_candidate_index=next_candidate_index + len(candidates),
        source_device=source_device,
        source_inode=source_inode,
        head_sha256=head_sha256,
        boundary_sha256=boundary_sha256,
        session_id=selected_metadata.session_id,
        state=state,
    )
    return _ParsedChunk(
        records=tuple(records),
        metadata=selected_metadata,
        candidates=tuple(candidates),
        checkpoint=checkpoint,
        bytes_read=bytes_read,
        content_metrics=content_metrics,
    )


def _validate_append_checkpoint(
    handle: Any,
    checkpoint: SessionParseCheckpoint,
    *,
    source_device: int,
    source_inode: int,
    stop_offset: int,
) -> int:
    if not source_device or not source_inode:
        raise AppendCheckpointMismatch("source file identity is unavailable")
    if (
        source_device != checkpoint.source_device
        or source_inode != checkpoint.source_inode
    ):
        raise AppendCheckpointMismatch("source file identity changed")
    if stop_offset < checkpoint.byte_offset:
        raise AppendCheckpointMismatch("source file was truncated")
    expected_session_id = (
        checkpoint.state.root_metadata or checkpoint.state.metadata
    ).session_id
    if not checkpoint.session_id or checkpoint.session_id != expected_session_id:
        raise AppendCheckpointMismatch("checkpoint task identity is inconsistent")
    head_sha256, head_bytes = _digest_range(
        handle, 0, min(CHECKPOINT_DIGEST_BYTES, checkpoint.byte_offset)
    )
    boundary_start = max(0, checkpoint.byte_offset - CHECKPOINT_DIGEST_BYTES)
    boundary_sha256, boundary_bytes = _digest_range(
        handle, boundary_start, checkpoint.byte_offset
    )
    if head_sha256 != checkpoint.head_sha256:
        raise AppendCheckpointMismatch("source file header changed")
    if boundary_sha256 != checkpoint.boundary_sha256:
        raise AppendCheckpointMismatch("source file checkpoint boundary changed")
    return head_bytes + boundary_bytes


def _digest_range(handle: Any, start: int, end: int) -> tuple[str, int]:
    handle.seek(start)
    remaining = max(0, end - start)
    digest = hashlib.sha256()
    total = 0
    while remaining:
        chunk = handle.read(min(64 * 1024, remaining))
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
        remaining -= len(chunk)
    if remaining:
        raise OSError("session file ended before checkpoint digest range")
    return digest.hexdigest(), total
