"""Dashboard daily totals without constructing CSV-only per-agent buckets."""
from collections import defaultdict
from dataclasses import dataclass

from codex_usage.agent_activity import ActivityTotals, DailyActivityRow, LedgerTask, _resolve_root_task
from codex_usage.models import ROOT_USAGE_ROLE, TokenUsage


@dataclass(frozen=True, slots=True)
class DailyAgentActivity:
    totals: ActivityTotals
    daily_rows: tuple[DailyActivityRow, ...]


def build_daily_activity(records, tasks, timezone):
    task_map = dict(tasks)
    for record in records:
        if record.session_id not in task_map:
            task_map[record.session_id] = LedgerTask(
                record.session_id, record.parent_thread_id, record.usage_role, "")
    roots = {task_id: _resolve_root_task(task_id, task_map) for task_id in task_map}
    totals, counts = {}, defaultdict(int)
    active_roots, active_subagents = defaultdict(set), defaultdict(set)
    total = TokenUsage()
    for record in records:
        day = record.timestamp.astimezone(timezone).date().isoformat()
        totals[day] = totals.get(day, TokenUsage()).add(record.usage)
        counts[day] += 1
        total = total.add(record.usage)
        active_roots[day].add(roots[record.session_id])
        if task_map[record.session_id].usage_role != ROOT_USAGE_ROLE:
            active_subagents[day].add(record.session_id)
    return DailyAgentActivity(ActivityTotals(total, sum(counts.values())), tuple(
        DailyActivityRow(day, ActivityTotals(usage, counts[day]),
                         len(active_roots[day]), len(active_subagents[day]))
        for day, usage in sorted(totals.items())))
