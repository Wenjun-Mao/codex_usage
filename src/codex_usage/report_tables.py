from __future__ import annotations

import html

from codex_usage.aggregation import AggregateRow
from codex_usage.report_breakdown_view import ProjectBreakdownPoint


def render_aggregate_table(
    title: str, rows: list[AggregateRow], *, section_id: str
) -> str:
    if not rows:
        return _empty_table_section(title, section_id)

    max_total = max(row.usage.total_tokens for row in rows) or 1
    table_rows = "".join(_aggregate_row_html(row, max_total) for row in rows[:200])
    return _table_section(
        title,
        section_id,
        '<th>Label</th><th class="num">Total</th><th class="num">Input</th>'
        '<th class="num">Cache Read</th><th class="num">Cache Write</th><th class="num">Output</th>'
        '<th class="num">API Cost</th><th class="num">Codex Credits</th><th class="num">API Excl.</th>'
        '<th class="num">No Credit Rate</th><th>Share</th>',
        table_rows,
    )


def render_project_details_table(
    title: str,
    points: tuple[ProjectBreakdownPoint, ...],
    *,
    section_id: str,
) -> str:
    if not points:
        return _empty_table_section(title, section_id)

    max_total = max(point.total_tokens for point in points) or 1
    table_rows = "".join(_project_row_html(point, max_total) for point in points[:200])
    return _table_section(
        title,
        section_id,
        '<th>Label</th><th class="num">Total</th><th class="num">Root Tokens</th>'
        '<th class="num">Subagent Tokens</th><th class="num">Input</th><th class="num">Cache Read</th>'
        '<th class="num">Cache Write</th><th class="num">Output</th><th class="num">API Cost</th>'
        '<th class="num">Codex Credits</th><th class="num">API Excl.</th>'
        '<th class="num">No Credit Rate</th><th>Share</th>',
        table_rows,
    )


def format_int(value: int) -> str:
    return f"{value:,}"


def format_credits(value: float) -> str:
    if value >= 1_000:
        return f"{value:,.0f}"
    return f"{value:,.1f}"


def _aggregate_row_html(row: AggregateRow, max_total: int) -> str:
    return _usage_cells(
        label=row.label,
        total_tokens=row.usage.total_tokens,
        input_tokens=row.usage.input_tokens,
        cached_input_tokens=row.usage.cached_input_tokens,
        cache_write_input_tokens=row.usage.cache_write_input_tokens,
        output_tokens=row.usage.output_tokens,
        cost_usd=row.cost.total_usd,
        total_credits=row.credits.total_credits,
        unpriced_tokens=row.cost.unpriced_tokens,
        credit_unpriced_tokens=row.credits.unpriced_tokens,
        max_total=max_total,
    )


def _project_row_html(point: ProjectBreakdownPoint, max_total: int) -> str:
    usage = point.usage
    return (
        "<tr>"
        f"<td>{html.escape(point.label)}</td>"
        f'<td class="num">{format_int(usage.total_tokens)}</td>'
        f'<td class="num">{format_int(point.root_tokens)}</td>'
        f'<td class="num">{format_int(point.subagent_tokens)}</td>'
        f'<td class="num">{format_int(usage.input_tokens)}</td>'
        f'<td class="num">{format_int(usage.cached_input_tokens)}</td>'
        f'<td class="num">{format_int(usage.cache_write_input_tokens)}</td>'
        f'<td class="num">{format_int(usage.output_tokens)}</td>'
        f'<td class="num">${point.cost.total_usd:.4f}</td>'
        f'<td class="num">{format_credits(point.credits.total_credits)}</td>'
        f'<td class="num">{format_int(point.cost.unpriced_tokens)}</td>'
        f'<td class="num">{format_int(point.credits.unpriced_tokens)}</td>'
        f"<td>{_share_bar(usage.total_tokens, max_total)}</td>"
        "</tr>"
    )


def _usage_cells(
    *,
    label: str,
    total_tokens: int,
    input_tokens: int,
    cached_input_tokens: int,
    cache_write_input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    total_credits: float,
    unpriced_tokens: int,
    credit_unpriced_tokens: int,
    max_total: int,
) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(label)}</td>"
        f'<td class="num">{format_int(total_tokens)}</td>'
        f'<td class="num">{format_int(input_tokens)}</td>'
        f'<td class="num">{format_int(cached_input_tokens)}</td>'
        f'<td class="num">{format_int(cache_write_input_tokens)}</td>'
        f'<td class="num">{format_int(output_tokens)}</td>'
        f'<td class="num">${cost_usd:.4f}</td>'
        f'<td class="num">{format_credits(total_credits)}</td>'
        f'<td class="num">{format_int(unpriced_tokens)}</td>'
        f'<td class="num">{format_int(credit_unpriced_tokens)}</td>'
        f"<td>{_share_bar(total_tokens, max_total)}</td>"
        "</tr>"
    )


def _share_bar(total_tokens: int, max_total: int) -> str:
    width = total_tokens / max_total * 100
    return f'<div class="bar-wrap"><div class="bar" style="width:{width:.4f}%"></div></div>'


def _empty_table_section(title: str, section_id: str) -> str:
    return (
        _section_open(section_id)
        + f'<h3>{html.escape(title)}</h3><p class="muted">No usage found.</p></section>'
    )


def _table_section(title: str, section_id: str, headers: str, rows: str) -> str:
    return (
        _section_open(section_id)
        + f'<h3>{html.escape(title)}</h3><div class="table-wrap"><table><thead><tr>{headers}</tr></thead>'
        f"<tbody>{rows}</tbody></table></div></section>"
    )


def _section_open(section_id: str) -> str:
    return f'<section class="report-table-section" data-report-section="{html.escape(section_id, quote=True)}">'
