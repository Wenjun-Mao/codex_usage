from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from codex_usage.aggregation import AggregateRow, UsageSummary
from codex_usage.report_breakdown import ReportBreakdown
from codex_usage.report_breakdown_view import (
    BreakdownView,
    ModelLegendItem,
    ModelMixPoint,
    ProjectBreakdownPoint,
    build_breakdown_view,
)


@dataclass(frozen=True)
class KpiCard:
    label: str
    value: str
    detail: str


@dataclass(frozen=True)
class DailyPoint:
    key: str
    label: str
    total_tokens: int
    cost_usd: float
    unpriced_tokens: int
    tooltip_label: str = ""
    granularity: str = "day"


@dataclass(frozen=True)
class HourlyCell:
    day: str
    hour: int
    total_tokens: int
    cost_usd: float
    unpriced_tokens: int


@dataclass(frozen=True)
class ReportViewModel:
    generated_at: datetime
    range_name: str
    sessions_dirs: list[Path]
    files_scanned: int
    files_archived: int
    files_retained_missing: int
    storage_roots: tuple[str, ...]
    total: UsageSummary
    kpis: list[KpiCard]
    daily_points: list[DailyPoint]
    temporal_chart_title: str
    temporal_granularity: str
    hourly_cells: list[HourlyCell]
    breakdown_view: BreakdownView
    model_legend: list[ModelLegendItem]
    project_points: list[ProjectBreakdownPoint]
    project_detail_points: tuple[ProjectBreakdownPoint, ...]
    model_points: list[ModelMixPoint]
    daily_rows: list[AggregateRow]
    hourly_rows: list[AggregateRow]
    project_rows: list[AggregateRow]
    model_rows: list[AggregateRow]

    @property
    def has_usage(self) -> bool:
        return self.total.usage.total_tokens > 0

    @property
    def has_partial_cost(self) -> bool:
        return self.total.cost.unpriced_tokens > 0

    @property
    def has_codex_credit_estimates(self) -> bool:
        return self.total.credits.total_credits > 0

    @property
    def no_price_data_tokens(self) -> int:
        return sum(
            row.usage.total_tokens
            for row in self.model_rows
            if row.cost.unpriced_tokens > 0 and row.credits.unpriced_tokens > 0
        )


def build_report_view_model(
    *,
    generated_at: datetime,
    range_name: str,
    total: UsageSummary,
    daily_rows: list[AggregateRow],
    hourly_rows: list[AggregateRow],
    breakdown: ReportBreakdown,
    sessions_dirs: list[Path],
    files_scanned: int,
    files_archived: int = 0,
    files_retained_missing: int = 0,
    storage_roots: list[str] | tuple[str, ...] | None = None,
) -> ReportViewModel:
    breakdown_view = build_breakdown_view(breakdown)
    daily_points, temporal_granularity = _build_temporal_points(
        daily_rows, range_name
    )
    return ReportViewModel(
        generated_at=generated_at,
        range_name=range_name,
        sessions_dirs=sessions_dirs,
        files_scanned=files_scanned,
        files_archived=files_archived,
        files_retained_missing=files_retained_missing,
        storage_roots=tuple(storage_roots or [str(path) for path in sessions_dirs]),
        total=total,
        kpis=_build_kpis(total),
        daily_points=daily_points,
        temporal_chart_title=_temporal_chart_title(temporal_granularity),
        temporal_granularity=temporal_granularity,
        hourly_cells=[cell for row in hourly_rows if (cell := _hourly_cell(row)) is not None],
        breakdown_view=breakdown_view,
        model_legend=list(breakdown_view.model_legend),
        project_points=list(breakdown_view.project_points[:12]),
        project_detail_points=breakdown_view.project_points,
        model_points=list(breakdown_view.model_points),
        daily_rows=daily_rows,
        hourly_rows=hourly_rows,
        project_rows=list(breakdown.project_rows),
        model_rows=list(breakdown.model_rows),
    )


def _build_kpis(total: UsageSummary) -> list[KpiCard]:
    cache_share = total.usage.cached_input_tokens / total.usage.input_tokens if total.usage.input_tokens else 0
    priced_tokens = max(0, total.usage.total_tokens - total.cost.unpriced_tokens)
    priced_share = priced_tokens / total.usage.total_tokens if total.usage.total_tokens else 0
    credit_priced_tokens = max(0, total.usage.total_tokens - total.credits.unpriced_tokens)
    credit_priced_share = credit_priced_tokens / total.usage.total_tokens if total.usage.total_tokens else 0
    credit_detail = f"{credit_priced_share:.0%} of tokens credit-priced"
    api_excluded_detail = "models without USD API rates"
    if total.cost.unpriced_tokens and total.credits.unpriced_tokens == 0:
        api_excluded_detail = "covered by Codex credit rates"
    elif total.credits.unpriced_tokens:
        api_excluded_detail = f"{_fmt_int(total.credits.unpriced_tokens)} without credit rates"
    return [
        KpiCard("Total Tokens", _fmt_int(total.usage.total_tokens), f"{_fmt_int(total.record_count)} usage events"),
        KpiCard("API-Equivalent Cost", f"${total.cost.total_usd:,.2f}", f"{priced_share:.0%} of tokens priced"),
        KpiCard("Codex Credits", _fmt_credits(total.credits.total_credits), credit_detail),
        KpiCard("Cache Hit Share", f"{cache_share:.1%}", f"{_fmt_int(total.usage.cached_input_tokens)} cached input"),
        KpiCard("API-Excluded Tokens", _fmt_int(total.cost.unpriced_tokens), api_excluded_detail),
    ]


def _daily_point(row: AggregateRow) -> DailyPoint:
    return DailyPoint(
        key=row.key,
        label=_short_day_label(row.key),
        total_tokens=row.usage.total_tokens,
        cost_usd=row.cost.total_usd,
        unpriced_tokens=row.cost.unpriced_tokens,
        tooltip_label=row.key,
    )


def _build_temporal_points(
    daily_rows: list[AggregateRow], range_name: str
) -> tuple[list[DailyPoint], str]:
    """Keep exact daily rows for details while reducing an unbounded chart to readable bins."""
    daily_points = [_daily_point(row) for row in daily_rows]
    if range_name != "all" or not daily_points:
        return daily_points, "day"

    dated_points = [(_parse_day(point.key), point) for point in daily_points]
    if any(day is None for day, _ in dated_points):
        # The day aggregate contract normally makes this unreachable. Retaining the
        # exact points is safer than silently assigning a malformed key to a period.
        return daily_points, "day"

    points_by_day = [(day, point) for day, point in dated_points if day is not None]
    first_day = min(day for day, _ in points_by_day)
    last_day = max(day for day, _ in points_by_day)
    if (last_day - first_day).days < 31:
        return daily_points, "day"
    week_count = (last_day - first_day).days // 7 + 1
    granularity = "week" if week_count <= 26 else "month"
    return _aggregate_temporal_points(points_by_day, granularity), granularity


def _aggregate_temporal_points(
    points_by_day: list[tuple[date, DailyPoint]], granularity: str
) -> list[DailyPoint]:
    buckets: dict[date, list[DailyPoint]] = {}
    for day, point in points_by_day:
        bucket = (
            day - timedelta(days=day.weekday())
            if granularity == "week"
            else day.replace(day=1)
        )
        buckets.setdefault(bucket, []).append(point)

    points: list[DailyPoint] = []
    for bucket, values in sorted(buckets.items()):
        if granularity == "week":
            period_end = bucket + timedelta(days=6)
            key = f"{bucket.isoformat()} to {period_end.isoformat()}"
            label = f"{_month_abbreviation(bucket.month)} {bucket.day}"
            tooltip_label = f"Week of {bucket.isoformat()}"
        else:
            key = bucket.strftime("%Y-%m")
            label = f"{_month_abbreviation(bucket.month)} {bucket.year}"
            tooltip_label = bucket.strftime("%B %Y")
        points.append(
            DailyPoint(
                key=key,
                label=label,
                total_tokens=sum(point.total_tokens for point in values),
                cost_usd=sum(point.cost_usd for point in values),
                unpriced_tokens=sum(point.unpriced_tokens for point in values),
                tooltip_label=tooltip_label,
                granularity=granularity,
            )
        )
    return points


def _parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _temporal_chart_title(granularity: str) -> str:
    return {
        "day": "Daily Cost Trend",
        "week": "Weekly Cost Trend",
        "month": "Monthly Cost Trend",
    }[granularity]


def _month_abbreviation(month: int) -> str:
    return (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )[month - 1]


def _hourly_cell(row: AggregateRow) -> HourlyCell | None:
    try:
        day, hour_text = row.key.split(" ", 1)
        hour = int(hour_text.split(":", 1)[0])
    except (ValueError, IndexError):
        return None
    if hour < 0 or hour > 23:
        return None
    return HourlyCell(
        day=day,
        hour=hour,
        total_tokens=row.usage.total_tokens,
        cost_usd=row.cost.total_usd,
        unpriced_tokens=row.cost.unpriced_tokens,
    )


def _short_day_label(value: str) -> str:
    parts = value.split("-")
    if len(parts) == 3:
        return f"{parts[1]}/{parts[2]}"
    return value


def _fmt_int(value: int) -> str:
    return f"{value:,}"


def _fmt_credits(value: float) -> str:
    if value >= 1_000:
        return f"{value:,.0f}"
    return f"{value:,.1f}"
