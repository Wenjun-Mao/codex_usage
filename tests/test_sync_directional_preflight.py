from pathlib import Path

from codex_usage.sync.directional_preflight import directional_blockers
from codex_usage.sync.models import SyncFileSnapshot, SyncPlan, SyncPlanItem


def _item(thread_id: str, action: str) -> SyncPlanItem:
    missing = SyncFileSnapshot(path=Path(f"/{thread_id}.jsonl"), exists=False)
    return SyncPlanItem(
        thread_id=thread_id,
        state=action,
        action=action,
        reason=action,
        local=missing,
        remote=missing,
        base_sha256="",
        updated_at="",
        source_relative_path=f"2026/07/15/{thread_id}.jsonl",
        project_key="repo",
        project_label="Repo",
        memory_database_rows=0,
        expected_remote_entry=None,
    )


def _plan(*actions: str) -> SyncPlan:
    return SyncPlan(
        items=tuple(
            _item(f"task-{index}", action)
            for index, action in enumerate(actions, 1)
        ),
        issues=(),
        discovered_count=len(actions),
        remote_count=len(actions),
        selected_count=len(actions),
    )


def test_pull_blocks_every_selected_task_when_one_requires_push() -> None:
    issues = directional_blockers(_plan("pull", "none", "push"), "pull")

    assert [(issue.code, issue.thread_id) for issue in issues] == [
        ("pull_requires_push", "task-3")
    ]


def test_push_blocks_every_selected_task_when_one_requires_pull() -> None:
    issues = directional_blockers(_plan("push", "pull"), "push")

    assert [(issue.code, issue.thread_id) for issue in issues] == [
        ("push_requires_pull", "task-2")
    ]


def test_up_to_date_and_same_direction_actions_do_not_block() -> None:
    assert directional_blockers(_plan("pull", "none"), "pull") == ()
    assert directional_blockers(_plan("push", "none"), "push") == ()
