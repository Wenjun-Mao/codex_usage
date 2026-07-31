from __future__ import annotations

from typing import Any


def is_structured_subagent(payload: dict[str, Any]) -> bool:
    source = payload.get("source")
    return isinstance(source, dict) and isinstance(source.get("subagent"), dict)


def parent_thread_id_from_source(payload: dict[str, Any]) -> str:
    source = payload.get("source")
    if not isinstance(source, dict):
        return ""
    subagent = source.get("subagent")
    if not isinstance(subagent, dict):
        return ""
    thread_spawn = subagent.get("thread_spawn")
    if not isinstance(thread_spawn, dict):
        return ""
    return str(thread_spawn.get("parent_thread_id") or "")
