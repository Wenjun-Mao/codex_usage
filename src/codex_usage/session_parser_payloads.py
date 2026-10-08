"""Bounded image/repository evidence from payload prefixes, independent of timing."""
from pathlib import Path

from codex_usage.image_capture import (
    bounded_invocation_from_prefix, bounded_result_for_pending,
    remove_pending, replace_pending,
)
from codex_usage.image_capture_models import ImageCaptureState
from codex_usage.image_models import ImageOutcome
from codex_usage.session_parser_events import extract_repo_path_candidates_from_bounded_prefix


def generated_artifact_directory(path: Path, task_id: str) -> Path | None:
    for parent in path.parents:
        if parent.name in {"sessions", "archived_sessions"}:
            return parent.parent / "generated_images" / task_id
    return None


def capture_bounded_payload(prefix, path, metadata, root_session_id, turn_id, image_capture):
    timestamp = metadata.timestamp
    root_task_id = metadata.parent_thread_id or root_session_id or metadata.session_id
    invocation = bounded_invocation_from_prefix(
        prefix, timestamp=timestamp, metadata=metadata,
        root_task_id=root_task_id, turn_id=turn_id,
    )
    if invocation is not None:
        return ImageCaptureState(replace_pending(image_capture.pending, invocation)), (invocation,), ()
    candidates = tuple(extract_repo_path_candidates_from_bounded_prefix(
        prefix, timestamp, metadata.session_id,
    ))
    resolved = bounded_result_for_pending(
        prefix, image_capture.pending,
        artifact_directory=generated_artifact_directory(path, metadata.session_id),
    )
    if resolved is None:
        return image_capture, (), candidates
    pending = (
        remove_pending(image_capture.pending, resolved.tool_call_id)
        if resolved.outcome is not ImageOutcome.ATTEMPTED
        else replace_pending(image_capture.pending, resolved)
    )
    return ImageCaptureState(pending), (resolved,), candidates
