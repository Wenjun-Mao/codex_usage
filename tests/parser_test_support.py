from __future__ import annotations

import json
from pathlib import Path


def write_session(tmp_path: Path, rows: list[dict]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def session_meta(
    cwd: str = "/repo/demo",
    repo: str = "",
    session_id: str = "session-1",
    forked_from_id: str = "",
    parent_thread_id: str = "",
) -> dict:
    git = {"repository_url": repo, "branch": "main"} if repo else {}
    payload = {
        "id": session_id,
        "timestamp": "2026-04-29T09:59:00Z",
        "cwd": cwd,
        "source": "vscode",
        "originator": "codex_vscode",
        "cli_version": "0.1.0",
        "git": git,
    }
    if forked_from_id:
        payload["forked_from_id"] = forked_from_id
    if parent_thread_id:
        payload["source"] = {
            "subagent": {
                "thread_spawn": {
                    "parent_thread_id": parent_thread_id,
                    "depth": 1,
                }
            }
        }
    return {
        "timestamp": "2026-04-29T09:59:00Z",
        "type": "session_meta",
        "payload": payload,
    }


def turn_context(model: str, effort: str = "medium") -> dict:
    return {
        "timestamp": "2026-04-29T09:59:30Z",
        "type": "turn_context",
        "payload": {
            "turn_id": f"turn-{model}",
            "model": model,
            "effort": effort,
            "collaboration_mode": {
                "mode": "default",
                "settings": {"model": model, "reasoning_effort": effort},
            },
        },
    }


def token(timestamp: str, usage: dict | None) -> dict:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": None if usage is None else {"total_token_usage": usage},
        },
    }


def usage(
    total: int,
    input_tokens: int | None = None,
    cached: int = 0,
    cache_write: int = 0,
    output: int | None = None,
) -> dict:
    input_value = input_tokens if input_tokens is not None else total
    output_value = output if output is not None else 0
    return {
        "input_tokens": input_value,
        "cached_input_tokens": cached,
        "cache_write_input_tokens": cache_write,
        "output_tokens": output_value,
        "reasoning_output_tokens": 0,
        "total_tokens": total,
    }
