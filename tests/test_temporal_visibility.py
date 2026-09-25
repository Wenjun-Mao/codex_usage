from datetime import UTC, datetime
from pathlib import Path

from codex_usage.aggregation import UsageSummary
from codex_usage.models import TokenUsage
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.reporting import render_html_report
from reporting_html_helpers import breakdown, row


def test_today_and_yesterday_hide_daily_trend_and_details_but_keep_heatmap(
    tmp_path: Path,
) -> None:
    for range_name in ("today", "yesterday"):
        html = _render_range_report(tmp_path, range_name, with_hourly=True)

        assert 'data-report-section="daily-cost"' not in html
        assert "Daily Cost Trend" not in html
        assert "Daily Details" not in html
        assert 'data-report-section="hourly-heatmap"' in html
        assert "Hourly Heatmap" in html
        assert 'aria-label="Usage chart comparison"' in html
        assert "Project Breakdown" in html
        assert "Model Mix" in html


def test_one_date_custom_range_keeps_daily_trend_and_details(tmp_path: Path) -> None:
    html = _render_range_report(tmp_path, "custom")

    assert "Daily Cost Trend" in html
    assert "Daily Details" in html
    assert 'data-report-section="daily-cost"' in html


def _render_range_report(
    tmp_path: Path, range_name: str, *, with_hourly: bool = False
) -> str:
    output = tmp_path / f"{range_name}.html"
    render_html_report(
        output_path=output,
        generated_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
        range_name=range_name,
        total=UsageSummary(
            usage=TokenUsage(total_tokens=10),
            cost=CostBreakdown(total_usd=0.5),
            credits=CreditBreakdown(),
            record_count=1,
        ),
        daily_rows=[row("2026-09-06", "2026-09-06", 10, cost=0.5)],
        hourly_rows=(
            [row("2026-09-06 10:00", "10:00", 10, cost=0.5)]
            if with_hourly
            else []
        ),
        breakdown=breakdown([], []),
        sessions_dirs=[Path("sessions")],
        files_scanned=1,
    )
    return output.read_text(encoding="utf-8")
