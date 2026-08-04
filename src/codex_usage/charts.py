from __future__ import annotations

import html

from codex_usage.report_breakdown_view import (
    ModelLegendItem,
    ModelMixPoint,
    ModelSegmentPoint,
    ProjectBreakdownPoint,
    RoleGroupPoint,
)
from codex_usage.report_view import DailyPoint, HourlyCell


def render_daily_cost_svg(points: list[DailyPoint]) -> str:
    title = "Daily API-equivalent cost trend"
    if not points:
        return _empty_svg(title, "No daily usage found for this range.")

    max_cost = max(point.cost_usd for point in points)
    if max_cost <= 0:
        return _empty_svg(title, "No priced daily cost is available for this range.")

    label_step = max(1, round(len(points) / 8))

    chunks = [f'<div class="daily-bar-chart" role="img" aria-label="{_esc(title)}">']
    chunks.append(f'<div class="chart-max-label">${max_cost:.2f} max day</div>')
    chunks.append(f'<div class="daily-bars" style="--bar-count: {len(points)};">')
    for index, point in enumerate(points):
        height_pct = max(1.0, point.cost_usd / max_cost * 100)
        label = (
            point.label if index % label_step == 0 or index == len(points) - 1 else ""
        )
        main_text = point.key
        detail_text = f"${point.cost_usd:.4f} | {_fmt_int(point.total_tokens)} tokens"
        aria_text = f"{main_text}: {detail_text.replace(' | ', ', ')}"
        chunks.append(
            '<span class="daily-bar-slot">'
            f'<span class="chart-bar-hit daily-bar-hit" tabindex="0" aria-label="{_esc(aria_text)}">'
            f'<span class="daily-bar-fill" style="height: {height_pct:.2f}%"></span>'
            f"{_chart_tooltip(main_text, detail_text)}"
            "</span>"
            f'<span class="daily-bar-label">{_esc(label)}</span>'
            "</span>"
        )
    chunks.append("</div></div>")
    return "".join(chunks)


def render_hourly_heatmap_html(cells: list[HourlyCell]) -> str:
    title = "Hourly API-equivalent cost heatmap"
    if not cells:
        return _empty_svg(title, "No hourly usage found for this range.")

    days = sorted({cell.day for cell in cells})
    by_key = {(cell.day, cell.hour): cell for cell in cells}
    max_cost = max(cell.cost_usd for cell in cells)
    if max_cost <= 0:
        return _empty_svg(title, "No priced hourly cost is available for this range.")

    chunks = [
        '<div class="heatmap-grid" role="grid" aria-label="Hourly API-equivalent cost heatmap">'
    ]
    chunks.append('<span class="heatmap-corner" aria-hidden="true"></span>')
    for hour in range(24):
        label = f"{hour:02d}" if hour % 3 == 0 else ""
        chunks.append(
            f'<span class="heatmap-hour" role="columnheader" aria-label="{hour:02d}:00">{label}</span>'
        )

    for day_index, day in enumerate(days):
        chunks.append(
            f'<span class="heatmap-day" role="rowheader">{_esc(_short_day(day))}</span>'
        )
        for hour in range(24):
            cell = by_key.get((day, hour))
            value = cell.cost_usd if cell else 0.0
            heat_class = _heat_class(value / max_cost if max_cost else 0)
            main_text = f"{day} {hour:02d}:00"
            detail_text = (
                f"${value:.4f} | {_fmt_int(cell.total_tokens)} tokens"
                if cell
                else "No usage"
            )
            aria_text = f"{main_text}: {detail_text.replace(' | ', ', ')}"
            chunks.append(
                f'<span class="heatmap-cell heat-cell {heat_class}" role="gridcell" tabindex="0" '
                f'aria-label="{_esc(aria_text)}">'
                '<span class="heatmap-tooltip" aria-hidden="true">'
                f'<span class="heatmap-tooltip-main">{_esc(main_text)}</span>'
                f'<span class="heatmap-tooltip-detail">{_esc(detail_text)}</span>'
                "</span>"
                "</span>"
            )
    chunks.append("</div>")
    return "".join(chunks)


def render_project_breakdown_chart(
    points: list[ProjectBreakdownPoint], legend: list[ModelLegendItem]
) -> str:
    title = "Top projects by total tokens"
    if not points:
        return _empty_svg(title, "No usage found for this range.")

    max_tokens = max(point.total_tokens for point in points) or 1
    chunks = [
        f'<div class="project-breakdown-chart" role="group" aria-label="{_esc(title)}">'
    ]
    for point in points:
        outer_width = point.total_tokens / max_tokens * 100
        role_gap_class = " has-role-gap" if len(point.roles) == 2 else ""
        role_columns = " ".join(f"{role.total_tokens}fr" for role in point.roles)
        role_headings = "".join(_render_role_heading(role) for role in point.roles)
        role_groups = "".join(_render_role_group(point, role) for role in point.roles)
        row_html = (
            '<div class="project-breakdown-row">'
            f'<span class="breakdown-bar-label">{_esc(point.label)}</span>'
            '<div class="project-track">'
            f'<div class="project-role-stack" style="width:{outer_width:.4f}%">'
            f'<div class="project-role-labels{role_gap_class}" '
            f'style="grid-template-columns:{role_columns}">{role_headings}</div>'
            f'<div class="project-role-groups{role_gap_class}" '
            f'style="grid-template-columns:{role_columns}">{role_groups}</div>'
            "</div></div>"
            f'<span class="breakdown-bar-value">{_esc(_breakdown_value(point))}</span>'
            "</div>"
        )
        chunks.append(row_html)
    chunks.append(_render_model_legend(legend))
    chunks.append("</div>")
    return "".join(chunks)


def render_model_mix_chart(points: list[ModelMixPoint]) -> str:
    title = "Model mix by total tokens"
    if not points:
        return _empty_svg(title, "No usage found for this range.")

    max_tokens = max(point.total_tokens for point in points) or 1
    chunks = [f'<div class="model-mix-chart" role="group" aria-label="{_esc(title)}">']
    for point in points:
        width = point.total_tokens / max_tokens * 100
        detail = _model_detail(point)
        aria = f"{point.label}, {detail.replace(' | ', ', ')}"
        chunks.append(
            '<div class="model-mix-row">'
            f'<span class="breakdown-bar-label">{_esc(point.label)}</span>'
            '<div class="model-mix-track">'
            f'<span class="model-mix-fill model-color-slot-{point.color_slot}" '
            f'style="width:{width:.4f}%" tabindex="0" aria-label="{_esc(aria)}">'
            f"{_chart_tooltip(point.label, detail)}"
            "</span></div>"
            f'<span class="breakdown-bar-value">{_esc(_breakdown_value(point))}</span>'
            "</div>"
        )
    chunks.append("</div>")
    return "".join(chunks)


def _render_role_heading(role: RoleGroupPoint) -> str:
    return (
        '<span class="project-role-heading">'
        f'<span class="project-role-heading-label">{_esc(role.label)}</span>'
        f'<span class="project-role-heading-detail">{_fmt_compact(role.total_tokens)} | {role.project_share:.1%}</span>'
        "</span>"
    )


def _render_role_group(point: ProjectBreakdownPoint, role: RoleGroupPoint) -> str:
    role_aria = (
        f"{point.label} {role.label}, {_fmt_int(role.total_tokens)} tokens, "
        f"{role.project_share:.1%} of project"
    )
    segments = []
    for segment in role.segments:
        segment_width = (
            segment.total_tokens / role.total_tokens * 100 if role.total_tokens else 0
        )
        tooltip_title = f"{point.label} · {role.label} · {segment.label}"
        tooltip_detail = _segment_detail(segment)
        segment_aria = f"{point.label}, {role.label}, {segment.label}, {tooltip_detail.replace(' | ', ', ')}"
        segments.append(
            f'<span class="model-segment model-color-slot-{segment.color_slot}" '
            f'style="width:{segment_width:.4f}%" tabindex="0" '
            f'aria-label="{_esc(segment_aria)}">'
            '<span class="chart-tooltip" aria-hidden="true">'
            f"<strong>{_esc(tooltip_title)}</strong><span>{_esc(tooltip_detail)}</span>"
            "</span></span>"
        )
    return (
        f'<div class="project-role-group" role="group" aria-label="{_esc(role_aria)}">'
        + "".join(segments)
        + "</div>"
    )


def _render_model_legend(legend: list[ModelLegendItem]) -> str:
    items = "".join(
        '<span class="model-legend-item">'
        f'<span class="model-swatch" aria-hidden="true"><span class="model-color-slot-{item.color_slot}"></span></span>'
        f"{_esc(item.label)}</span>"
        for item in legend
    )
    return f'<div class="model-legend" aria-label="Model colors">{items}</div>'


def _segment_detail(segment: ModelSegmentPoint) -> str:
    return _detail_text(
        total_tokens=segment.total_tokens,
        project_share=segment.project_share,
        cost_usd=segment.cost_usd,
        total_credits=segment.total_credits,
        unpriced_tokens=segment.unpriced_tokens,
        credit_unpriced_tokens=segment.credit_unpriced_tokens,
    )


def _model_detail(point: ModelMixPoint) -> str:
    return _detail_text(
        total_tokens=point.total_tokens,
        project_share=None,
        cost_usd=point.cost_usd,
        total_credits=point.total_credits,
        unpriced_tokens=point.unpriced_tokens,
        credit_unpriced_tokens=point.credit_unpriced_tokens,
    )


def _breakdown_value(point: ProjectBreakdownPoint | ModelMixPoint) -> str:
    value = f"{_fmt_compact(point.total_tokens)} | ${point.cost_usd:.2f} | {_fmt_credits(point.total_credits)} cr"
    if point.unpriced_tokens:
        value += f" | {_fmt_compact(point.unpriced_tokens)} API excl."
    if point.credit_unpriced_tokens:
        value += f" | {_fmt_compact(point.credit_unpriced_tokens)} no credit"
    return value


def _detail_text(
    *,
    total_tokens: int,
    project_share: float | None,
    cost_usd: float,
    total_credits: float,
    unpriced_tokens: int,
    credit_unpriced_tokens: int,
) -> str:
    detail = f"{_fmt_int(total_tokens)} tokens"
    if project_share is not None:
        detail += f" | {project_share:.1%} of project"
    detail += f" | ${cost_usd:.4f} | {_fmt_credits(total_credits)} credits"
    if unpriced_tokens:
        detail += f" | {_fmt_int(unpriced_tokens)} API-excluded"
    if credit_unpriced_tokens:
        detail += f" | {_fmt_int(credit_unpriced_tokens)} without credit rates"
    return detail


def _empty_svg(title: str, message: str) -> str:
    width = 920
    height = 150
    return (
        _svg_open(width, height, title)
        + f'<text class="empty-chart" x="24" y="78">{_esc(message)}</text>'
        + "</svg>"
    )


def _chart_tooltip(main_text: str, detail_text: str) -> str:
    return (
        '<span class="chart-tooltip" aria-hidden="true">'
        f'<span class="chart-tooltip-main">{_esc(main_text)}</span>'
        f'<span class="chart-tooltip-detail">{_esc(detail_text)}</span>'
        "</span>"
    )


def _svg_open(width: int, height: int, title: str) -> str:
    return (
        f'<svg class="chart-svg" role="img" aria-label="{_esc(title)}" '
        f'viewBox="0 0 {width} {height}" width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
        f"<title>{_esc(title)}</title>"
    )


def _heat_class(ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    if ratio == 0:
        return "heat-0"
    bucket = min(5, max(1, int(ratio * 5 + 0.999)))
    return f"heat-{bucket}"


def _short_day(value: str) -> str:
    parts = value.split("-")
    if len(parts) == 3:
        return f"{parts[1]}/{parts[2]}"
    return value


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 1] + "..."


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


def _fmt_int(value: int) -> str:
    return f"{value:,}"


def _fmt_compact(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def _fmt_credits(value: float) -> str:
    if value >= 1_000:
        return f"{value:,.0f}"
    return f"{value:,.1f}"
