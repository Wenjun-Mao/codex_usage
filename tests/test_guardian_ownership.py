from __future__ import annotations

import json
from pathlib import Path

from codex_usage.models import SUBAGENT_USAGE_ROLE
from codex_usage.parser import parse_session_file
from codex_usage.storage_context import load_storage_context


def test_guardian_is_preserved_inside_its_owning_task_tree(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    root = _write_task(sessions, "root")
    child = _write_task(sessions, "child", parent_id="root")
    guardian = _write_task(
        sessions,
        "guardian",
        parent_id="child",
        owner_id="root",
        guardian=True,
    )
    context = load_storage_context(
        session_dirs=[sessions], cache_dir=tmp_path / "cache"
    )

    assert context.insights.physical_file_count == 3
    assert len(context.insights.task_trees) == 1
    tree = context.insights.task_trees[0]
    assert tree.root_task_id == "root"
    assert tree.descendant_count == 2
    assert tree.has_missing_root is False
    assert tree.total_bytes == sum(path.stat().st_size for path in (root, child, guardian))

def test_guardian_usage_remains_subagent_auto_review_usage(tmp_path: Path) -> None:
    path = _write_task(
        tmp_path,
        "guardian",
        owner_id="root",
        guardian=True,
    )

    records = parse_session_file(path)

    assert len(records) == 1
    assert records[0].model == "codex-auto-review"
    assert records[0].usage_role == SUBAGENT_USAGE_ROLE
    assert records[0].parent_thread_id == "root"


def _write_task(
    sessions: Path,
    task_id: str,
    *,
    parent_id: str = "",
    owner_id: str = "",
    guardian: bool = False,
) -> Path:
    sessions.mkdir(parents=True, exist_ok=True)
    path = sessions / f"{task_id}.jsonl"
    payload: dict[str, object] = {
        "id": task_id,
        "cwd": "/projects/example",
        "source": "cli",
    }
    if guardian:
        payload.update(
            {
                "session_id": owner_id,
                "source": {"subagent": {"other": "guardian"}},
            }
        )
        if parent_id:
            payload["parent_thread_id"] = parent_id
    elif parent_id:
        payload["source"] = {
            "subagent": {"thread_spawn": {"parent_thread_id": parent_id}}
        }
    rows = [
        {
            "timestamp": "2026-08-07T12:00:00Z",
            "type": "session_meta",
            "payload": payload,
        },
        {
            "timestamp": "2026-08-07T12:00:01Z",
            "type": "turn_context",
            "payload": {"model": "codex-auto-review" if guardian else "gpt-5.6-sol"},
        },
        {
            "timestamp": "2026-08-07T12:00:02Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 80,
                        "output_tokens": 20,
                        "total_tokens": 100,
                    }
                },
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    return path
