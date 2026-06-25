from datetime import UTC, datetime
from pathlib import Path

from codex_usage.aggregation import AggregateRow, UsageSummary
from codex_usage.models import TokenUsage
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.project_transitions import ProjectTransition
from codex_usage.reporting import render_html_report


def test_dashboard_report_contains_fast_tooltip_charts_without_external_assets(tmp_path: Path) -> None:
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
        project_keys=["repo"],
        theme="night",
    )

    html = output.read_text(encoding="utf-8")

    assert "Codex Usage Report" in html
    assert '<html lang="en" data-codex-theme="night">' in html
    assert "--bg: #f7f8fa" in html
    assert "--night-bg: #0d0f12" in html
    assert "body.vscode-dark" in html
    assert "body.vscode-high-contrast" in html
    assert "Projects: repo" in html
    assert "Daily Cost Trend" in html
    assert "Hourly Heatmap" in html
    assert "Project Breakdown" in html
    assert "Model Mix" in html
    assert html.count("<svg") == 0
    assert 'role="img" aria-label="Daily API-equivalent cost trend"' in html
    assert 'role="grid" aria-label="Hourly API-equivalent cost heatmap"' in html
    assert 'class="chart-scroll tooltip-chart-scroll"' in html
    assert "daily-bar-chart" in html
    assert "breakdown-bar-chart" in html
    assert "chart-tooltip-main" in html
    assert '<span class="chart-tooltip-main">2026-04-29</span>' in html
    assert '<span class="chart-tooltip-detail">$1.7500 | 1,100 tokens</span>' in html
    assert '<span class="chart-tooltip-main">demo</span>' in html
    assert '<span class="chart-tooltip-detail">1,100 tokens | $1.7500 | 14.2 credits</span>' in html
    assert '<span class="chart-tooltip-main">gpt-5.5</span>' in html
    assert "<title>2026-04-29:" not in html
    assert "<title>demo:" not in html
    assert "<title>gpt-5.5:" not in html
    assert "Codex Credits" in html
    assert "rates effective at each usage event" in html
    assert "API USD excludes" not in html
    assert "Cost is partial" not in html
    assert "No price data is available" not in html
    assert "<script" not in html
    assert " src=" not in html
    assert " href=" not in html


def test_dashboard_heatmap_uses_themeable_classes(tmp_path: Path) -> None:
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
        project_rows=[],
        model_rows=[],
        sessions_dirs=[Path("sessions")],
        files_scanned=1,
        theme="auto",
    )

    html = output.read_text(encoding="utf-8")

    assert '<html lang="en" data-codex-theme="auto">' in html
    assert "heatmap-grid" in html
    assert 'class="chart-scroll heatmap-chart-scroll"' in html
    assert "--heatmap-cell-size: 20px;" in html
    assert "margin-inline: auto;" in html
    assert "heat-cell heat-" in html
    assert "heatmap-tooltip" in html
    assert "heatmap-tooltip-main" in html
    assert "heatmap-tooltip-detail" in html
    assert 'tabindex="0"' in html
    assert '<span class="heatmap-tooltip-main">2026-04-29 10:00</span>' in html
    assert '<span class="heatmap-tooltip-detail">$0.7500 | 700 tokens</span>' in html
    assert 'aria-label="2026-04-29 10:00: $0.7500, 700 tokens"' in html
    assert "<title>2026-04-29 10:00" not in html
    assert "#edf2f7" not in html
    assert "heatmap-legend" not in html
    assert "More saturated cells mean higher API-equivalent cost." not in html
    assert "Darker cells mean higher API-equivalent cost." not in html
    assert "--heat-0" in html
    assert "--heat-5: #f4b000" not in html
    assert "--heat-5: #d8a72f" not in html


def test_dashboard_report_shows_project_transitions(tmp_path: Path) -> None:
    output = tmp_path / "transitions.html"
    total = UsageSummary(usage=TokenUsage(), cost=CostBreakdown(), credits=CreditBreakdown(), record_count=0)
    effective_from = datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC)
    transition = ProjectTransition(
        source_key="https://github.com/example/signoz-stack",
        source_label="signoz-stack",
        target_key="https://github.com/example/ops-board",
        target_label="ops-board",
        effective_from=effective_from,
        confidence=100,
        evidence=("verified local repository switch",),
        thread_ids=("thread-1",),
    )

    render_html_report(
        output_path=output,
        generated_at=datetime(2026, 5, 23, 22, tzinfo=UTC),
        range_name="all",
        total=total,
        daily_rows=[],
        hourly_rows=[],
        project_rows=[],
        model_rows=[],
        sessions_dirs=[Path("sessions")],
        files_scanned=1,
        project_transitions=[transition.to_dict()],
    )

    html = output.read_text(encoding="utf-8")

    assert "Project Transitions" in html
    assert "signoz-stack" in html
    assert "ops-board" in html
    assert effective_from.isoformat() in html


def test_report_html_mentions_archived_and_retained_missing_files(tmp_path: Path) -> None:
    output = tmp_path / "storage.html"
    total = UsageSummary(
        usage=TokenUsage(input_tokens=30, total_tokens=30),
        cost=CostBreakdown(),
        credits=CreditBreakdown(),
        record_count=2,
    )

    render_html_report(
        output_path=output,
        generated_at=datetime(2026, 5, 27, 12, tzinfo=UTC),
        range_name="all",
        total=total,
        daily_rows=[],
        hourly_rows=[],
        project_rows=[],
        model_rows=[],
        sessions_dirs=[Path("sessions"), Path("archived_sessions")],
        files_scanned=2,
        files_archived=1,
        files_retained_missing=1,
    )

    html = output.read_text(encoding="utf-8")

    assert "Archived files included: 1" in html
    assert "Retained missing files: 1" in html


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
    )

    html = output.read_text(encoding="utf-8")

    assert "No price data is available for 25 tokens" in html


def test_dashboard_report_warns_for_unknown_future_model_without_price_data(tmp_path: Path) -> None:
    output = tmp_path / "future-model.html"
    total = UsageSummary(
        usage=TokenUsage(input_tokens=1_000, cached_input_tokens=100, output_tokens=50, total_tokens=1_050),
        cost=CostBreakdown(unpriced_tokens=1_050),
        credits=CreditBreakdown(unpriced_tokens=1_050),
        record_count=1,
    )

    render_html_report(
        output_path=output,
        generated_at=datetime(2026, 6, 25, 12, tzinfo=UTC),
        range_name="all",
        total=total,
        daily_rows=[_row("2026-06-25", "2026-06-25", 1_050, unpriced=1_050, credit_unpriced=1_050)],
        hourly_rows=[],
        project_rows=[],
        model_rows=[_row("gpt-5.6", "gpt-5.6", 1_050, unpriced=1_050, credit_unpriced=1_050)],
        sessions_dirs=[Path("sessions")],
        files_scanned=1,
    )

    html = output.read_text(encoding="utf-8")

    assert "gpt-5.6" in html
    assert "No price data is available for 1,050 tokens" in html
    assert "API USD excludes 1,050 tokens from models without API USD rates" in html


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
    )

    html = output.read_text(encoding="utf-8")

    assert "No Codex usage was found for this report range." in html
    assert "Projects: All Projects" in html
    assert "Project Transitions" not in html
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
