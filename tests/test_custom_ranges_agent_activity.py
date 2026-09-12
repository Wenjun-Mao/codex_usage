from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from codex_usage.agent_activity import (
    LedgerTask,
    agent_activity_csv,
    build_agent_activity,
)
from codex_usage.report_agent_activity import render_agent_activity_section
from codex_usage.aggregation import resolve_report_range
from codex_usage.models import TokenUsage, UsageRecord


def test_custom_range_is_inclusive_local_calendar_time_across_dst() -> None:
    toronto = ZoneInfo("America/Toronto")
    resolved = resolve_report_range(
        "custom",
        toronto,
        start_date="2026-03-08",
        end_date="2026-03-08",
        now=datetime(2026, 3, 9, 12, tzinfo=toronto),
    )

    assert resolved.start_date.isoformat() == "2026-03-08"
    assert resolved.end_date.isoformat() == "2026-03-08"
    assert resolved.bounds.start_us == 1_772_946_000_000_000
    assert resolved.bounds.end_us == 1_773_028_800_000_000
    assert resolved.display_label == "Mar 8, 2026"


@pytest.mark.parametrize(
    ("start_date", "end_date", "message"),
    [
        (None, "2026-03-08", "start_date is required"),
        ("2026-03-08", "2026/03/09", "end_date must use"),
        ("2026-03-10", "2026-03-08", "start_date must be"),
        ("2026-03-08", "2026-03-11", "future"),
    ],
)
def test_custom_range_rejects_invalid_calendar_contract(
    start_date: str | None, end_date: str | None, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_report_range(
            "custom",
            UTC,
            start_date=start_date,
            end_date=end_date,
            now=datetime(2026, 3, 10, 12, tzinfo=UTC),
        )


def test_moving_preset_cache_identity_changes_at_local_midnight() -> None:
    timezone = ZoneInfo("America/Toronto")
    before = resolve_report_range(
        "today", timezone, now=datetime(2026, 3, 8, 23, 59, tzinfo=timezone)
    )
    after = resolve_report_range(
        "today", timezone, now=datetime(2026, 3, 9, 0, 1, tzinfo=timezone)
    )

    assert before.cache_identity != after.cache_identity


def test_agent_activity_conserves_selected_ledger_records_and_csv_is_complete() -> None:
    timezone = ZoneInfo("America/Toronto")
    records = [
        _record("root", "2026-03-08T05:00:00+00:00", 10, role="root"),
        _record("child", "2026-03-08T06:00:00+00:00", 20, parent="root", role="subagent"),
        _record("grandchild", "2026-03-09T04:00:00+00:00", 30, parent="child", role="subagent"),
        _record("orphan", "2026-03-09T05:00:00+00:00", 5, parent="missing", role="subagent"),
        _record("cycle-a", "2026-03-09T06:00:00+00:00", 7, parent="cycle-b", role="subagent"),
    ]
    tasks = {
        "root": LedgerTask("root", "", "root", "Narrative forge"),
        "child": LedgerTask("child", "root", "subagent", "Éditeur"),
        "grandchild": LedgerTask("grandchild", "child", "subagent", ""),
        "orphan": LedgerTask("orphan", "missing", "subagent", ""),
        "cycle-a": LedgerTask("cycle-a", "cycle-b", "subagent", ""),
        "cycle-b": LedgerTask("cycle-b", "cycle-a", "subagent", ""),
    }

    activity = build_agent_activity(records, tasks, timezone)

    assert activity.totals.usage.total_tokens == 72
    assert activity.totals.responses == 5
    assert sum(row.totals.usage.total_tokens for row in activity.daily_rows) == 72
    assert sum(row.totals.usage.total_tokens for row in activity.agent_rows) == 72
    assert sum(row.usage.total_tokens for row in activity.role_totals.values()) == 72
    assert sum(row.usage.total_tokens for row in activity.root_task_totals.values()) == 72
    assert sum(row.totals.usage.total_tokens for row in activity.agent_day_rows) == 72
    by_id = {row.agent_id: row for row in activity.agent_rows}
    assert by_id["grandchild"].root_task_id == "root"
    assert by_id["orphan"].root_task_id == "orphan"
    assert by_id["cycle-a"].root_task_id == "cycle-a"
    assert by_id["child"].label == "Éditeur"
    assert len(activity.agent_day_rows) == 5

    csv_rows = list(csv.DictReader(io.StringIO(agent_activity_csv(activity))))
    assert len(csv_rows) == 5
    assert sum(int(row["total_tokens"]) for row in csv_rows) == 72
    assert any(row["agent_label"] == "Éditeur" for row in csv_rows)

    html = render_agent_activity_section(activity)
    assert "<h3>Daily Summary</h3>" in html
    assert '<details class="agent-activity-agents">' in html
    assert "<h3>Agents</h3>" in html
    assert "<summary>Show 5 of 5 agents by total tokens.</summary>" in html
    assert "<details class=\"agent-activity-agents\" open" not in html
    assert "Export Agent Activity CSV includes every selected agent-day row." in html


def _record(
    task_id: str,
    timestamp: str,
    total_tokens: int,
    *,
    parent: str = "",
    role: str,
) -> UsageRecord:
    return UsageRecord(
        timestamp=datetime.fromisoformat(timestamp),
        usage=TokenUsage(
            input_tokens=total_tokens,
            cached_input_tokens=total_tokens // 4,
            output_tokens=total_tokens // 3,
            reasoning_output_tokens=total_tokens // 6,
            total_tokens=total_tokens,
        ),
        session_id=task_id,
        file_path=Path(f"/{task_id}.jsonl"),
        usage_role=role,  # type: ignore[arg-type]
        project_key="forge",
        project_label="Narrative Forge",
        parent_thread_id=parent,
    )
