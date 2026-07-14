from __future__ import annotations

from collections.abc import Mapping
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


def require_remote_index_thread_identity(
    mapping_thread_id: object,
    entry_thread_id: object,
    index_entry: Mapping[str, object],
) -> str:
    thread_id = require_canonical_thread_id(
        mapping_thread_id,
        f"remote index threads[{mapping_thread_id!r}] key",
    )
    canonical_entry_thread_id = require_canonical_thread_id(
        entry_thread_id,
        f"remote index thread {thread_id!r} entry.thread_id",
    )
    if thread_id != canonical_entry_thread_id:
        raise ValueError("remote index thread mapping key must match entry.thread_id")
    if "id" not in index_entry:
        raise ValueError(
            f"remote index thread {thread_id!r} entry.index_entry.id is required"
        )
    index_entry_thread_id = require_canonical_thread_id(
        index_entry["id"],
        f"remote index thread {thread_id!r} entry.index_entry.id",
    )
    if index_entry_thread_id != thread_id or index_entry_thread_id != canonical_entry_thread_id:
        raise ValueError(
            f"remote index thread {thread_id!r} entry.index_entry.id must match "
            "the mapping key and entry.thread_id"
        )
    return thread_id
