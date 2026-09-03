from __future__ import annotations

import re
from typing import Literal


RELEVANT_PREFIX_BYTES = 4096
CHECKPOINT_DIGEST_BYTES = 64 * 1024
SESSION_READ_BUFFER_BYTES = 1024 * 1024

_USAGE_EVENT_MARKERS_BYTES = tuple(
    marker.encode()
    for marker in (
        '"session_meta"',
        '"turn_context"',
        '"inter_agent_communication_metadata"',
        '"token_count"',
        '"task_started"',
    )
)
_FUNCTION_CALL_MARKERS_BYTES = (b'"response_item"', b'"function_call"')
_NORMAL_EVENT_DISCRIMINATOR = re.compile(
    rb'"type"\s*:\s*"(response_item|event_msg)"\s*,\s*'
    rb'"payload"\s*:\s*\{\s*"type"\s*:\s*"([^"\\]+)"'
)
_TOP_LEVEL_TYPE = re.compile(
    rb'^\s*\{(?:(?!"payload"\s*:).){0,4096}?"type"\s*:\s*"([^"\\]+)"',
    re.DOTALL,
)

type RowRelevance = Literal["relevant", "irrelevant", "unclassified"]


def classify_row_prefix(prefix: bytes, *, complete: bool) -> RowRelevance:
    inspected = prefix[:RELEVANT_PREFIX_BYTES]
    if (
        any(marker in inspected for marker in _USAGE_EVENT_MARKERS_BYTES)
        or all(marker in inspected for marker in _FUNCTION_CALL_MARKERS_BYTES)
        or b"\\u" in inspected
        or b"\\U" in inspected
        or not inspected.isascii()
    ):
        return "relevant"
    discriminator = _NORMAL_EVENT_DISCRIMINATOR.search(inspected)
    if discriminator is not None:
        outer_type, payload_type = discriminator.groups()
        return (
            "relevant"
            if (outer_type, payload_type)
            in {
                (b"response_item", b"function_call"),
                (b"event_msg", b"token_count"),
                (b"event_msg", b"task_started"),
            }
            else "irrelevant"
        )
    top_level = _TOP_LEVEL_TYPE.search(inspected)
    if top_level is not None:
        event_type = top_level.group(1)
        if event_type not in {
            b"session_meta",
            b"turn_context",
            b"inter_agent_communication_metadata",
            b"response_item",
            b"event_msg",
        }:
            return "irrelevant"
    if complete:
        return (
            "relevant"
            if _legacy_line_bytes_may_affect_usage(prefix)
            else "irrelevant"
        )
    return "unclassified"


def line_bytes_may_affect_usage(raw_line: bytes) -> bool:
    return classify_row_prefix(raw_line, complete=True) == "relevant"


def _legacy_line_bytes_may_affect_usage(raw_line: bytes) -> bool:
    return (
        any(marker in raw_line for marker in _USAGE_EVENT_MARKERS_BYTES)
        or all(marker in raw_line for marker in _FUNCTION_CALL_MARKERS_BYTES)
        or b"\\u" in raw_line
        or b"\\U" in raw_line
    )
