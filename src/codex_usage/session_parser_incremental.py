from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from codex_usage.image_capture import (
    direct_operation_from_payload,
    extension_result_for_pending,
    invocation_from_payload,
    remove_pending,
    replace_pending,
    result_for_pending,
)
from codex_usage.image_capture_models import CapturedImageOperation, ImageCaptureState
from codex_usage.image_models import ImageOutcome
from codex_usage.models import (
    SessionMetadata,
    TokenUsage,
    UsageRecord,
)
from codex_usage.session_generation_models import (
    RawRepoPathCandidate,
)
from codex_usage.session_parser_models import (
    SessionParseCheckpoint,
    SessionParserState,
)
from codex_usage.session_parser_safety import (
    digest_range as _digest_range,
    validate_append_checkpoint as _validate_append_checkpoint,
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
from codex_usage.session_chunk_reader import read_candidate_row, RecoveryRowBudgetExceeded
from codex_usage.session_row_relevance import (
    CHECKPOINT_DIGEST_BYTES,
    SESSION_READ_BUFFER_BYTES,
)
from codex_usage.allowance_models import QuotaObservation, quota_observations
from codex_usage.storage_content import (
    StorageContentMetrics,
)
from codex_usage.speed_parser import SpeedParser
from codex_usage.speed_models import SpeedFact
from codex_usage.session_parser_payloads import (
    generated_artifact_directory as _generated_artifact_directory,
    capture_bounded_payload,
)
from codex_usage.session_history import (
    HistorySource, inline_replay_possible, resolve_baseline, validate_page_metadata,
)
from codex_usage.session_history_models import PaginatedHistoryError
from codex_usage.session_usage_record import usage_record


@dataclass(frozen=True, slots=True)
class _ParsedChunk:
    records: tuple[UsageRecord, ...]
    metadata: SessionMetadata
    candidates: tuple[RawRepoPathCandidate, ...]
    checkpoint: SessionParseCheckpoint
    bytes_read: int
    content_metrics: StorageContentMetrics
    image_operations: tuple[CapturedImageOperation, ...]
    quota_observations: tuple[QuotaObservation, ...]
    speed_facts: tuple[SpeedFact, ...]
    speed_tools: tuple[tuple[float, float], ...]
    speed_uncertain_tools: tuple[str, ...]


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
    strict_byte_budget: bool = False,
    history_sources: tuple[HistorySource, ...] = (),
) -> _ParsedChunk:
    metadata = initial_state.metadata
    root_metadata = initial_state.root_metadata
    records: list[UsageRecord] = []
    candidates: list[RawRepoPathCandidate] = []
    previous_usage = initial_state.previous_usage
    root_session_id = initial_state.root_session_id
    root_session_is_fork = initial_state.root_session_is_fork
    root_inline_replay_possible = initial_state.root_inline_replay_possible
    counted_root_fork_usage = initial_state.counted_root_fork_usage
    subagent_own_activity_started = initial_state.subagent_own_activity_started
    current_model = initial_state.current_model
    current_turn_id = initial_state.current_turn_id
    current_effort = initial_state.current_effort
    current_mode = initial_state.current_mode
    image_capture = initial_state.image_capture
    speed = SpeedParser(initial_state.speed_state)
    row_drain = initial_state.row_drain
    history_baseline_pending = initial_state.history_baseline_pending
    history_boundary_digest = initial_state.history_boundary_digest
    history_dependencies = initial_state.history_dependencies
    image_operations = []
    quota_points = []
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
                raise OSError(
                    "session file changed before its captured snapshot could be read"
                )
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
                try:
                    row = read_candidate_row(
                        handle, captured_stop,
                        max_row_bytes=target_stop - line_start if strict_byte_budget else None,
                        drain_state=row_drain,
                    )
                except RecoveryRowBudgetExceeded as error:
                    if line_start == start_offset:
                        raise
                    bytes_read += error.bytes_read
                    handle.seek(line_start)
                    break
                if not row.bytes_read:
                    break
                raw_line, complete_line, row_bytes, relevance = row.raw, row.complete, row.bytes_read, row.relevance
                bytes_read += row_bytes
                line_end = handle.tell()
                if row.drain_state or row.projection is not None:
                    if relevance == "bounded" and not row_drain:
                        image_capture, operations, found = capture_bounded_payload(
                            raw_line, path, metadata, root_session_id, current_turn_id, image_capture,
                        )
                        image_operations.extend(operations)
                        candidates.extend(found)
                    row_drain = row.drain_state
                    if row.projection is not None and relevance == "bounded":
                        speed.observe_projection(*row.projection, current_model, current_turn_id)
                    checkpoint_offset = line_end
                    continue
                unterminated_tail = line_end == captured_stop and not complete_line
                # A definitively irrelevant row is safe to checkpoint even when the
                # source has not written a trailing newline. Its discriminator cannot
                # become relevant by appending more payload bytes.
                if relevance == "irrelevant":
                    checkpoint_offset = line_end
                    continue
                if relevance == "timing":
                    speed.observe_prefix(raw_line, current_model, current_turn_id)
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
                    speed.dirty()
                    continue

                event_timestamp = parse_timestamp(obj.get("timestamp"))
                event_type = obj.get("type")
                payload = (
                    obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
                )
                speed.observe(obj, current_model, current_turn_id)

                if event_type == "session_meta":
                    metadata = _parse_session_metadata(payload, path, event_timestamp, ordinal=obj.get("ordinal"))
                    if root_metadata is None:
                        validate_page_metadata(metadata)
                        root_metadata = metadata
                        root_session_id = metadata.session_id
                        root_session_is_fork = bool(metadata.forked_from_id)
                        root_inline_replay_possible = inline_replay_possible(metadata)
                        subagent_own_activity_started = not (
                            metadata.is_subagent and root_session_is_fork and root_inline_replay_possible
                        )
                        if metadata.history_base is not None:
                            baseline = resolve_baseline(metadata, history_sources)
                            previous_usage = baseline.usage
                            bytes_read += baseline.bytes_read
                            history_baseline_pending = True
                            history_boundary_digest = baseline.boundary_digest
                            history_dependencies = baseline.dependencies
                            # Paginated inheritance is external to this physical
                            # page, unlike legacy inline imported-parent replay.
                            subagent_own_activity_started = True
                    checkpoint_offset = line_end
                    continue

                if event_type == "inter_agent_communication_metadata":
                    subagent_own_activity_started = True
                    checkpoint_offset = line_end
                    continue

                if event_type == "response_item":
                    root_task_id = (
                        metadata.parent_thread_id
                        or root_session_id
                        or metadata.session_id
                    )
                    invocation = invocation_from_payload(
                        payload,
                        timestamp=event_timestamp,
                        metadata=metadata,
                        root_task_id=root_task_id,
                        turn_id=current_turn_id,
                    )
                    if invocation is not None:
                        image_capture = ImageCaptureState(
                            replace_pending(image_capture.pending, invocation)
                        )
                        image_operations.append(invocation)
                    else:
                        resolved = result_for_pending(
                            payload,
                            image_capture.pending,
                            artifact_directory=_generated_artifact_directory(
                                path, metadata.session_id
                            ),
                        )
                        if resolved is not None:
                            image_operations.append(resolved)
                            image_capture = ImageCaptureState(
                                remove_pending(
                                    image_capture.pending, resolved.tool_call_id
                                )
                                if resolved.outcome is not ImageOutcome.ATTEMPTED
                                else replace_pending(image_capture.pending, resolved)
                            )
                        else:
                            direct = direct_operation_from_payload(
                                payload,
                                timestamp=event_timestamp,
                                metadata=metadata,
                                root_task_id=root_task_id,
                                turn_id=current_turn_id,
                            )
                            if direct is not None:
                                image_operations.append(direct)
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
                    current_mode = str(
                        payload.get("collaboration_mode_kind") or current_mode
                    )
                    checkpoint_offset = line_end
                    continue
                if payload_type == "item_completed":
                    resolved = extension_result_for_pending(
                        payload,
                        image_capture.pending,
                        artifact_directory=_generated_artifact_directory(
                            path, metadata.session_id
                        ),
                    )
                    if resolved is not None:
                        image_operations.append(resolved)
                        image_capture = ImageCaptureState(
                            remove_pending(image_capture.pending, resolved.tool_call_id)
                        )
                    checkpoint_offset = line_end
                    continue
                if payload_type != "token_count":
                    checkpoint_offset = line_end
                    continue

                quota_points.extend(quota_observations(
                    payload.get("rate_limits"), event_timestamp.isoformat() if event_timestamp else ""
                ))
                info = payload.get("info")
                if not isinstance(info, dict) or info.get("total_token_usage") is None:
                    checkpoint_offset = line_end
                    continue

                total_usage = TokenUsage.from_mapping(info.get("total_token_usage"))
                if history_baseline_pending:
                    if any(total_usage.to_dict()[key] < previous_usage.to_dict()[key]
                           for key in total_usage.__dataclass_fields__):
                        raise PaginatedHistoryError("paginated_history_counter_precedes_baseline")
                    history_baseline_pending = False
                if previous_usage and any(total_usage.to_dict()[k] < previous_usage.to_dict()[k] for k in ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens")):
                    if speed.matched is not None:
                        speed.matched["reason"] = "nonmonotonic_usage"
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
                    and root_inline_replay_possible
                    and not subagent_own_activity_started
                ):
                    checkpoint_offset = line_end
                    continue

                is_root_session = (
                    not root_session_id or metadata.session_id == root_session_id
                )
                if root_session_is_fork and root_inline_replay_possible and not is_root_session:
                    checkpoint_offset = line_end
                    continue
                # Fork files can replay imported parent history before actual fork work. A first root
                # snapshot without a prior baseline is inherited context, not newly consumed tokens.
                if (
                    root_session_is_fork
                    and root_inline_replay_possible
                    and is_root_session
                    and not counted_root_fork_usage
                    and not had_previous_usage
                ):
                    checkpoint_offset = line_end
                    continue

                timestamp = event_timestamp or metadata.timestamp
                if timestamp is None:
                    checkpoint_offset = line_end
                    continue

                records.append(
                    usage_record(path, metadata, timestamp, delta, model=current_model,
                                 turn_id=current_turn_id, effort=current_effort, mode=current_mode)
                )
                if root_session_is_fork and is_root_session:
                    counted_root_fork_usage = True
                speed.finish(records[-1], next_record_index + len(records) - 1, metadata.cli_version)
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
                image_capture=image_capture,
                speed_state=speed.state,
                row_drain=row_drain,
                history_baseline_pending=history_baseline_pending,
                history_boundary_digest=history_boundary_digest,
                root_inline_replay_possible=root_inline_replay_possible,
                history_dependencies=history_dependencies,
            )
            head_sha256, head_bytes = _digest_range(
                handle, 0, min(CHECKPOINT_DIGEST_BYTES, checkpoint_offset)
            )
            boundary_start = max(0, checkpoint_offset - CHECKPOINT_DIGEST_BYTES)
            boundary_sha256, boundary_bytes = _digest_range(
                handle, boundary_start, checkpoint_offset
            )
            bytes_read += head_bytes + boundary_bytes
    except PaginatedHistoryError as error:
        error.bytes_read = bytes_read + getattr(error, "bytes_read", 0)
        raise
    except (OSError, UnicodeDecodeError) as error:
        from codex_usage.session_parser_safety import PartialSessionGenerationReadError

        raise PartialSessionGenerationReadError(tuple(candidates), error,
            bytes_read + getattr(error, "bytes_read", 0)) from error

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
        image_operations=tuple(image_operations),
        quota_observations=tuple(quota_points),
        speed_facts=tuple(speed.facts),
        speed_tools=tuple(speed.tools),
        speed_uncertain_tools=tuple(sorted(speed.uncertain_tools)),
    )
