from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import tzinfo
from typing import Iterable, Mapping

from codex_usage.models import ROOT_USAGE_ROLE, TokenUsage, UsageRecord


@dataclass(frozen=True, slots=True)
class LedgerTask:
    task_id: str
    parent_task_id: str
    usage_role: str
    title: str


@dataclass(frozen=True, slots=True)
class ActivityTotals:
    usage: TokenUsage
    responses: int


@dataclass(frozen=True, slots=True)
class AgentActivityRow:
    agent_id: str
    label: str
    role: str
    root_task_id: str
    projects: tuple[tuple[str, str], ...]
    active_days: int
    totals: ActivityTotals


@dataclass(frozen=True, slots=True)
class AgentDayRow:
    day: str
    agent_id: str
    label: str
    role: str
    root_task_id: str
    projects: tuple[tuple[str, str], ...]
    totals: ActivityTotals


@dataclass(frozen=True, slots=True)
class DailyActivityRow:
    day: str
    totals: ActivityTotals
    active_root_tasks: int
    active_subagents: int


@dataclass(frozen=True, slots=True)
class AgentActivity:
    totals: ActivityTotals
    daily_rows: tuple[DailyActivityRow, ...]
    agent_rows: tuple[AgentActivityRow, ...]
    role_totals: Mapping[str, ActivityTotals]
    root_task_totals: Mapping[str, ActivityTotals]
    agent_day_rows: tuple[AgentDayRow, ...]


@dataclass
class _Bucket:
    usage: TokenUsage = TokenUsage()
    responses: int = 0
    days: set[str] | None = None
    projects: dict[str, str] | None = None

    def add(self, record: UsageRecord, *, day: str, include_day: bool = True) -> None:
        self.usage = self.usage.add(record.usage)
        self.responses += 1
        if include_day:
            if self.days is None:
                self.days = set()
            self.days.add(day)
        if self.projects is None:
            self.projects = {}
        self.projects.setdefault(record.project_key, record.project_label)

    def totals(self) -> ActivityTotals:
        return ActivityTotals(usage=self.usage, responses=self.responses)


def build_agent_activity(
    records: Iterable[UsageRecord],
    tasks: Mapping[str, LedgerTask],
    timezone: tzinfo,
) -> AgentActivity:
    """Aggregate only the report's filtered ledger records.

    The task map is ledger metadata, not a source-file lookup. It lets nested
    agents retain their top-level task relationship when their parent has no
    usage inside the selected calendar range.
    """
    selected = list(records)
    task_map = dict(tasks)
    for record in selected:
        task_map.setdefault(
            record.session_id,
            LedgerTask(
                task_id=record.session_id,
                parent_task_id=record.parent_thread_id,
                usage_role=record.usage_role,
                title="",
            ),
        )
    root_by_agent = {
        task_id: _resolve_root_task(task_id, task_map) for task_id in task_map
    }
    agent_buckets: dict[str, _Bucket] = defaultdict(_Bucket)
    day_buckets: dict[str, _Bucket] = defaultdict(_Bucket)
    role_buckets: dict[str, _Bucket] = defaultdict(_Bucket)
    root_buckets: dict[str, _Bucket] = defaultdict(_Bucket)
    agent_day_buckets: dict[tuple[str, str], _Bucket] = defaultdict(_Bucket)
    active_roots_by_day: dict[str, set[str]] = defaultdict(set)
    active_subagents_by_day: dict[str, set[str]] = defaultdict(set)

    for record in selected:
        day = record.timestamp.astimezone(timezone).date().isoformat()
        task = task_map[record.session_id]
        root_id = root_by_agent[record.session_id]
        role = "Root" if task.usage_role == ROOT_USAGE_ROLE else "Subagent"
        agent_buckets[record.session_id].add(record, day=day)
        day_buckets[day].add(record, day=day, include_day=False)
        role_buckets[role].add(record, day=day, include_day=False)
        root_buckets[root_id].add(record, day=day, include_day=False)
        agent_day_buckets[(day, record.session_id)].add(record, day=day, include_day=False)
        active_roots_by_day[day].add(root_id)
        if role == "Subagent":
            active_subagents_by_day[day].add(record.session_id)

    daily_rows = tuple(
        DailyActivityRow(
            day=day,
            totals=bucket.totals(),
            active_root_tasks=len(active_roots_by_day[day]),
            active_subagents=len(active_subagents_by_day[day]),
        )
        for day, bucket in sorted(day_buckets.items())
    )
    agent_rows = tuple(
        AgentActivityRow(
            agent_id=agent_id,
            label=_agent_label(task_map[agent_id]),
            role="Root" if task_map[agent_id].usage_role == ROOT_USAGE_ROLE else "Subagent",
            root_task_id=root_by_agent[agent_id],
            projects=tuple(sorted((bucket.projects or {}).items())),
            active_days=len(bucket.days or set()),
            totals=bucket.totals(),
        )
        for agent_id, bucket in sorted(
            agent_buckets.items(),
            key=lambda item: (-item[1].usage.total_tokens, _agent_label(task_map[item[0]]).casefold(), item[0]),
        )
    )
    agent_by_id = {row.agent_id: row for row in agent_rows}
    agent_day_rows = tuple(
        AgentDayRow(
            day=day,
            agent_id=agent_id,
            label=agent_by_id[agent_id].label,
            role=agent_by_id[agent_id].role,
            root_task_id=agent_by_id[agent_id].root_task_id,
            projects=tuple(sorted((bucket.projects or {}).items())),
            totals=bucket.totals(),
        )
        for (day, agent_id), bucket in sorted(agent_day_buckets.items())
    )
    total = _totals_for(selected)
    return AgentActivity(
        totals=total,
        daily_rows=daily_rows,
        agent_rows=agent_rows,
        role_totals={role: bucket.totals() for role, bucket in sorted(role_buckets.items())},
        root_task_totals={root: bucket.totals() for root, bucket in sorted(root_buckets.items())},
        agent_day_rows=agent_day_rows,
    )


def agent_activity_csv(activity: AgentActivity) -> str:
    """Return full UTF-8 CSV content; dashboard limits never apply here."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "date", "agent_id", "agent_label", "role", "root_task_id",
            "project_keys", "project_labels", "input_tokens",
            "cached_input_tokens", "output_tokens", "reasoning_tokens",
            "total_tokens", "responses",
        ],
        lineterminator="\n",
    )
    writer.writeheader()
    for row in activity.agent_day_rows:
        writer.writerow(
            {
                "date": row.day,
                "agent_id": row.agent_id,
                "agent_label": row.label,
                "role": row.role,
                "root_task_id": row.root_task_id,
                "project_keys": "; ".join(key for key, _ in row.projects),
                "project_labels": "; ".join(label for _, label in row.projects),
                "input_tokens": row.totals.usage.input_tokens,
                "cached_input_tokens": row.totals.usage.cached_input_tokens,
                "output_tokens": row.totals.usage.output_tokens,
                "reasoning_tokens": row.totals.usage.reasoning_output_tokens,
                "total_tokens": row.totals.usage.total_tokens,
                "responses": row.totals.responses,
            }
        )
    return output.getvalue()


def _totals_for(records: Iterable[UsageRecord]) -> ActivityTotals:
    usage = TokenUsage()
    responses = 0
    for record in records:
        usage = usage.add(record.usage)
        responses += 1
    return ActivityTotals(usage=usage, responses=responses)


def _resolve_root_task(task_id: str, tasks: Mapping[str, LedgerTask]) -> str:
    current = task_id
    seen: list[str] = []
    while True:
        if current in seen:
            # Cycles should not happen, but a deterministic member is safer
            # than looping or attributing the same usage to multiple roots.
            return min(seen[seen.index(current):])
        seen.append(current)
        task = tasks.get(current)
        if task is None or not task.parent_task_id or task.parent_task_id == current:
            return current
        parent = task.parent_task_id
        if parent not in tasks:
            # A purged/missing parent cannot become a synthetic active root.
            return current
        current = parent


def _agent_label(task: LedgerTask) -> str:
    title = task.title.strip()
    if title and title != task.task_id:
        return title
    role = "Root" if task.usage_role == ROOT_USAGE_ROLE else "Subagent"
    return f"{role} {task.task_id[:8]}"
