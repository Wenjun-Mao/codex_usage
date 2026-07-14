from __future__ import annotations

from typing import TypeGuard


def is_canonical_thread_id(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value) and value == value.strip()


def require_canonical_thread_id(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(
            f"{field} is invalid: thread ids must not be blank and must be canonical"
        )
    if value != value.strip():
        raise ValueError(
            f"{field} must be canonical (nonempty and equal to its own trim)"
        )
    return value
