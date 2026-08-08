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
    if isinstance(thread_spawn, dict):
        parent_thread_id = str(thread_spawn.get("parent_thread_id") or "").strip()
        if parent_thread_id:
            return parent_thread_id

    parent_thread_id = str(payload.get("parent_thread_id") or "").strip()
    if parent_thread_id:
        return parent_thread_id

    if subagent.get("other") != "guardian":
        return ""
    owner_thread_id = str(payload.get("session_id") or "").strip()
    task_id = str(payload.get("id") or "").strip()
    return owner_thread_id if owner_thread_id and owner_thread_id != task_id else ""
