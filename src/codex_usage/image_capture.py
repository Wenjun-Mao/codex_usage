"""Bounded, content-free extraction of Codex image-generation activity.

This module intentionally accepts only decoded JSON objects or a short row
prefix.  It never retains prompts, response text, image paths, base64 payloads,
or image bytes.  A pending invocation is checkpointed so a result arriving in a
later append can update the same durable operation.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codex_usage.image_artifacts import inspect_generated_artifact
from codex_usage.image_capture_models import (
    CapturedImageOperation,
)
from codex_usage.image_capture_payloads import (
    append_evidence as _append_evidence,
    arguments as _arguments,
    artifact_names as _artifact_names,
    bounded_failure as _bounded_failure,
    call_id as _call_id,
    dimensions as _dimensions,
    failed as _failed,
    has_reference_inputs as _has_reference_inputs,
    is_image_tool as _is_image_tool,
    kind_from_mapping as _kind_from_mapping,
    output_count as _output_count,
    prefix_value as _prefix_value,
    result_mapping as _result_mapping,
    text as _text,
    usage_from_mapping as _usage_from_mapping,
)
from codex_usage.image_models import (
    ImageEvidenceConfidence,
    ImageEvidenceSource,
    ImageModelEvidence,
    ImageOperationKind,
    ImageOutcome,
)
from codex_usage.models import SessionMetadata, usage_role_from_is_subagent
from codex_usage.project_identity import resolve_project_identity


_PREFIX_CALL_ID = re.compile(rb'"(?:call_id|tool_call_id|id)"\s*:\s*"([^"\\]{1,256})"')
_PREFIX_MODEL = re.compile(rb'"model"\s*:\s*"([^"\\]{1,256})"')


def invocation_from_payload(
    payload: dict[str, Any],
    *,
    timestamp: datetime | None,
    metadata: SessionMetadata,
    root_task_id: str,
    turn_id: str,
) -> CapturedImageOperation | None:
    """Return an attempted operation only for an explicitly named image tool."""
    if not _is_image_tool(payload):
        return None
    call_id = _call_id(payload)
    if not call_id:
        return None
    arguments = _arguments(payload)
    model = _text(arguments.get("model")) or _text(payload.get("model"))
    evidence = (
        (
            ImageModelEvidence(
                model, ImageEvidenceSource.TOOL_INVOCATION, ImageEvidenceConfidence.HIGH
            ),
        )
        if model
        else ()
    )
    kind = (
        ImageOperationKind.EDIT_REFERENCE
        if _has_reference_inputs(arguments)
        else ImageOperationKind.GENERATE
    )
    width, height = _dimensions(arguments)
    return _operation_context(
        tool_call_id=call_id,
        timestamp=timestamp,
        metadata=metadata,
        root_task_id=root_task_id,
        turn_id=turn_id,
        kind=kind,
        output_width=width,
        output_height=height,
        output_format=_text(arguments.get("output_format") or arguments.get("format")),
        quality=_text(arguments.get("quality")),
        evidence=evidence,
    )


def bounded_invocation_from_prefix(
    prefix: bytes,
    *,
    timestamp: datetime | None,
    metadata: SessionMetadata,
    root_task_id: str,
    turn_id: str,
) -> CapturedImageOperation | None:
    """Capture only call identity/model from a large tool row's safe prefix."""
    folded = prefix.lower()
    if (
        b'"function_call"' not in folded
        or b"imagegen" not in folded
        and b"image_gen" not in folded
    ):
        return None
    call_id = _prefix_value(_PREFIX_CALL_ID, prefix)
    if not call_id:
        return None
    model = _prefix_value(_PREFIX_MODEL, prefix)
    evidence = (
        (
            ImageModelEvidence(
                model, ImageEvidenceSource.TOOL_INVOCATION, ImageEvidenceConfidence.HIGH
            ),
        )
        if model
        else ()
    )
    return _operation_context(
        tool_call_id=call_id,
        timestamp=timestamp,
        metadata=metadata,
        root_task_id=root_task_id,
        turn_id=turn_id,
        kind=ImageOperationKind.EDIT_REFERENCE
        if b"referenced_image" in folded
        else ImageOperationKind.GENERATE,
        output_width=None,
        output_height=None,
        output_format="",
        quality="",
        evidence=evidence,
    )


def direct_operation_from_payload(
    payload: dict[str, Any],
    *,
    timestamp: datetime | None,
    metadata: SessionMetadata,
    root_task_id: str,
    turn_id: str,
) -> CapturedImageOperation | None:
    """Capture first-class image events that do not wrap a function call."""
    payload_type = _text(payload.get("type")).casefold()
    if "image" not in payload_type or "generation" not in payload_type:
        return None
    call_id = _call_id(payload)
    if not call_id:
        return None
    model = _text(payload.get("model"))
    evidence = (
        (
            ImageModelEvidence(
                model, ImageEvidenceSource.RESPONSE_USAGE, ImageEvidenceConfidence.EXACT
            ),
        )
        if model
        else ()
    )
    width, height = _dimensions(payload)
    operation = _operation_context(
        tool_call_id=call_id,
        timestamp=timestamp,
        metadata=metadata,
        root_task_id=root_task_id,
        turn_id=turn_id,
        kind=_kind_from_mapping(payload),
        output_width=width,
        output_height=height,
        output_format=_text(payload.get("output_format") or payload.get("format")),
        quality=_text(payload.get("quality")),
        evidence=evidence,
    )
    return apply_result(operation, payload)


def result_for_pending(
    payload: dict[str, Any],
    pending: tuple[CapturedImageOperation, ...],
    *,
    artifact_directory: Path | None = None,
) -> CapturedImageOperation | None:
    call_id = _call_id(payload)
    if not call_id:
        return None
    operation = next((item for item in pending if item.tool_call_id == call_id), None)
    return (
        None
        if operation is None
        else apply_result(operation, payload, artifact_directory=artifact_directory)
    )


def bounded_result_for_pending(
    prefix: bytes,
    pending: tuple[CapturedImageOperation, ...],
    *,
    artifact_directory: Path | None = None,
) -> CapturedImageOperation | None:
    """Use a short prefix only to settle a known pending call conservatively."""
    call_id = _prefix_value(_PREFIX_CALL_ID, prefix)
    if not call_id:
        return None
    operation = next((item for item in pending if item.tool_call_id == call_id), None)
    if operation is None:
        return None
    model = _prefix_value(_PREFIX_MODEL, prefix)
    evidence = operation.evidence
    if model:
        evidence = _append_evidence(
            evidence,
            ImageModelEvidence(
                model,
                ImageEvidenceSource.RESPONSE_USAGE,
                ImageEvidenceConfidence.HIGH,
            ),
        )
    if _bounded_failure(prefix):
        return replace(operation, outcome=ImageOutcome.FAILED, evidence=evidence)
    artifact_names = _artifact_names(prefix.decode("utf-8", errors="ignore"))
    if artifact_names:
        metadata = tuple(
            inspect_generated_artifact(artifact_directory, name)
            for name in artifact_names
        )
        for artifact in metadata:
            for item in artifact.evidence:
                evidence = _append_evidence(evidence, item)
        widths = {item.width for item in metadata if item.width is not None}
        heights = {item.height for item in metadata if item.height is not None}
        formats = {item.output_format for item in metadata if item.output_format}
        return replace(
            operation,
            outcome=ImageOutcome.SUCCEEDED,
            output_count=len(artifact_names),
            output_width=next(iter(widths))
            if len(widths) == 1
            else operation.output_width,
            output_height=next(iter(heights))
            if len(heights) == 1
            else operation.output_height,
            output_format=next(iter(formats))
            if len(formats) == 1
            else operation.output_format,
            evidence=evidence,
        )
    # A partial row cannot prove the number of outputs or complete usage, but a
    # result array is sufficient to settle the invocation without retaining it.
    if any(
        marker in prefix
        for marker in (b'"data"', b'"images"', b'\\"data\\"', b'\\"images\\"')
    ):
        return replace(operation, outcome=ImageOutcome.SUCCEEDED, evidence=evidence)
    return replace(operation, evidence=evidence)


def extension_result_for_pending(
    payload: dict[str, Any],
    pending: tuple[CapturedImageOperation, ...],
    *,
    artifact_directory: Path | None = None,
) -> CapturedImageOperation | None:
    """Settle the single in-flight image call from an Extension completion."""
    item = payload.get("item")
    if (
        _text(payload.get("type")).casefold() != "item_completed"
        or not isinstance(item, dict)
        or _text(item.get("type")).casefold() != "extension"
        or _text(item.get("kind")).casefold() != "image_gen.generation"
        or len(pending) != 1
    ):
        return None
    artifact_id = _text(item.get("id"))
    artifact_name = f"{artifact_id}.png"
    result = {
        "status": _text(item.get("status")),
        "error": item.get("failure"),
        "output": artifact_name,
    }
    return apply_result(
        pending[0],
        result,
        artifact_directory=artifact_directory,
    )


def apply_result(
    operation: CapturedImageOperation,
    payload: dict[str, Any],
    *,
    artifact_directory: Path | None = None,
) -> CapturedImageOperation:
    """Update an operation with result metadata while discarding content fields."""
    result = _result_mapping(payload)
    combined = {**payload, **result}
    model = _text(combined.get("model"))
    evidence = operation.evidence
    if model:
        evidence = _append_evidence(
            evidence,
            ImageModelEvidence(
                model,
                ImageEvidenceSource.RESPONSE_USAGE,
                ImageEvidenceConfidence.EXACT,
            ),
        )
    width, height = _dimensions(combined)
    output_count = _output_count(combined)
    artifact_names = _artifact_names(payload)
    artifact_metadata = tuple(
        inspect_generated_artifact(artifact_directory, name) for name in artifact_names
    )
    for metadata in artifact_metadata:
        for item in metadata.evidence:
            evidence = _append_evidence(evidence, item)
    artifact_widths = {
        item.width for item in artifact_metadata if item.width is not None
    }
    artifact_heights = {
        item.height for item in artifact_metadata if item.height is not None
    }
    artifact_formats = {
        item.output_format for item in artifact_metadata if item.output_format
    }
    if width is None and len(artifact_widths) == 1:
        width = next(iter(artifact_widths))
    if height is None and len(artifact_heights) == 1:
        height = next(iter(artifact_heights))
    has_result = (
        bool(result)
        or any(
            key in combined
            for key in ("data", "images", "output_count", "usage", "error", "status")
        )
        or bool(artifact_names)
    )
    outcome = (
        ImageOutcome.FAILED
        if _failed(combined)
        else ImageOutcome.SUCCEEDED
        if has_result
        else operation.outcome
    )
    return replace(
        operation,
        outcome=outcome,
        output_count=(
            output_count
            if output_count is not None
            else len(artifact_names)
            if artifact_names
            else operation.output_count
        ),
        output_width=width if width is not None else operation.output_width,
        output_height=height if height is not None else operation.output_height,
        output_format=(
            _text(combined.get("output_format") or combined.get("format"))
            or next(iter(artifact_formats), "")
            or operation.output_format
        ),
        quality=_text(combined.get("quality")) or operation.quality,
        evidence=evidence,
        usage=_usage_from_mapping(combined) or operation.usage,
    )


def replace_pending(
    pending: tuple[CapturedImageOperation, ...],
    operation: CapturedImageOperation,
) -> tuple[CapturedImageOperation, ...]:
    return tuple(
        item for item in pending if item.tool_call_id != operation.tool_call_id
    ) + (operation,)


def remove_pending(
    pending: tuple[CapturedImageOperation, ...],
    tool_call_id: str,
) -> tuple[CapturedImageOperation, ...]:
    return tuple(item for item in pending if item.tool_call_id != tool_call_id)


def _operation_context(
    *,
    tool_call_id: str,
    timestamp: datetime | None,
    metadata: SessionMetadata,
    root_task_id: str,
    turn_id: str,
    kind: ImageOperationKind,
    output_width: int | None,
    output_height: int | None,
    output_format: str,
    quality: str,
    evidence: tuple[ImageModelEvidence, ...],
) -> CapturedImageOperation:
    identity = resolve_project_identity(metadata)
    return CapturedImageOperation(
        tool_call_id=tool_call_id,
        timestamp=timestamp or metadata.timestamp or datetime.now(UTC),
        task_id=metadata.session_id,
        root_task_id=root_task_id or metadata.parent_thread_id or metadata.session_id,
        usage_role=usage_role_from_is_subagent(metadata.is_subagent),
        turn_id=turn_id,
        project_key=identity.key,
        project_label=identity.label,
        kind=kind,
        outcome=ImageOutcome.ATTEMPTED,
        output_width=output_width,
        output_height=output_height,
        output_format=output_format,
        quality=quality,
        evidence=evidence,
    )
