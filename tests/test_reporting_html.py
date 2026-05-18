from datetime import UTC, datetime
from pathlib import Path

from codex_usage.aggregation import AggregateRow, UsageSummary
from codex_usage.models import TokenUsage
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.reporting import render_html_report


def test_dashboard_report_contains_inline_svg_sections_without_external_assets(tmp_path: Path) -> None:
    output = tmp_path / "report.html"
    total = UsageSummary(
        usage=TokenUsage(input_tokens=1_000, cached_input_tokens=500, output_tokens=100, total_tokens=1_100),
        cost=CostBreakdown(total_usd=1.75),
        credits=CreditBreakdown(total_credits=14.25),
        record_count=4,
    )

    render_html_report(
        output_path=output,
        generated_at=datetime(2026, 4, 29, 12, tzinfo=UTC),
        range_name="all",
        total=total,
        daily_rows=[_row("2026-04-29", "2026-04-29", 1_100, cost=1.75, credits=14.25)],
        hourly_rows=[_row("2026-04-29 10:00", "2026-04-29 10:00", 700, cost=0.75, credits=9.0)],
        project_rows=[_row("repo", "demo", 1_100, cost=1.75, credits=14.25)],
        model_rows=[
            _row("gpt-5.5", "gpt-5.5", 1_075, cost=1.25, credits=12.0),
            _row("gpt-5.3-codex", "gpt-5.3-codex", 25, cost=0.5, credits=2.25),
        ],
        sessions_dirs=[Path("sessions")],
        files_scanned=1,
        subscription_usd=20.0,
        project_keys=["repo"],
    )

    html = output.read_text(encoding="utf-8")

    assert "Codex Usage Report" in html
    assert "Projects: repo" in html
    assert "Daily Cost Trend" in html
    assert "Hourly Heatmap" in html
    assert "Project Breakdown" in html
    assert "Model Mix" in html
    assert html.count("<svg") == 4
    assert 'aria-label="Daily API-equivalent cost trend"' in html
    assert "Codex Credits" in html
    assert "rates effective at each usage event" in html
    assert "API USD excludes" not in html
    assert "Cost is partial" not in html
    assert "No price data is available" not in html
    assert "<script" not in html
    assert " src=" not in html
    assert " href=" not in html


def test_dashboard_report_warns_when_model_has_no_price_data(tmp_path: Path) -> None:
    output = tmp_path / "unknown.html"
    total = UsageSummary(
        usage=TokenUsage(input_tokens=25, total_tokens=25),
        cost=CostBreakdown(unpriced_tokens=25),
        credits=CreditBreakdown(unpriced_tokens=25),
        record_count=1,
    )

    render_html_report(
        output_path=output,
        generated_at=datetime(2026, 4, 29, 12, tzinfo=UTC),
        range_name="all",
        total=total,
        daily_rows=[_row("2026-04-29", "2026-04-29", 25, unpriced=25, credit_unpriced=25)],
        hourly_rows=[],
        project_rows=[],
        model_rows=[_row("unknown", "unknown", 25, unpriced=25, credit_unpriced=25)],
        sessions_dirs=[Path("sessions")],
        files_scanned=1,
        subscription_usd=None,
    )

    html = output.read_text(encoding="utf-8")

    assert "No price data is available for 25 tokens" in html


def test_dashboard_report_has_empty_states(tmp_path: Path) -> None:
    output = tmp_path / "empty.html"
    total = UsageSummary(usage=TokenUsage(), cost=CostBreakdown(), credits=CreditBreakdown(), record_count=0)

    render_html_report(
        output_path=output,
        generated_at=datetime(2026, 4, 29, 12, tzinfo=UTC),
        range_name="today",
        total=total,
        daily_rows=[],
        hourly_rows=[],
        project_rows=[],
        model_rows=[],
        sessions_dirs=[Path("sessions")],
        files_scanned=0,
        subscription_usd=None,
    )

    html = output.read_text(encoding="utf-8")

    assert "No Codex usage was found for this report range." in html
    assert "Projects: All Projects" in html
    assert "No daily usage found for this range." in html
    assert html.count("<svg") == 4


def _row(
    key: str,
    label: str,
    total: int,
    cost: float = 0.0,
    credits: float = 0.0,
    unpriced: int = 0,
    credit_unpriced: int = 0,
) -> AggregateRow:
    return AggregateRow(
        key=key,
        label=label,
        usage=TokenUsage(input_tokens=total, cached_input_tokens=total // 2, output_tokens=10, total_tokens=total),
        cost=CostBreakdown(total_usd=cost, unpriced_tokens=unpriced),
        credits=CreditBreakdown(total_credits=credits, unpriced_tokens=credit_unpriced),
        record_count=1,
    )
