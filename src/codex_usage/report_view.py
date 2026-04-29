from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from codex_usage.aggregation import AggregateRow, UsageSummary


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


@dataclass(frozen=True)
class HourlyCell:
    day: str
    hour: int
    total_tokens: int
    cost_usd: float
    unpriced_tokens: int


@dataclass(frozen=True)
class BreakdownPoint:
    key: str
    label: str
    total_tokens: int
    cost_usd: float
    unpriced_tokens: int
    record_count: int


@dataclass(frozen=True)
class ReportViewModel:
    generated_at: datetime
    range_name: str
    sessions_dirs: list[Path]
    files_scanned: int
    total: UsageSummary
    kpis: list[KpiCard]
    daily_points: list[DailyPoint]
    hourly_cells: list[HourlyCell]
    project_points: list[BreakdownPoint]
    model_points: list[BreakdownPoint]
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


def build_report_view_model(
    *,
    generated_at: datetime,
    range_name: str,
    total: UsageSummary,
    daily_rows: list[AggregateRow],
    hourly_rows: list[AggregateRow],
    project_rows: list[AggregateRow],
    model_rows: list[AggregateRow],
    sessions_dirs: list[Path],
    files_scanned: int,
) -> ReportViewModel:
    return ReportViewModel(
        generated_at=generated_at,
        range_name=range_name,
        sessions_dirs=sessions_dirs,
        files_scanned=files_scanned,
        total=total,
        kpis=_build_kpis(total),
        daily_points=[_daily_point(row) for row in daily_rows],
        hourly_cells=[cell for row in hourly_rows if (cell := _hourly_cell(row)) is not None],
        project_points=[_breakdown_point(row) for row in project_rows[:12]],
        model_points=[_breakdown_point(row) for row in model_rows],
        daily_rows=daily_rows,
        hourly_rows=hourly_rows,
        project_rows=project_rows,
        model_rows=model_rows,
    )


def _build_kpis(total: UsageSummary) -> list[KpiCard]:
    cache_share = total.usage.cached_input_tokens / total.usage.input_tokens if total.usage.input_tokens else 0
    priced_tokens = max(0, total.usage.total_tokens - total.cost.unpriced_tokens)
    priced_share = priced_tokens / total.usage.total_tokens if total.usage.total_tokens else 0
    return [
        KpiCard("Total Tokens", _fmt_int(total.usage.total_tokens), f"{_fmt_int(total.record_count)} usage events"),
        KpiCard("API-Equivalent Cost", f"${total.cost.total_usd:,.2f}", f"{priced_share:.0%} of tokens priced"),
        KpiCard("Cache Hit Share", f"{cache_share:.1%}", f"{_fmt_int(total.usage.cached_input_tokens)} cached input"),
        KpiCard("Unpriced Tokens", _fmt_int(total.cost.unpriced_tokens), "models without USD API rates"),
    ]


def _daily_point(row: AggregateRow) -> DailyPoint:
    return DailyPoint(
        key=row.key,
        label=_short_day_label(row.key),
        total_tokens=row.usage.total_tokens,
        cost_usd=row.cost.total_usd,
        unpriced_tokens=row.cost.unpriced_tokens,
    )


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


def _breakdown_point(row: AggregateRow) -> BreakdownPoint:
    return BreakdownPoint(
        key=row.key,
        label=row.label,
        total_tokens=row.usage.total_tokens,
        cost_usd=row.cost.total_usd,
        unpriced_tokens=row.cost.unpriced_tokens,
        record_count=row.record_count,
    )


def _short_day_label(value: str) -> str:
    parts = value.split("-")
    if len(parts) == 3:
        return f"{parts[1]}/{parts[2]}"
    return value


def _fmt_int(value: int) -> str:
    return f"{value:,}"
