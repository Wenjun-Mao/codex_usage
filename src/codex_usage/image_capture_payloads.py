"""Content-free metadata decoding for image capture payloads."""

from __future__ import annotations

import json
import re
from typing import Any

from codex_usage.image_models import (
    ImageModelEvidence,
    ImageOperationKind,
    ImageUsage,
)


MAX_IMAGE_METADATA_BYTES = 64 * 1024
_DIMENSIONS = re.compile(r"^(?P<width>\d{2,5})x(?P<height>\d{2,5})$", re.IGNORECASE)
_NESTED_IMAGEGEN = re.compile(r"await\s+tools\.image_gen__imagegen\s*\(")
_ARTIFACT_NAME = re.compile(
    r"(?<![0-9A-Za-z_.-])(exec-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.png)(?![0-9A-Za-z_.-])",
    re.IGNORECASE,
)


def is_image_tool(payload: dict[str, Any]) -> bool:
    payload_type = text(payload.get("type")).casefold()
    name = text(payload.get("name") or payload.get("tool_name")).casefold()
    if payload_type == "function_call":
        return name in {"image_gen", "imagegen", "image_generation"} or name.endswith(
            "__imagegen"
        )
    return (
        payload_type == "custom_tool_call"
        and name == "exec"
        and _NESTED_IMAGEGEN.search(text(payload.get("input"))) is not None
    )


def call_id(payload: dict[str, Any]) -> str:
    return text(
        payload.get("call_id") or payload.get("tool_call_id") or payload.get("id")
    )


def arguments(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("arguments")
    if value is None and text(payload.get("type")).casefold() == "custom_tool_call":
        return _nested_arguments(text(payload.get("input")))
    if isinstance(value, dict):
        return value
    if (
        not isinstance(value, str)
        or len(value.encode("utf-8", errors="ignore")) > MAX_IMAGE_METADATA_BYTES
    ):
        return {}
    try:
        parsed = json.loads(value)
    except (ValueError, RecursionError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def result_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("result", "response", "output"):
        if isinstance(payload.get(key), dict):
            return payload[key]
    output = payload.get("output")
    if isinstance(output, list) and artifact_names(output):
        return {"output_count": len(artifact_names(output)), "status": "succeeded"}
    if (
        not isinstance(output, str)
        or len(output.encode("utf-8", errors="ignore")) > MAX_IMAGE_METADATA_BYTES
    ):
        return {}
    try:
        parsed = json.loads(output)
    except (ValueError, RecursionError):
        return {}
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list) and artifact_names(parsed):
        return {"output_count": len(artifact_names(parsed)), "status": "succeeded"}
    return {}


def _nested_arguments(source: str) -> dict[str, Any]:
    """Extract only non-content metadata from the exact nested image call."""
    match = _NESTED_IMAGEGEN.search(source)
    if match is None:
        return {}
    argument = source[match.end() : match.end() + MAX_IMAGE_METADATA_BYTES].lstrip()
    if not argument:
        return {}
    if argument.startswith('"'):
        try:
            decoded, _ = json.JSONDecoder().raw_decode(argument)
            parsed = json.loads(decoded) if isinstance(decoded, str) else None
        except (ValueError, RecursionError):
            parsed = None
        return parsed if isinstance(parsed, dict) else {}
    if argument.startswith("{"):
        try:
            parsed, _ = json.JSONDecoder().raw_decode(argument)
        except (ValueError, RecursionError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
        return _top_level_js_object_metadata(argument)
    return {}


def _top_level_js_object_metadata(source: str) -> dict[str, Any]:
    """Return content-free top-level metadata from a JavaScript object literal."""
    metadata: dict[str, Any] = {}
    depth = 0
    quote = ""
    escaped = False
    index = 0
    while index < len(source):
        character = source[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            index += 1
            continue
        if character in {'"', "'", "`"}:
            quote = character
            index += 1
            continue
        if character == "{":
            depth += 1
            index += 1
            continue
        if character == "}":
            depth -= 1
            if depth <= 0:
                break
            index += 1
            continue
        if depth == 1 and (character.isalpha() or character in "_$"):
            end = index + 1
            while end < len(source) and (source[end].isalnum() or source[end] in "_$"):
                end += 1
            cursor = end
            while cursor < len(source) and source[cursor].isspace():
                cursor += 1
            if cursor < len(source) and source[cursor] == ":":
                key = source[index:end]
                metadata[key] = _safe_js_metadata_value(key, source, cursor + 1)
            index = end
            continue
        index += 1
    return metadata


def _safe_js_metadata_value(key: str, source: str, offset: int) -> object:
    """Decode only accounting metadata; never retain prompt or path contents."""
    value = source[offset:].lstrip()
    if key == "referenced_image_paths":
        if value.startswith("["):
            return [] if value[1:].lstrip().startswith("]") else [True]
        return None
    if key == "num_last_images_to_include":
        match = re.match(r"[+-]?\d+", value)
        return int(match.group(0)) if match else None
    if key in {"input_image", "image", "mask"}:
        lowered = value.casefold()
        if lowered.startswith(("null", "undefined", "false", "''", '""')):
            return None
        return True
    if key in {"operation", "kind"}:
        match = re.match(r"(['\"])([a-z_-]{1,32})\1", value, re.IGNORECASE)
        return match.group(2) if match else ""
    if key in {"width", "height"}:
        match = re.match(r"\d{1,5}", value)
        return int(match.group(0)) if match else None
    if key in {"size", "dimensions"}:
        match = re.match(r"(['\"])(\d{2,5}x\d{2,5})\1", value, re.IGNORECASE)
        return match.group(2) if match else ""
    return True


def artifact_names(value: object) -> tuple[str, ...]:
    """Find safe generated basenames in a bounded decoded result structure."""
    remaining = MAX_IMAGE_METADATA_BYTES
    names: list[str] = []

    def visit(item: object) -> None:
        nonlocal remaining
        if remaining <= 0:
            return
        if isinstance(item, str):
            encoded = item.encode("utf-8", errors="ignore")[:remaining]
            remaining -= len(encoded)
            for match in _ARTIFACT_NAME.finditer(
                encoded.decode("utf-8", errors="ignore")
            ):
                name = match.group(1)
                if name not in names:
                    names.append(name)
            return
        if isinstance(item, dict):
            for key, nested in item.items():
                visit(key)
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return tuple(names)


def kind_from_mapping(value: dict[str, Any]) -> ImageOperationKind:
    requested = text(value.get("operation") or value.get("kind")).casefold()
    if requested in {"edit", "edit_reference", "variation"} or has_reference_inputs(
        value
    ):
        return ImageOperationKind.EDIT_REFERENCE
    return (
        ImageOperationKind.GENERATE
        if requested in {"", "generate", "generation"}
        else ImageOperationKind.UNKNOWN
    )


def has_reference_inputs(value: dict[str, Any]) -> bool:
    paths = value.get("referenced_image_paths")
    prior_count = integer(value.get("num_last_images_to_include"))
    return (
        isinstance(paths, list)
        and bool(paths)
        or bool(prior_count and prior_count > 0)
        or any(bool(value.get(key)) for key in ("input_image", "image", "mask"))
    )


def dimensions(value: dict[str, Any]) -> tuple[int | None, int | None]:
    width = integer(value.get("width"))
    height = integer(value.get("height"))
    if width is not None and height is not None:
        return width, height
    match = _DIMENSIONS.fullmatch(text(value.get("size") or value.get("dimensions")))
    return (
        (int(match.group("width")), int(match.group("height")))
        if match
        else (None, None)
    )


def output_count(value: dict[str, Any]) -> int | None:
    direct = integer(first_present(value, "output_count", "n"))
    if direct is not None:
        return max(0, direct)
    for key in ("data", "images"):
        items = value.get(key)
        if isinstance(items, list):
            return len(items)
    return None


def usage_from_mapping(value: dict[str, Any]) -> ImageUsage | None:
    usage = value.get("usage")
    if not isinstance(usage, dict):
        return None
    details = (
        usage.get("input_tokens_details")
        if isinstance(usage.get("input_tokens_details"), dict)
        else {}
    )
    image_details = (
        usage.get("image_tokens") if isinstance(usage.get("image_tokens"), dict) else {}
    )
    values = ImageUsage(
        text_input_tokens=integer(
            first_present(usage, "text_input_tokens", "input_text_tokens")
        ),
        cached_text_input_tokens=integer(
            first_present(usage, "cached_text_input_tokens")
            if "cached_text_input_tokens" in usage
            else details.get("cached_tokens")
        ),
        text_output_tokens=integer(
            first_present(usage, "text_output_tokens", "output_text_tokens")
        ),
        image_input_tokens=integer(
            first_present(usage, "image_input_tokens")
            if "image_input_tokens" in usage
            else image_details.get("input_tokens")
        ),
        cached_image_input_tokens=integer(
            first_present(usage, "cached_image_input_tokens")
            if "cached_image_input_tokens" in usage
            else image_details.get("cached_input_tokens")
        ),
        image_output_tokens=integer(
            first_present(usage, "image_output_tokens")
            if "image_output_tokens" in usage
            else image_details.get("output_tokens")
        ),
        total_tokens=integer(usage.get("total_tokens")),
    )
    observed = (
        values.text_input_tokens,
        values.cached_text_input_tokens,
        values.text_output_tokens,
        values.image_input_tokens,
        values.cached_image_input_tokens,
        values.image_output_tokens,
        values.total_tokens,
    )
    return values if any(item is not None for item in observed) else None


def failed(value: dict[str, Any]) -> bool:
    return bool(value.get("error")) or text(value.get("status")).casefold() in {
        "error",
        "failed",
        "failure",
    }


def bounded_failure(prefix: bytes) -> bool:
    for value in _bounded_field_values(prefix, "error"):
        if not value.startswith((b"null", b"false", b'""', b'\\"\\"')):
            return True
    return any(
        value.startswith(
            (
                b'"error',
                b'"failed',
                b'"failure',
                b'\\"error',
                b'\\"failed',
                b'\\"failure',
            )
        )
        for value in _bounded_field_values(prefix, "status")
    )


def _bounded_field_values(prefix: bytes, field: str) -> tuple[bytes, ...]:
    lowered = prefix.lower()
    key = field.encode("ascii")
    values: list[bytes] = []
    for marker in (b'"' + key + b'"', b'\\"' + key + b'\\"'):
        offset = lowered.find(marker)
        if offset >= 0:
            remainder = lowered[offset + len(marker) :].lstrip()
            if remainder.startswith(b":"):
                values.append(remainder[1:].lstrip())
    return tuple(values)


def append_evidence(
    evidence: tuple[ImageModelEvidence, ...],
    candidate: ImageModelEvidence,
) -> tuple[ImageModelEvidence, ...]:
    return evidence if candidate in evidence else (*evidence, candidate)


def prefix_value(pattern: re.Pattern[bytes], prefix: bytes) -> str:
    match = pattern.search(prefix)
    return match.group(1).decode("utf-8", errors="ignore") if match else ""


def integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def first_present(mapping: dict[str, Any], *keys: str) -> object:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
