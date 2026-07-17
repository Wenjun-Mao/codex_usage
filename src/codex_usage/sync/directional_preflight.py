from typing import Literal

from codex_usage.sync.models import SyncIssue, SyncPlan


Direction = Literal["pull", "push"]


def directional_blockers(
    plan: SyncPlan,
    direction: Direction,
) -> tuple[SyncIssue, ...]:
    opposite_direction = "push" if direction == "pull" else "pull"
    issue_code = f"{direction}_requires_{opposite_direction}"
    return tuple(
        SyncIssue(
            issue_code,
            (
                f"Selected task requires {opposite_direction} before the batch "
                f"can {direction}."
            ),
            item.thread_id,
        )
        for item in plan.items
        if item.action == opposite_direction
    )
