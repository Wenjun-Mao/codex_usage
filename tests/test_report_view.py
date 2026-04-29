from datetime import UTC, datetime
from pathlib import Path

from codex_usage.aggregation import AggregateRow, UsageSummary
from codex_usage.models import TokenUsage
from codex_usage.pricing import CostBreakdown
from codex_usage.report_view import build_report_view_model


def test_report_view_model_prepares_dashboard_data() -> None:
    total = UsageSummary(
        usage=TokenUsage(input_tokens=1_000, cached_input_tokens=250, output_tokens=100, total_tokens=1_100),
        cost=CostBreakdown(total_usd=1.25, unpriced_tokens=50),
        record_count=3,
    )
    daily_rows = [_row("2026-04-29", "2026-04-29", 1_100, cost=1.25, unpriced=50)]
    hourly_rows = [_row("2026-04-29 10:00", "2026-04-29 10:00", 600, cost=0.75)]
    project_rows = [_row("repo", "demo", 1_100, cost=1.25)]
    model_rows = [_row("gpt-5.5", "gpt-5.5", 1_050, cost=1.25), _row("unknown", "unknown", 50, unpriced=50)]

    view_model = build_report_view_model(
        generated_at=datetime(2026, 4, 29, tzinfo=UTC),
        range_name="all",
        total=total,
        daily_rows=daily_rows,
        hourly_rows=hourly_rows,
        project_rows=project_rows,
        model_rows=model_rows,
        sessions_dirs=[Path("sessions")],
        files_scanned=1,
    )

    assert view_model.kpis[2].value == "25.0%"
    assert view_model.has_partial_cost is True
    assert view_model.daily_points[0].label == "04/29"
    assert view_model.hourly_cells[0].day == "2026-04-29"
    assert view_model.hourly_cells[0].hour == 10
    assert [point.label for point in view_model.model_points] == ["gpt-5.5", "unknown"]


def _row(key: str, label: str, total: int, cost: float = 0.0, unpriced: int = 0) -> AggregateRow:
    return AggregateRow(
        key=key,
        label=label,
        usage=TokenUsage(input_tokens=total, total_tokens=total),
        cost=CostBreakdown(total_usd=cost, unpriced_tokens=unpriced),
        record_count=1,
    )
