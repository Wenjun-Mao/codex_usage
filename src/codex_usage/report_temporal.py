from __future__ import annotations

from codex_usage.charts import render_daily_cost_svg
from codex_usage.report_tables import render_aggregate_table
from codex_usage.report_view import ReportViewModel


def render_temporal_chart(view_model: ReportViewModel, range_name: str) -> str:
    details = render_aggregate_table(
        "Daily Details", view_model.daily_rows, section_id="daily-details"
    )
    if range_name != "all":
        chart = render_daily_cost_svg(view_model.daily_points)
        return _chart_section("Daily Cost Trend", chart, details)

    weekly_chart = render_daily_cost_svg(
        view_model.weekly_points, title="Weekly API-equivalent cost trend"
    )
    monthly_chart = render_daily_cost_svg(
        view_model.monthly_points, title="Monthly API-equivalent cost trend"
    )
    return (
        '<section class="section all-history-cost-trend" data-report-section="daily-cost">'
        "<h2>Cost Trend</h2>"
        '<div class="cost-trend-interaction" role="radiogroup" '
        'aria-label="Cost trend period">'
        '<input class="cost-granularity-input" type="radio" '
        'name="cost-trend-granularity" id="cost-trend-week" value="week" '
        'aria-label="Group cost trend by week" checked>'
        '<input class="cost-granularity-input" type="radio" '
        'name="cost-trend-granularity" id="cost-trend-month" value="month" '
        'aria-label="Group cost trend by month">'
        '<div class="cost-granularity-toolbar">'
        '<span class="cost-granularity-label">Group by</span>'
        '<span class="cost-granularity-options">'
        '<label for="cost-trend-week">Week</label>'
        '<label for="cost-trend-month">Month</label>'
        "</span></div>"
        '<div class="cost-trend-panels">'
        '<div class="cost-trend-panel cost-trend-week-panel">'
        f'<div class="chart-scroll tooltip-chart-scroll">{weekly_chart}</div></div>'
        '<div class="cost-trend-panel cost-trend-month-panel">'
        f'<div class="chart-scroll tooltip-chart-scroll">{monthly_chart}</div></div>'
        "</div></div>"
        f"{details}"
        "</section>"
    )


def _chart_section(title: str, chart_html: str, table_html: str) -> str:
    return (
        '<section class="section" data-report-section="daily-cost">'
        f"<h2>{title}</h2>"
        f'<div class="chart-scroll tooltip-chart-scroll">{chart_html}</div>'
        f"{table_html}"
        "</section>"
    )
