from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import pytest

from codex_usage.aggregation import aggregate_records
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.report_breakdown import build_report_breakdown
from codex_usage.report_breakdown_view import build_breakdown_view
from codex_usage.report_tables import (
    render_aggregate_table,
    render_project_details_table,
)


class TableCells(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.rows = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append(0)
        elif tag in {"td", "th"}:
            self.rows[-1] += 1


def records():
    return [
        UsageRecord(
            timestamp=datetime(2026, 10, 4, 12, tzinfo=UTC),
            usage=TokenUsage(input_tokens=100, output_tokens=10, total_tokens=110),
            session_id="test-task",
            file_path=Path("/synthetic/sessions/task.jsonl"),
            usage_role="root",
            model="gpt-6-sol",
            cwd="/synthetic/project",
        )
    ]


@pytest.mark.parametrize("period", ["Daily", "Hourly"])
def test_period_details_omit_share_and_keep_headers_aligned(period):
    rows = aggregate_records(records(), "model", UTC)
    markup = render_aggregate_table(
        f"{period} Details", rows, section_id=f"{period.lower()}-details"
    )
    assert TableCells(markup).rows == [10, 10]
    assert "Share" not in markup and "bar-wrap" not in markup
    assert "110</td>" in markup and "API Cost</th>" in markup


def test_project_details_omit_share_and_keep_role_accounting():
    points = build_breakdown_view(build_report_breakdown(records())).project_points
    markup = render_project_details_table(
        "Project Details", points, section_id="project-details"
    )
    assert TableCells(markup).rows == [12, 12]
    assert "Share" not in markup and "bar-wrap" not in markup
    assert "Root Tokens</th>" in markup and "Subagent Tokens</th>" in markup
    assert "110</td>" in markup and "API Cost</th>" in markup
