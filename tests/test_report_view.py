from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from codex_usage.aggregation import AggregateRow, UsageSummary, aggregate_records
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.report_breakdown import OTHER_MODEL_KEY, build_report_breakdown
from codex_usage.report_view import build_report_view_model


def test_report_view_model_prepares_role_and_model_presentation_points() -> None:
    records = [
        _record("demo", "demo", "root", "gpt-5.6-sol", total=1_000),
        _record("demo", "demo", "subagent", "gpt-5.6-terra", total=100),
        _record("other", "other", "root", "gpt-5.6-luna", total=10),
        _record("other", "other", "root", "gpt-6-astra", total=5),
    ]

    view_model = _view_model(records)

    assert [item.label for item in view_model.model_legend] == [
        "gpt-6-astra",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ]
    assert [item.color_slot for item in view_model.model_legend] == [0, 1, 2, 3]

    project = view_model.project_points[0]
    assert project.label == "demo"
    assert project.root_tokens == 1_000
    assert project.subagent_tokens == 100
    assert [(group.role, group.label) for group in project.roles] == [
        ("root", "Root tasks"),
        ("subagent", "Subagents"),
    ]
    assert project.roles[0].project_share == pytest.approx(1_000 / 1_100)
    assert project.roles[0].cost_usd > 0
    assert project.roles[0].project_cost_share > 0
    assert project.roles[1].segments[0].project_share == pytest.approx(100 / 1_100)
    assert view_model.project_detail_points == view_model.breakdown_view.project_points


def test_report_view_model_keeps_all_project_details_but_limits_chart_to_twelve() -> (
    None
):
    records = [
        _record(
            f"project-{number:02d}",
            f"Project {number:02d}",
            "root",
            "gpt-5.6-sol",
            total=100 - number,
        )
        for number in range(13)
    ]

    view_model = _view_model(records)

    assert len(view_model.project_points) == 12
    assert len(view_model.project_detail_points) == 13
    assert view_model.project_points == list(view_model.project_detail_points[:12])


def test_report_view_model_uses_project_key_for_tied_top_twelve_membership() -> None:
    records = [
        _record(
            f"project-{number:02d}",
            f"Project {number:02d}",
            "root",
            "gpt-5.6-sol",
            total=100,
        )
        for number in range(13)
    ]

    view_model = _view_model(records)
    reversed_view_model = _view_model(list(reversed(records)))

    expected_keys = [f"project-{number:02d}" for number in range(12)]
    assert [point.key for point in view_model.project_points] == expected_keys
    assert [point.key for point in reversed_view_model.project_points] == expected_keys
    assert [point.key for point in view_model.project_detail_points] == [
        *expected_keys,
        "project-12",
    ]


def test_report_view_model_reserves_other_model_color_slot_seven() -> None:
    records = [
        _record("demo", "demo", "root", f"model-{number}", total=100 - number)
        for number in range(8)
    ]

    view_model = _view_model(records)

    assert [item.color_slot for item in view_model.model_legend[:-1]] == list(range(7))
    assert view_model.model_legend[-1].key == OTHER_MODEL_KEY
    assert view_model.model_legend[-1].color_slot == 7
    assert view_model.model_points[-1].key == OTHER_MODEL_KEY
    assert view_model.model_points[-1].color_slot == 7


def test_all_range_builds_monday_week_buckets_and_preserves_partial_periods() -> None:
    view_model = _view_model_with_daily_rows(
        [
            _daily_row("2025-12-28", total=100, cost=1.0),
            _daily_row("2025-12-29", total=50, cost=0.5),
            _daily_row("2026-01-11", total=25, cost=0.25),
        ]
    )

    assert [
        (point.key, point.total_tokens, point.cost_usd)
        for point in view_model.weekly_points
    ] == [
        ("2025-12-22 to 2025-12-28", 100, 1.0),
        ("2025-12-29 to 2026-01-04", 50, 0.5),
        ("2026-01-05 to 2026-01-11", 25, 0.25),
    ]
    assert [point.tooltip_label for point in view_model.weekly_points] == [
        "Dec 22\u201328, 2025",
        "Dec 29, 2025\u2013Jan 4, 2026",
        "Jan 5\u201311, 2026",
    ]
    assert [row.key for row in view_model.daily_rows] == [
        "2025-12-28",
        "2025-12-29",
        "2026-01-11",
    ]


def test_all_range_builds_calendar_months_across_year_boundary() -> None:
    view_model = _view_model_with_daily_rows(
        [
            _daily_row("2025-12-31", total=100, cost=1.0),
            _daily_row("2026-01-01", total=300, cost=3.0),
            _daily_row("2026-01-20", total=25, cost=0.25),
        ]
    )

    assert [
        (point.key, point.label, point.tooltip_label, point.total_tokens, point.cost_usd)
        for point in view_model.monthly_points
    ] == [
        ("2025-12", "Dec 2025", "Dec 1\u201331, 2025", 100, 1.0),
        ("2026-01", "Jan 2026", "Jan 1\u201331, 2026", 325, 3.25),
    ]


def test_all_range_week_and_month_views_conserve_daily_values() -> None:
    view_model = _view_model_with_daily_rows(
        [
            _daily_row("2026-01-01", total=100, cost=0.1, unpriced=7),
            _daily_row("2026-01-30", total=50, cost=0.2, unpriced=3),
            _daily_row("2026-02-02", total=25, cost=0.3, unpriced=2),
        ]
    )

    for points in (view_model.weekly_points, view_model.monthly_points):
        assert sum(point.total_tokens for point in points) == 175
        assert sum(point.cost_usd for point in points) == pytest.approx(0.6)
        assert sum(point.unpriced_tokens for point in points) == 12


def test_shorter_range_keeps_daily_chart_and_has_no_period_aggregates() -> None:
    view_model = _view_model_with_daily_rows(
        [
            _daily_row("2026-01-01", total=100, cost=1.0),
            _daily_row("2026-01-30", total=50, cost=0.5),
        ],
        range_name="30d",
    )

    assert [point.key for point in view_model.daily_points] == ["2026-01-01", "2026-01-30"]
    assert view_model.weekly_points == []
    assert view_model.monthly_points == []


def test_local_timezone_daily_rows_drive_week_boundaries() -> None:
    timezone = ZoneInfo("America/Toronto")
    records = [
        _record(
            "demo",
            "demo",
            "root",
            "gpt-5.6-sol",
            total=100,
            timestamp=datetime(2026, 1, 5, 4, 30, tzinfo=UTC),
        ),
        _record(
            "demo",
            "demo",
            "root",
            "gpt-5.6-sol",
            total=200,
            timestamp=datetime(2026, 1, 5, 5, 30, tzinfo=UTC),
        ),
    ]
    daily_rows = aggregate_records(records, "day", timezone)
    view_model = _view_model_with_daily_rows(daily_rows)

    assert [row.key for row in daily_rows] == ["2026-01-04", "2026-01-05"]
    assert [point.key for point in view_model.weekly_points] == [
        "2025-12-29 to 2026-01-04",
        "2026-01-05 to 2026-01-11",
    ]


def _view_model(records: list[UsageRecord]):
    total = UsageSummary(
        usage=TokenUsage(
            total_tokens=sum(record.usage.total_tokens for record in records)
        ),
        cost=CostBreakdown(),
        credits=CreditBreakdown(),
        record_count=len(records),
    )
    return build_report_view_model(
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        range_name="all",
        total=total,
        daily_rows=[],
        hourly_rows=[],
        breakdown=build_report_breakdown(records),
        sessions_dirs=[Path("sessions")],
        files_scanned=1,
    )


def _view_model_with_daily_rows(
    daily_rows: list[AggregateRow], *, range_name: str = "all"
):
    return build_report_view_model(
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        range_name=range_name,
        total=UsageSummary(
            usage=TokenUsage(
                total_tokens=sum(row.usage.total_tokens for row in daily_rows)
            ),
            cost=CostBreakdown(total_usd=sum(row.cost.total_usd for row in daily_rows)),
            credits=CreditBreakdown(),
            record_count=sum(row.record_count for row in daily_rows),
        ),
        daily_rows=daily_rows,
        hourly_rows=[],
        breakdown=build_report_breakdown([]),
        sessions_dirs=[Path("sessions")],
        files_scanned=1,
    )


def _daily_row(
    key: str, *, total: int, cost: float, unpriced: int = 0
) -> AggregateRow:
    return AggregateRow(
        key=key,
        label=key,
        usage=TokenUsage(total_tokens=total),
        cost=CostBreakdown(total_usd=cost, unpriced_tokens=unpriced),
        credits=CreditBreakdown(),
        record_count=1,
    )


def _record(
    project_key: str,
    project_label: str,
    role: str,
    model: str,
    *,
    total: int,
    timestamp: datetime | None = None,
) -> UsageRecord:
    return UsageRecord(
        timestamp=timestamp or datetime(2026, 8, 1, tzinfo=UTC),
        usage=TokenUsage(input_tokens=total, total_tokens=total),
        session_id=f"{project_key}-{role}-{model}",
        file_path=Path("/tmp/session.jsonl"),
        usage_role=role,  # type: ignore[arg-type]
        model=model,
        project_key=project_key,
        project_label=project_label,
    )
