from __future__ import annotations

from typing import Any


REMOTE_THREAD_ENTRY_KEYS = frozenset(
    {
        "file",
        "source_relative_path",
        "index_entry",
        "project_key",
        "project_label",
        "project_aliases",
        "sha256",
        "size_bytes",
        "session_updated_at",
        "exported_at",
        "source_machine_id",
    }
)
REMOTE_INDEX_KEYS = frozenset({"format_version", "updated_at", "threads"})


def require_object(value: Any, keys: frozenset[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} must contain exactly: {', '.join(sorted(keys))}")


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def require_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be an integer")
    return value


def require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def require_string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be an array of strings")
    return tuple(value)
