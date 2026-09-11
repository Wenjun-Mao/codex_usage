from __future__ import annotations

import html

from codex_usage.aggregation import AggregateRow
from codex_usage.project_economics import (
    ModelEconomics,
    ProjectEconomics,
    ProjectEconomicsReport,
    TurnCoverage,
    TurnMetrics,
)
from codex_usage.report_breakdown_view import ProjectBreakdownPoint


def render_aggregate_table(
    title: str, rows: list[AggregateRow], *, section_id: str
) -> str:
    if not rows:
        return _empty_table_section(title, section_id)

    max_total = max(row.usage.total_tokens for row in rows) or 1
    table_rows = "".join(_aggregate_row_html(row, max_total) for row in rows)
    return _table_section(
        title,
        section_id,
        '<th>Label</th><th class="num">Total</th><th class="num">Input</th>'
        '<th class="num">Cache Read</th><th class="num">Cache Write (reported)</th><th class="num">Output</th>'
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
    table_rows = "".join(_project_row_html(point, max_total) for point in points)
    return _table_section(
        title,
        section_id,
        '<th>Label</th><th class="num">Total</th><th class="num">Root Tokens</th>'
        '<th class="num">Subagent Tokens</th><th class="num">Input</th><th class="num">Cache Read</th>'
        '<th class="num">Cache Write (reported)</th><th class="num">Output</th><th class="num">API Cost</th>'
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


def render_project_economics_section(report: ProjectEconomicsReport | None) -> str:
    if report is None:
        return ""

    benchmark = report.benchmark
    if not report.projects:
        return (
            '<section class="section project-economics" '
            'data-report-section="project-economics" aria-labelledby="project-economics-heading">'
            '<h2 id="project-economics-heading">Project Economics</h2>'
            '<p class="muted">No positive ledger usage is available for project economics.</p>'
            "</section>"
        )

    project_rows = "".join(
        _render_project_economics_project(project) for project in report.projects
    )
    return (
        '<section class="section project-economics" '
        'data-report-section="project-economics" aria-labelledby="project-economics-heading">'
        '<div class="project-economics-heading">'
        '<div><h2 id="project-economics-heading">Project Economics</h2>'
        '<p class="muted">Turn measures use selected ledger responses with a non-empty '
        "turn ID. The benchmark is weighted across those responses, not averaged from projects.</p>"
        "</div>"
        '<span class="project-economics-source">Ledger only</span>'
        "</div>"
        f"{_render_economics_benchmark(benchmark)}"
        '<div class="project-economics-projects" aria-label="Project economics details">'
        f"{project_rows}"
        "</div>"
        "</section>"
    )


def project_economics_css() -> str:
    return """
    .token-accounting { margin-top: 12px; }
    .token-accounting > summary, .project-economics-project > summary { cursor: pointer; color: var(--text); font-weight: 650; }
    .token-accounting-help { max-width: 760px; margin: 8px 0 0; }
    .project-economics { display: grid; gap: 12px; }
    .project-economics-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
    .project-economics-heading h2 { margin-bottom: 4px; }.project-economics-heading p { max-width: 760px; margin: 0; }
    .project-economics-source, .project-economics-small-sample { display: inline-block; border: 1px solid var(--border); border-radius: 999px; color: var(--muted); font-size: 11px; font-weight: 650; line-height: 1.2; padding: 3px 7px; white-space: nowrap; }
    .project-economics-small-sample { border-color: var(--highlight); color: var(--highlight); margin-left: 7px; vertical-align: middle; }
    .project-economics-benchmark { background: var(--surface-soft); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
    .project-economics-benchmark-heading { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }.project-economics-benchmark-heading > span { color: var(--muted); }
    .project-economics-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 10px 0 0; }.project-economics-metrics > div { min-width: 0; }
    .project-economics-metrics dt, .project-economics-metrics span { color: var(--muted); font-size: 11px; }.project-economics-metrics dd { margin: 2px 0; font-size: 15px; font-variant-numeric: tabular-nums; font-weight: 650; overflow-wrap: anywhere; }.project-economics-metrics span { display: block; line-height: 1.3; }
    .project-economics-projects { display: grid; gap: 6px; }.project-economics-project { border: 1px solid var(--border); border-radius: 7px; background: var(--surface); padding: 0 10px; }.project-economics-project[open] { padding-bottom: 10px; }
    .project-economics-project > summary { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; min-height: 42px; }.project-economics-project-summary { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; text-align: right; }.project-economics-project-body { padding: 2px 0 0; }.project-economics-models { margin-top: 14px; }.project-economics-models th[scope="row"] { color: var(--text); font-weight: 500; }
    @media (max-width: 720px) { .project-economics-heading, .project-economics-project > summary { align-items: flex-start; flex-direction: column; gap: 4px; padding: 9px 0; }.project-economics-project > summary { min-height: 0; }.project-economics-project-summary { text-align: left; }.project-economics-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
"""


def _render_economics_benchmark(benchmark: ProjectEconomics) -> str:
    metrics = benchmark.metrics
    return (
        '<section class="project-economics-benchmark" aria-label="Weighted all-project benchmark">'
        '<div class="project-economics-benchmark-heading">'
        "<strong>Weighted all-project benchmark</strong>"
        f'<span>{format_int(metrics.turn_count)} measured turns</span>'
        "</div>"
        '<dl class="project-economics-metrics">'
        f"{_economics_metric('Average cost / turn', _currency_or_unavailable(metrics.average_cost_per_turn), _priced_turn_detail(metrics))}"
        f"{_economics_metric('Median cost / turn', _currency_or_unavailable(metrics.median_cost_per_turn), 'Priceable turns only')}"
        f"{_economics_metric('Tokens / turn', _number_or_unavailable(metrics.tokens_per_turn), _turn_response_detail(metrics))}"
        f"{_economics_metric('Turn coverage', _coverage_value(benchmark.coverage), _coverage_detail(benchmark.coverage))}"
        "</dl>"
        "</section>"
    )


def _render_project_economics_project(project: ProjectEconomics) -> str:
    metrics = project.metrics
    sample_warning = ('<span class="project-economics-small-sample">Small sample</span>' if project.is_small_sample else "")
    model_rows = "".join(_render_economics_model(model) for model in project.models)
    return (
        '<details class="project-economics-project"><summary>'
        '<span class="project-economics-project-name">'
        f"{html.escape(project.label)}{sample_warning}</span>"
        '<span class="project-economics-project-summary">'
        f"{format_int(project.total.usage.total_tokens)} tokens · {_currency_or_unavailable(metrics.average_cost_per_turn)} / turn · {format_int(metrics.turn_count)} turns"
        "</span></summary>"
        '<div class="project-economics-project-body"><dl class="project-economics-metrics">'
        f"{_economics_metric('Average cost / response', _currency_or_unavailable(metrics.average_cost_per_response), _priced_response_detail(metrics))}"
        f"{_economics_metric('Responses / turn', _number_or_unavailable(metrics.responses_per_turn), _turn_response_detail(metrics))}"
        f"{_economics_metric('Tokens / turn', _number_or_unavailable(metrics.tokens_per_turn), _coverage_detail(project.coverage))}"
        f"{_economics_metric('Turn coverage', _coverage_value(project.coverage), _coverage_detail(project.coverage))}"
        "</dl><div class=\"table-wrap\"><table class=\"project-economics-models\"><thead><tr>"
        '<th scope="col">Model</th><th scope="col" class="num">Tokens</th><th scope="col" class="num">Token share</th><th scope="col" class="num">Cost share</th><th scope="col" class="num">Turns</th><th scope="col" class="num">Average cost / turn</th>'
        f"</tr></thead><tbody>{model_rows}</tbody></table></div></div></details>"
    )


def _render_economics_model(model: ModelEconomics) -> str:
    return (
        "<tr>"
        f'<th scope="row">{html.escape(model.label)}</th><td class="num">{format_int(model.total.usage.total_tokens)}</td><td class="num">{model.token_share:.1%}</td><td class="num">{model.cost_share:.1%}</td><td class="num">{format_int(model.metrics.turn_count)}</td><td class="num">{_currency_or_unavailable(model.metrics.average_cost_per_turn)}</td>'
        "</tr>"
    )


def _economics_metric(label: str, value: str, detail: str) -> str:
    return f"<div><dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd><span>{html.escape(detail)}</span></div>"


def _currency_or_unavailable(value: float | None) -> str:
    return f"${value:,.4f}" if value is not None else "Unavailable"


def _number_or_unavailable(value: float | None) -> str:
    return f"{value:,.1f}" if value is not None else "Unavailable"


def _priced_turn_detail(metrics: TurnMetrics) -> str:
    return f"{format_int(metrics.priced_turn_count)} of {format_int(metrics.turn_count)} turns priceable"


def _priced_response_detail(metrics: TurnMetrics) -> str:
    return f"{format_int(metrics.priced_response_count)} of {format_int(metrics.response_count)} responses priceable"


def _turn_response_detail(metrics: TurnMetrics) -> str:
    return f"{format_int(metrics.response_count)} responses across {format_int(metrics.turn_count)} turns"


def _coverage_value(coverage: TurnCoverage) -> str:
    return f"{coverage.response_share:.0%} responses"


def _coverage_detail(coverage: TurnCoverage) -> str:
    return f"{format_int(coverage.measured_responses)} of {format_int(coverage.total_responses)} responses · {coverage.token_share:.0%} of tokens"
