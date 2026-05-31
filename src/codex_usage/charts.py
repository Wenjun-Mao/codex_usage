from __future__ import annotations

import html

from codex_usage.report_view import BreakdownPoint, DailyPoint, HourlyCell


def render_daily_cost_svg(points: list[DailyPoint]) -> str:
    title = "Daily API-equivalent cost trend"
    if not points:
        return _empty_svg(title, "No daily usage found for this range.")

    max_cost = max(point.cost_usd for point in points)
    if max_cost <= 0:
        return _empty_svg(title, "No priced daily cost is available for this range.")

    width = 920
    height = 270
    left = 54
    right = 18
    top = 26
    bottom = 44
    inner_width = width - left - right
    inner_height = height - top - bottom
    gap = 3
    bar_width = max(4, (inner_width - gap * max(0, len(points) - 1)) / len(points))
    label_step = max(1, round(len(points) / 8))

    chunks = [_svg_open(width, height, title)]
    chunks.append(f'<line class="axis-line" x1="{left}" y1="{top + inner_height}" x2="{width - right}" y2="{top + inner_height}" />')
    for index, point in enumerate(points):
        bar_height = max(1, point.cost_usd / max_cost * inner_height)
        x = left + index * (bar_width + gap)
        y = top + inner_height - bar_height
        chunks.append(
            f'<rect class="cost-bar" x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" '
            f'height="{bar_height:.2f}" rx="2"><title>{_esc(point.key)}: ${point.cost_usd:.4f}, '
            f'{_fmt_int(point.total_tokens)} tokens</title></rect>'
        )
        if index % label_step == 0 or index == len(points) - 1:
            chunks.append(
                f'<text class="axis-label" x="{x + bar_width / 2:.2f}" y="{height - 18}" text-anchor="middle">'
                f'{_esc(point.label)}</text>'
            )
    chunks.append(f'<text class="axis-label" x="{left}" y="18">${max_cost:.2f} max day</text>')
    chunks.append("</svg>")
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

    chunks = ['<div class="heatmap-grid" role="grid" aria-label="Hourly API-equivalent cost heatmap">']
    chunks.append('<span class="heatmap-corner" aria-hidden="true"></span>')
    for hour in range(24):
        label = f"{hour:02d}" if hour % 3 == 0 else ""
        chunks.append(f'<span class="heatmap-hour" role="columnheader" aria-label="{hour:02d}:00">{label}</span>')

    for day_index, day in enumerate(days):
        chunks.append(f'<span class="heatmap-day" role="rowheader">{_esc(_short_day(day))}</span>')
        for hour in range(24):
            cell = by_key.get((day, hour))
            value = cell.cost_usd if cell else 0.0
            heat_class = _heat_class(value / max_cost if max_cost else 0)
            title_text = (
                f"{day} {hour:02d}:00: ${value:.4f}, {_fmt_int(cell.total_tokens)} tokens"
                if cell
                else f"{day} {hour:02d}:00: no usage"
            )
            chunks.append(
                f'<span class="heatmap-cell heat-cell {heat_class}" role="gridcell" tabindex="0" '
                f'aria-label="{_esc(title_text)}">'
                f'<span class="heatmap-tooltip" aria-hidden="true">{_esc(title_text)}</span>'
                "</span>"
            )
    chunks.append("</div>")
    chunks.append('<p class="heatmap-legend muted">Darker cells mean higher API-equivalent cost.</p>')
    return "".join(chunks)


def render_project_breakdown_svg(points: list[BreakdownPoint]) -> str:
    return _render_horizontal_bars("Top projects by total tokens", points, value_kind="tokens")


def render_model_mix_svg(points: list[BreakdownPoint]) -> str:
    return _render_horizontal_bars("Model mix by total tokens", points, value_kind="tokens")


def _render_horizontal_bars(title: str, points: list[BreakdownPoint], *, value_kind: str) -> str:
    if not points:
        return _empty_svg(title, "No usage found for this range.")

    width = 920
    row_height = 38
    top = 26
    left = 206
    right = 184
    height = top + row_height * len(points) + 22
    inner_width = width - left - right
    max_value = max(point.total_tokens for point in points) or 1

    chunks = [_svg_open(width, height, title)]
    for index, point in enumerate(points):
        y = top + index * row_height
        bar_width = max(2, point.total_tokens / max_value * inner_width)
        label = _truncate(point.label, 28)
        chunks.append(f'<text class="bar-label" x="{left - 10}" y="{y + 20}" text-anchor="end">{_esc(label)}</text>')
        chunks.append(
            f'<rect class="breakdown-bar" x="{left}" y="{y + 5}" width="{bar_width:.2f}" height="20" rx="4">'
            f'<title>{_esc(point.label)}: {_fmt_int(point.total_tokens)} {value_kind}, '
            f'${point.cost_usd:.4f}, {_fmt_credits(point.total_credits)} credits</title></rect>'
        )
        value_text = f"{_fmt_compact(point.total_tokens)} | ${point.cost_usd:.2f} | {_fmt_credits(point.total_credits)} cr"
        if point.unpriced_tokens:
            value_text += f" | {_fmt_compact(point.unpriced_tokens)} API excl."
        if point.credit_unpriced_tokens:
            value_text += f" | {_fmt_compact(point.credit_unpriced_tokens)} no credit"
        chunks.append(f'<text class="value-label" x="{left + inner_width + 10}" y="{y + 20}">{_esc(value_text)}</text>')
    chunks.append("</svg>")
    return "".join(chunks)


def _empty_svg(title: str, message: str) -> str:
    width = 920
    height = 150
    return (
        _svg_open(width, height, title)
        + f'<text class="empty-chart" x="24" y="78">{_esc(message)}</text>'
        + "</svg>"
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
