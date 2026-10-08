"""Project structural header fields from streamed rows without retaining payloads."""
import json
from codex_usage.session_row_relevance import RELEVANT_PREFIX_BYTES

HEADER_FIELDS = {"type", "timestamp", "payload", "role",
                 "internal_chat_message_metadata_passthrough", "turn_id"}


def project_prefix(prefix: bytes) -> dict:
    try:
        source = prefix[:RELEVANT_PREFIX_BYTES].decode("utf-8")
    except UnicodeDecodeError:
        return {}
    decoder = json.JSONDecoder()

    def mapping(offset, depth=0):
        result = {}
        if depth > 3 or offset >= len(source) or source[offset] != "{":
            return result, offset
        offset += 1
        try:
            while offset < len(source):
                while source[offset].isspace() or source[offset] == ",":
                    offset += 1
                if source[offset] == "}":
                    return result, offset + 1
                key, offset = decoder.raw_decode(source, offset)
                while source[offset].isspace():
                    offset += 1
                if source[offset] != ":" or not isinstance(key, str):
                    return {}, offset
                offset += 1
                while source[offset].isspace():
                    offset += 1
                if key in HEADER_FIELDS and source[offset] == "{":
                    value, offset = mapping(offset, depth + 1)
                    result[key] = value
                else:
                    value, offset = decoder.raw_decode(source, offset)
                    if key in HEADER_FIELDS and isinstance(value, str) and len(value) <= 256:
                        result[key] = value
        except (ValueError, IndexError, RecursionError):
            pass
        return result, offset
    return mapping(len(source) - len(source.lstrip()))[0]
