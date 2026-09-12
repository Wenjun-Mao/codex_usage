"""Content-free image capture records and checkpoint serialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from codex_usage.image_models import (
    ImageEvidenceConfidence,
    ImageEvidenceSource,
    ImageModelEvidence,
    ImageOperationKind,
    ImageOutcome,
    ImageUsage,
)


@dataclass(frozen=True, slots=True)
class CapturedImageOperation:
    """A cache-owned image operation, excluding all image content."""

    tool_call_id: str
    timestamp: datetime
    task_id: str
    root_task_id: str
    usage_role: str
    turn_id: str
    project_key: str
    project_label: str
    kind: ImageOperationKind
    outcome: ImageOutcome
    output_count: int = 0
    output_width: int | None = None
    output_height: int | None = None
    output_format: str = ""
    quality: str = ""
    evidence: tuple[ImageModelEvidence, ...] = ()
    usage: ImageUsage = ImageUsage()


@dataclass(frozen=True, slots=True)
class ImageCaptureState:
    pending: tuple[CapturedImageOperation, ...] = ()


def image_capture_state_to_json(state: ImageCaptureState) -> list[dict[str, object]]:
    return [captured_operation_to_dict(operation) for operation in state.pending]


def image_capture_state_from_json(value: object) -> ImageCaptureState:
    if value is None:
        return ImageCaptureState()
    if not isinstance(value, list):
        raise ValueError("image capture checkpoint state must be a list")
    return ImageCaptureState(
        tuple(captured_operation_from_dict(_mapping(item)) for item in value)
    )


def captured_operation_to_dict(operation: CapturedImageOperation) -> dict[str, object]:
    return {
        "tool_call_id": operation.tool_call_id,
        "timestamp": operation.timestamp.isoformat(),
        "task_id": operation.task_id,
        "root_task_id": operation.root_task_id,
        "usage_role": operation.usage_role,
        "turn_id": operation.turn_id,
        "project_key": operation.project_key,
        "project_label": operation.project_label,
        "kind": operation.kind.value,
        "outcome": operation.outcome.value,
        "output_count": operation.output_count,
        "output_width": operation.output_width,
        "output_height": operation.output_height,
        "output_format": operation.output_format,
        "quality": operation.quality,
        "evidence": [
            {
                "raw_identity": item.raw_identity,
                "source": item.source.value,
                "confidence": item.confidence.value,
                "version": item.version,
            }
            for item in operation.evidence
        ],
        "usage": {
            "text_input_tokens": operation.usage.text_input_tokens,
            "cached_text_input_tokens": operation.usage.cached_text_input_tokens,
            "text_output_tokens": operation.usage.text_output_tokens,
            "image_input_tokens": operation.usage.image_input_tokens,
            "cached_image_input_tokens": operation.usage.cached_image_input_tokens,
            "image_output_tokens": operation.usage.image_output_tokens,
            "total_tokens": operation.usage.total_tokens,
        },
    }


def captured_operation_from_dict(value: dict[str, object]) -> CapturedImageOperation:
    evidence_value = value.get("evidence")
    usage_value = value.get("usage")
    if not isinstance(evidence_value, list) or not isinstance(usage_value, dict):
        raise ValueError("invalid image capture checkpoint operation")
    return CapturedImageOperation(
        tool_call_id=_text(value.get("tool_call_id")),
        timestamp=datetime.fromisoformat(_text(value.get("timestamp"))).astimezone(UTC),
        task_id=_text(value.get("task_id")),
        root_task_id=_text(value.get("root_task_id")),
        usage_role=_text(value.get("usage_role")),
        turn_id=_text(value.get("turn_id")),
        project_key=_text(value.get("project_key")),
        project_label=_text(value.get("project_label")),
        kind=ImageOperationKind(_text(value.get("kind"))),
        outcome=ImageOutcome(_text(value.get("outcome"))),
        output_count=_integer(value.get("output_count")) or 0,
        output_width=_integer(value.get("output_width")),
        output_height=_integer(value.get("output_height")),
        output_format=_text(value.get("output_format")),
        quality=_text(value.get("quality")),
        evidence=tuple(
            ImageModelEvidence(
                _text(item.get("raw_identity")),
                ImageEvidenceSource(_text(item.get("source"))),
                ImageEvidenceConfidence(_text(item.get("confidence"))),
                _text(item.get("version")),
            )
            for raw_item in evidence_value
            if isinstance(raw_item, dict)
            for item in (_mapping(raw_item),)
        ),
        usage=ImageUsage(
            text_input_tokens=_integer(usage_value.get("text_input_tokens")),
            cached_text_input_tokens=_integer(usage_value.get("cached_text_input_tokens")),
            text_output_tokens=_integer(usage_value.get("text_output_tokens")),
            image_input_tokens=_integer(usage_value.get("image_input_tokens")),
            cached_image_input_tokens=_integer(usage_value.get("cached_image_input_tokens")),
            image_output_tokens=_integer(usage_value.get("image_output_tokens")),
            total_tokens=_integer(usage_value.get("total_tokens")),
        ),
    )


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("image capture value must be an object")
    return value


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
