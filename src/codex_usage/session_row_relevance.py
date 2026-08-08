from __future__ import annotations

import re


RELEVANT_PREFIX_BYTES = 4096
CHECKPOINT_DIGEST_BYTES = 64 * 1024
SESSION_READ_BUFFER_BYTES = 1024 * 1024

_USAGE_EVENT_MARKERS_BYTES = tuple(
    marker.encode()
    for marker in (
        '"session_meta"',
        '"turn_context"',
        '"token_count"',
        '"task_started"',
    )
)
_FUNCTION_CALL_MARKERS_BYTES = (b'"response_item"', b'"function_call"')
_NORMAL_EVENT_DISCRIMINATOR = re.compile(
    rb'"type"\s*:\s*"(response_item|event_msg)"\s*,\s*'
    rb'"payload"\s*:\s*\{\s*"type"\s*:\s*"([^"\\]+)"'
)


def line_bytes_may_affect_usage(raw_line: bytes) -> bool:
    prefix = raw_line[:RELEVANT_PREFIX_BYTES]
    if (
        any(marker in prefix for marker in _USAGE_EVENT_MARKERS_BYTES)
        or all(marker in prefix for marker in _FUNCTION_CALL_MARKERS_BYTES)
        or b"\\u" in prefix
        or b"\\U" in prefix
    ):
        return True
    discriminator = _NORMAL_EVENT_DISCRIMINATOR.search(prefix)
    if discriminator is not None:
        outer_type, payload_type = discriminator.groups()
        return (outer_type, payload_type) in {
            (b"response_item", b"function_call"),
            (b"event_msg", b"token_count"),
            (b"event_msg", b"task_started"),
        }
    # Preserve invalid-UTF-8 failures and ambiguous layouts through the legacy
    # whole-row check instead of silently classifying them as irrelevant.
    if not prefix.isascii():
        return True
    return _legacy_line_bytes_may_affect_usage(raw_line)


def _legacy_line_bytes_may_affect_usage(raw_line: bytes) -> bool:
    return (
        any(marker in raw_line for marker in _USAGE_EVENT_MARKERS_BYTES)
        or all(marker in raw_line for marker in _FUNCTION_CALL_MARKERS_BYTES)
        or b"\\u" in raw_line
        or b"\\U" in raw_line
    )
