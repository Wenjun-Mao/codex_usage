from __future__ import annotations

import html

from codex_usage.aggregation import AggregateRow
from codex_usage.report_breakdown_view import ProjectBreakdownPoint
from codex_usage.report_numbers import format_int
from codex_usage.report_project_economics import project_economics_css as project_economics_css
from codex_usage.report_project_economics import (
    render_project_economics_section as render_project_economics_section,
)


def render_aggregate_table(
    title: str, rows: list[AggregateRow], *, section_id: str
) -> str:
    if not rows:
        return _empty_table_section(title, section_id)

    table_rows = "".join(_aggregate_row_html(row) for row in rows)
    return _table_section(
        title,
        section_id,
        '<th>Label</th><th class="num">Total</th><th class="num">Input</th>'
        '<th class="num">Cache Read</th><th class="num">Cache Write (reported)</th><th class="num">Output</th>'
        '<th class="num">API Cost</th><th class="num">Codex Credits</th><th class="num">API Excl.</th>'
        '<th class="num">No Credit Rate</th>',
        table_rows,
    )


def render_model_details_table(rows: list[AggregateRow]) -> str:
    """Keep the model comparison compact while exposing additive event valuations."""
    title = "Model Details"
    section_id = "model-details"
    if not rows:
        return _empty_table_section(title, section_id)
    table_rows = "".join(_model_rows_html(row) for row in rows)
    return (
        _section_open(section_id) + '<h3 id="model-details-heading">Model Details</h3>'
        '<p class="muted model-details-help">Open a model for token categories and '
        "estimated prices. Input includes cached input, regular input, and "
        "reported cache writes; Total includes Input and Output. Category prices "
        "sum event valuations at their effective rates. Credit estimates use "
        "Standard rates; Fast usage cannot be identified in this ledger.</p>"
        '<div class="table-wrap"><table class="model-details-table" '
        'aria-labelledby="model-details-heading"><thead><tr>'
        '<th scope="col">Model</th><th scope="col" class="num">Tokens</th>'
        '<th scope="col" class="num">API Cost</th>'
        '<th scope="col" class="num">Est. Credits</th>'
        '<th scope="col" class="num">API Excl.</th>'
        '<th scope="col" class="num">No Credit Rate</th>'
        '<th scope="col" class="num">Output tok/s</th>'
        f"</tr></thead><tbody>{table_rows}</tbody></table></div></section>"
    )


def _model_rows_html(row: AggregateRow) -> str:
    usage, cost, credits = row.usage, row.cost, row.credits
    label = html.escape(row.label)
    categories = (
        (
            "Total",
            usage.total_tokens,
            cost.total_usd,
            credits.total_credits,
            cost.unpriced_tokens,
            credits.unpriced_tokens,
        ),
        (
            "Input subtotal",
            usage.input_tokens,
            cost.input_usd,
            credits.input_credits,
            cost.unpriced_input_tokens,
            credits.unpriced_input_tokens,
        ),
        (
            "Cached input",
            usage.cached_input_tokens,
            cost.cached_input_usd,
            credits.cached_input_credits,
            cost.unpriced_cached_input_tokens,
            credits.unpriced_cached_input_tokens,
        ),
        (
            "Regular input",
            usage.ordinary_input_tokens,
            cost.ordinary_input_usd,
            credits.ordinary_input_credits,
            cost.unpriced_ordinary_input_tokens,
            credits.unpriced_ordinary_input_tokens,
        ),
        (
            "Cache write (reported)",
            usage.cache_write_input_tokens,
            cost.cache_write_input_usd,
            credits.cache_write_input_credits,
            cost.unpriced_cache_write_input_tokens,
            credits.unpriced_cache_write_input_tokens,
        ),
        (
            "Output",
            usage.output_tokens,
            cost.output_usd,
            credits.output_credits,
            cost.unpriced_output_tokens,
            credits.unpriced_output_tokens,
        ),
    )
    detail_rows = "".join(
        "<tr>"
        f'<th scope="row">{html.escape(category)}</th>'
        f'<td class="num">{format_int(tokens)}</td>'
        f'<td class="num">{_partial_amount(amount, missing, tokens, "$")}</td>'
        f'<td class="num">{_partial_amount(credit_amount, credit_missing, tokens, "", decimals=2)}</td>'
        "</tr>"
        for category, tokens, amount, credit_amount, missing, credit_missing in categories
    )
    return (
        '<tr class="model-summary-row">'
        f'<th scope="row">{label}</th>'
        f'<td class="num">{format_int(usage.total_tokens)}</td>'
        f'<td class="num">{_partial_amount(cost.total_usd, cost.unpriced_tokens, usage.total_tokens, "$")}</td>'
        f'<td class="num">{_partial_amount(credits.total_credits, credits.unpriced_tokens, usage.total_tokens, "", decimals=2)}</td>'
        f'<td class="num">{format_int(cost.unpriced_tokens)}</td>'
        f'<td class="num">{format_int(credits.unpriced_tokens)}</td>'
        f'<td class="num"><span data-speed-model="{html.escape(row.key, quote=True)}">Unavailable</span></td></tr>'
        '<tr class="model-breakdown-row"><td colspan="7">'
        '<details class="model-breakdown"><summary>'
        f"Token and price breakdown for {label}</summary>"
        '<div class="table-wrap"><table aria-label="Token and price categories for '
        f'{html.escape(row.label, quote=True)}"><thead><tr>'
        '<th scope="col">Category</th><th scope="col" class="num">Tokens</th>'
        '<th scope="col" class="num">API Cost</th>'
        '<th scope="col" class="num">Est. Credits</th>'
        f"</tr></thead><tbody>{detail_rows}</tbody></table></div>"
        '<p class="muted">Cached, regular, and reported cache-write input add to Input. '
        "Input and Output add to Total. Cache-write credits are the ordinary input "
        "contribution, not a separate surcharge. “Partial” excludes tokens without "
        "a published rate; “—” means no rate is available.</p>"
        "</details></td></tr>"
    )


def _partial_amount(
    amount: float, missing: int, tokens: int, prefix: str, *, decimals: int = 6
) -> str:
    if tokens > 0 and missing >= tokens:
        return '<span aria-label="No published rate">—</span>'
    value = f"{amount:,.{decimals}f}"
    if amount > 0 and value == f"{0:.{decimals}f}":
        value = f"&lt;{10 ** -decimals:.{decimals}f}"
    suffix = ' <span class="model-partial">partial</span>' if missing else ""
    return f"{prefix}{value}{suffix}"


def render_project_details_table(
    title: str,
    points: tuple[ProjectBreakdownPoint, ...],
    *,
    section_id: str,
) -> str:
    if not points:
        return _empty_table_section(title, section_id)

    table_rows = "".join(_project_row_html(point) for point in points)
    return _table_section(
        title,
        section_id,
        '<th>Label</th><th class="num">Total</th><th class="num">Root Tokens</th>'
        '<th class="num">Subagent Tokens</th><th class="num">Input</th><th class="num">Cache Read</th>'
        '<th class="num">Cache Write (reported)</th><th class="num">Output</th><th class="num">API Cost</th>'
        '<th class="num">Codex Credits</th><th class="num">API Excl.</th>'
        '<th class="num">No Credit Rate</th>',
        table_rows,
    )


def format_credits(value: float) -> str:
    from codex_usage.report_numbers import estimated_credits
    return estimated_credits(value)


def _aggregate_row_html(row: AggregateRow) -> str:
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
    )


def _project_row_html(point: ProjectBreakdownPoint) -> str:
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
        "</tr>"
    )


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


def render_token_accounting_details(table_html: str) -> str:
    """Keep detailed token categories available without competing with the charts."""
    return (
        '<details class="token-accounting">'
        "<summary>Token Accounting</summary>"
        '<p class="muted token-accounting-help">Cache Write (reported) is taken from '
        "the selected ledger exactly as Codex reported it; it is never inferred from "
        "cache reads or reconstructed during report rendering.</p>"
        f"{table_html}"
        "</details>"
    )
