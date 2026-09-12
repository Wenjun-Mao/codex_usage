"""Bounded, content-free extraction of Codex image-generation activity.

This module intentionally accepts only decoded JSON objects or a short row
prefix.  It never retains prompts, response text, image paths, base64 payloads,
or image bytes.  A pending invocation is checkpointed so a result arriving in a
later append can update the same durable operation.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from codex_usage.image_capture_models import (
    CapturedImageOperation,
)
from codex_usage.image_models import (
    ImageEvidenceConfidence,
    ImageEvidenceSource,
    ImageModelEvidence,
    ImageOperationKind,
    ImageOutcome,
    ImageUsage,
)
from codex_usage.models import SessionMetadata, usage_role_from_is_subagent
from codex_usage.project_identity import resolve_project_identity


MAX_IMAGE_METADATA_BYTES = 64 * 1024
_DIMENSIONS = re.compile(r"^(?P<width>\d{2,5})x(?P<height>\d{2,5})$", re.IGNORECASE)
_PREFIX_CALL_ID = re.compile(rb'"(?:call_id|tool_call_id|id)"\s*:\s*"([^"\\]{1,256})"')
_PREFIX_MODEL = re.compile(rb'"model"\s*:\s*"([^"\\]{1,256})"')
_PREFIX_ERROR = re.compile(rb'"(?:error|status)"\s*:\s*"?(?:error|failed)[^"\\]*"?', re.IGNORECASE)


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
        (ImageModelEvidence(model, ImageEvidenceSource.TOOL_INVOCATION, ImageEvidenceConfidence.HIGH),)
        if model
        else ()
    )
    kind = (
        ImageOperationKind.EDIT_REFERENCE
        if any(key in arguments for key in ("referenced_image_paths", "input_image", "image", "mask"))
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
    if b'"function_call"' not in folded or b"imagegen" not in folded and b"image_gen" not in folded:
        return None
    call_id = _prefix_value(_PREFIX_CALL_ID, prefix)
    if not call_id:
        return None
    model = _prefix_value(_PREFIX_MODEL, prefix)
    evidence = (
        (ImageModelEvidence(model, ImageEvidenceSource.TOOL_INVOCATION, ImageEvidenceConfidence.HIGH),)
        if model
        else ()
    )
    return _operation_context(
        tool_call_id=call_id,
        timestamp=timestamp,
        metadata=metadata,
        root_task_id=root_task_id,
        turn_id=turn_id,
        kind=ImageOperationKind.EDIT_REFERENCE if b"referenced_image" in folded else ImageOperationKind.GENERATE,
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
        (ImageModelEvidence(model, ImageEvidenceSource.RESPONSE_USAGE, ImageEvidenceConfidence.EXACT),)
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
) -> CapturedImageOperation | None:
    call_id = _call_id(payload)
    if not call_id:
        return None
    operation = next((item for item in pending if item.tool_call_id == call_id), None)
    return None if operation is None else apply_result(operation, payload)


def bounded_result_for_pending(
    prefix: bytes,
    pending: tuple[CapturedImageOperation, ...],
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
    if _PREFIX_ERROR.search(prefix):
        return replace(operation, outcome=ImageOutcome.FAILED, evidence=evidence)
    # A partial row cannot prove the number of outputs or complete usage, but a
    # result array is sufficient to settle the invocation without retaining it.
    if any(
        marker in prefix
        for marker in (b'"data"', b'"images"', b'\\"data\\"', b'\\"images\\"')
    ):
        return replace(operation, outcome=ImageOutcome.SUCCEEDED, evidence=evidence)
    return replace(operation, evidence=evidence)


def apply_result(
    operation: CapturedImageOperation,
    payload: dict[str, Any],
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
    has_result = bool(result) or any(
        key in combined for key in ("data", "images", "output_count", "usage", "error", "status")
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
        output_count=output_count if output_count is not None else operation.output_count,
        output_width=width if width is not None else operation.output_width,
        output_height=height if height is not None else operation.output_height,
        output_format=_text(combined.get("output_format") or combined.get("format")) or operation.output_format,
        quality=_text(combined.get("quality")) or operation.quality,
        evidence=evidence,
        usage=_usage_from_mapping(combined) or operation.usage,
    )


def replace_pending(
    pending: tuple[CapturedImageOperation, ...],
    operation: CapturedImageOperation,
) -> tuple[CapturedImageOperation, ...]:
    return tuple(item for item in pending if item.tool_call_id != operation.tool_call_id) + (operation,)


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


def _is_image_tool(payload: dict[str, Any]) -> bool:
    if _text(payload.get("type")).casefold() != "function_call":
        return False
    name = _text(payload.get("name") or payload.get("tool_name")).casefold()
    return name in {"image_gen", "imagegen", "image_generation"} or name.endswith("__imagegen")


def _call_id(payload: dict[str, Any]) -> str:
    return _text(payload.get("call_id") or payload.get("tool_call_id") or payload.get("id"))


def _arguments(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("arguments")
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or len(value.encode("utf-8", errors="ignore")) > MAX_IMAGE_METADATA_BYTES:
        return {}
    try:
        parsed = json.loads(value)
    except (ValueError, RecursionError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _result_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("result", "response"):
        if isinstance(payload.get(key), dict):
            return payload[key]
    output = payload.get("output")
    if not isinstance(output, str) or len(output.encode("utf-8", errors="ignore")) > MAX_IMAGE_METADATA_BYTES:
        return {}
    try:
        parsed = json.loads(output)
    except (ValueError, RecursionError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _kind_from_mapping(value: dict[str, Any]) -> ImageOperationKind:
    requested = _text(value.get("operation") or value.get("kind")).casefold()
    if requested in {"edit", "edit_reference", "variation"} or any(
        key in value for key in ("referenced_image_paths", "input_image", "mask")
    ):
        return ImageOperationKind.EDIT_REFERENCE
    return ImageOperationKind.GENERATE if requested in {"", "generate", "generation"} else ImageOperationKind.UNKNOWN


def _dimensions(value: dict[str, Any]) -> tuple[int | None, int | None]:
    width = _integer(value.get("width"))
    height = _integer(value.get("height"))
    if width is not None and height is not None:
        return width, height
    size = _text(value.get("size") or value.get("dimensions"))
    match = _DIMENSIONS.fullmatch(size)
    return (int(match.group("width")), int(match.group("height"))) if match else (None, None)


def _output_count(value: dict[str, Any]) -> int | None:
    direct = _integer(value.get("output_count") or value.get("n"))
    if direct is not None:
        return max(0, direct)
    for key in ("data", "images"):
        items = value.get(key)
        if isinstance(items, list):
            return len(items)
    return None


def _usage_from_mapping(value: dict[str, Any]) -> ImageUsage | None:
    usage = value.get("usage")
    if not isinstance(usage, dict):
        return None
    details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
    image_details = usage.get("image_tokens") if isinstance(usage.get("image_tokens"), dict) else {}
    values = ImageUsage(
        text_input_tokens=_integer(
            _first_present(usage, "text_input_tokens", "input_text_tokens")
        ),
        cached_text_input_tokens=_integer(
            _first_present(usage, "cached_text_input_tokens")
            if "cached_text_input_tokens" in usage
            else details.get("cached_tokens")
        ),
        text_output_tokens=_integer(
            _first_present(usage, "text_output_tokens", "output_text_tokens")
        ),
        image_input_tokens=_integer(
            _first_present(usage, "image_input_tokens")
            if "image_input_tokens" in usage
            else image_details.get("input_tokens")
        ),
        cached_image_input_tokens=_integer(
            _first_present(usage, "cached_image_input_tokens")
            if "cached_image_input_tokens" in usage
            else image_details.get("cached_input_tokens")
        ),
        image_output_tokens=_integer(
            _first_present(usage, "image_output_tokens")
            if "image_output_tokens" in usage
            else image_details.get("output_tokens")
        ),
        total_tokens=_integer(usage.get("total_tokens")),
    )
    return (
        values
        if any(
            item is not None
            for item in (
                values.text_input_tokens,
                values.cached_text_input_tokens,
                values.text_output_tokens,
                values.image_input_tokens,
                values.cached_image_input_tokens,
                values.image_output_tokens,
                values.total_tokens,
            )
        )
        else None
    )


def _failed(value: dict[str, Any]) -> bool:
    status = _text(value.get("status")).casefold()
    return bool(value.get("error")) or status in {"error", "failed", "failure"}


def _append_evidence(
    evidence: tuple[ImageModelEvidence, ...],
    candidate: ImageModelEvidence,
) -> tuple[ImageModelEvidence, ...]:
    return evidence if candidate in evidence else (*evidence, candidate)


def _prefix_value(pattern: re.Pattern[bytes], prefix: bytes) -> str:
    match = pattern.search(prefix)
    return match.group(1).decode("utf-8", errors="ignore") if match else ""


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _first_present(mapping: dict[str, Any], *keys: str) -> object:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
