from __future__ import annotations

import html
from decimal import Decimal

from codex_usage.project_economics import (
    ModelEconomics,
    ProjectEconomics,
    ProjectEconomicsReport,
    TurnCoverage,
    TurnMetrics,
)
from codex_usage.report_numbers import adaptive_usd, compact_token_count, format_int


def render_project_economics_section(report: ProjectEconomicsReport | None) -> str:
    if report is None:
        return ""

    if not report.projects:
        return (
            '<section class="section project-economics" '
            'data-report-section="project-economics" aria-labelledby="project-economics-heading">'
            '<h2 id="project-economics-heading">Project Economics</h2>'
            '<p class="muted">No positive ledger usage is available for project economics.</p>'
            "</section>"
        )

    project_rows = "".join(
        _render_project(project) for project in report.projects
    )
    return (
        '<section class="section project-economics" '
        'data-report-section="project-economics" aria-labelledby="project-economics-heading">'
        '<div class="project-economics-heading">'
        '<div><h2 id="project-economics-heading">Project Economics</h2>'
        '<p class="muted">Turn measures use selected responses with a non-empty turn ID. '
        "Per-model measures use that model's own usage; average API-equivalent costs use "
        'fully priced responses. Token totals include input (including cached input) and output.</p>'
        "</div>"
        '<span class="project-economics-source">Ledger only</span>'
        "</div>"
        f"{_render_benchmark(report.benchmark)}"
        '<div class="project-economics-projects" aria-label="Project economics details">'
        f"{project_rows}"
        "</div>"
        "</section>"
    )


def project_economics_css() -> str:
    return """
    .token-accounting { margin-top: 12px; }
    .token-accounting > summary, .project-economics-project > summary, .project-economics-secondary > summary { cursor: pointer; color: var(--text); font-weight: 650; }
    .token-accounting-help { max-width: 760px; margin: 8px 0 0; }
    .project-economics { display: grid; gap: 12px; min-width: 0; }
    .project-economics-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
    .project-economics-heading h2 { margin-bottom: 4px; }.project-economics-heading p { max-width: 760px; margin: 0; }
    .project-economics-source, .project-economics-small-sample { display: inline-block; border: 1px solid var(--border); border-radius: 999px; color: var(--muted); font-size: 11px; font-weight: 650; line-height: 1.2; padding: 3px 7px; white-space: nowrap; }
    .project-economics-small-sample { border-color: var(--highlight); color: var(--highlight); margin-left: 7px; vertical-align: middle; }
    .project-economics-benchmark { background: var(--surface-soft); border: 1px solid var(--border); border-radius: 8px; padding: 12px; min-width: 0; }
    .project-economics-benchmark-heading { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }.project-economics-benchmark-heading > span { color: var(--muted); }
    .project-economics-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 10px 0 0; }.project-economics-metrics > div { min-width: 0; }
    .project-economics-metrics dt, .project-economics-metrics span { color: var(--muted); font-size: 11px; }.project-economics-metrics dd { margin: 2px 0; font-size: 15px; font-variant-numeric: tabular-nums; font-weight: 650; overflow-wrap: anywhere; }.project-economics-metrics span { display: block; line-height: 1.3; }
    .project-economics-projects { display: grid; gap: 6px; min-width: 0; }.project-economics-project { border: 1px solid var(--border); border-radius: 7px; background: var(--surface); padding: 0 10px; min-width: 0; }.project-economics-project[open] { padding-bottom: 10px; }
    .project-economics-project > summary { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; min-height: 42px; }.project-economics-project-summary { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; text-align: right; }.project-economics-project-body { padding: 2px 0 0; min-width: 0; }
    .project-economics-table-wrap { max-width: 100%; min-width: 0; overflow-x: auto; overscroll-behavior-inline: contain; }
    .project-economics-models { margin: 8px 0 0; min-width: 660px; }.project-economics-models th[scope="row"] { color: var(--text); font-weight: 500; overflow-wrap: anywhere; }.project-economics-models th[scope="col"] { white-space: nowrap; }.project-economics-models .num { white-space: nowrap; }
    .project-economics-secondary { border-top: 1px solid var(--border); margin-top: 12px; padding-top: 10px; }.project-economics-secondary > summary:focus-visible, .project-economics-project > summary:focus-visible { outline: 2px solid var(--accent-strong); outline-offset: 3px; }
    .project-economics-secondary-help { margin: 7px 0; max-width: 900px; }.project-economics-legacy { min-width: 1120px; font-size: 12px; }.project-economics-legacy .num { white-space: nowrap; }.project-economics-exact { display: block; color: var(--muted); font-size: 11px; font-weight: 400; margin-top: 2px; }
    @media (max-width: 720px) { .project-economics-heading, .project-economics-project > summary { align-items: flex-start; flex-direction: column; gap: 4px; padding: 9px 0; }.project-economics-project > summary { min-height: 0; }.project-economics-project-summary { text-align: left; }.project-economics-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
"""


def _render_benchmark(benchmark: ProjectEconomics) -> str:
    metrics = benchmark.metrics
    return (
        '<section class="project-economics-benchmark" aria-label="Weighted all-project benchmark">'
        '<div class="project-economics-benchmark-heading">'
        "<strong>Weighted all-project benchmark</strong>"
        f"<span>{format_int(metrics.turn_count)} measured turns</span>"
        "</div>"
        '<dl class="project-economics-metrics">'
        f"{_economics_metric('Average cost / turn', _usd(metrics.average_cost_per_turn), _priced_turn_detail(metrics))}"
        f"{_economics_metric('Median cost / turn', _usd(metrics.median_cost_per_turn), 'Priceable turns only')}"
        f"{_economics_metric('Tokens / turn', _number_or_unavailable(metrics.tokens_per_turn), _turn_response_detail(metrics))}"
        f"{_economics_metric('Turn coverage', _coverage_value(benchmark.coverage), _coverage_detail(benchmark.coverage))}"
        "</dl>"
        "</section>"
    )


def _render_project(project: ProjectEconomics) -> str:
    metrics = project.metrics
    sample_warning = (
        '<span class="project-economics-small-sample">Small sample</span>'
        if project.is_small_sample
        else ""
    )
    response_cost_labels = adaptive_usd(
        tuple(model.metrics.average_cost_per_response for model in project.models)
    )
    turn_cost_labels = adaptive_usd(
        tuple(model.metrics.average_cost_per_turn for model in project.models)
    )
    model_rows = "".join(
        _render_primary_model(model, response_cost)
        for model, response_cost in zip(
            project.models, response_cost_labels, strict=True
        )
    )
    detail_rows = "".join(
        _render_model_detail(model, turn_cost)
        for model, turn_cost in zip(project.models, turn_cost_labels, strict=True)
    )
    return (
        '<details class="project-economics-project"><summary>'
        '<span class="project-economics-project-name">'
        f"{html.escape(project.label)}{sample_warning}</span>"
        '<span class="project-economics-project-summary">'
        f"{format_int(project.total.usage.total_tokens)} tokens | {_usd(metrics.average_cost_per_turn)} / turn | {format_int(metrics.turn_count)} turns"
        "</span></summary>"
        '<div class="project-economics-project-body"><dl class="project-economics-metrics">'
        f"{_economics_metric('Average cost / response', _usd(metrics.average_cost_per_response), _priced_response_detail(metrics))}"
        f"{_economics_metric('Responses / turn', _number_or_unavailable(metrics.responses_per_turn), _turn_response_detail(metrics))}"
        f"{_economics_metric('Tokens / turn', _number_or_unavailable(metrics.tokens_per_turn), _coverage_detail(project.coverage))}"
        f"{_economics_metric('Turn coverage', _coverage_value(project.coverage), _coverage_detail(project.coverage))}"
        '</dl><div class="table-wrap project-economics-table-wrap">'
        f'<table class="project-economics-models" aria-label="Per-model comparison for {html.escape(project.label, quote=True)}">'
        '<thead><tr><th scope="col">Model</th>'
        '<th scope="col" class="num">Average API-equivalent cost / response</th>'
        '<th scope="col" class="num">Responses / turn</th>'
        '<th scope="col" class="num">Tokens / turn</th>'
        '<th scope="col" class="num">Measured turns</th>'
        f"</tr></thead><tbody>{model_rows}</tbody></table></div>"
        '<details class="project-economics-secondary"><summary>Totals, shares, coverage and priceability</summary>'
        '<p class="muted project-economics-secondary-help">Totals include all positive responses, including those without a turn ID. '
        'Turn averages use measured turns only; cost averages use fully priced responses or turns. '
        'Exact average API-equivalent costs and their measured denominators are shown in this detail.</p>'
        '<div class="table-wrap project-economics-table-wrap"><table class="project-economics-legacy" '
        f'aria-label="Detailed totals and coverage for {html.escape(project.label, quote=True)}">'
        '<thead><tr><th scope="col">Model</th><th scope="col" class="num">Total tokens</th>'
        '<th scope="col" class="num">Token share</th><th scope="col" class="num">Cost share</th>'
        '<th scope="col" class="num">Measured turns</th><th scope="col" class="num">Average cost / turn</th>'
        '<th scope="col" class="num">Average cost / response</th><th scope="col">Response coverage</th>'
        '<th scope="col">Token coverage</th><th scope="col">Priceability</th>'
        f"</tr></thead><tbody>{detail_rows}</tbody></table></div></details></div></details>"
    )


def _render_primary_model(model: ModelEconomics, response_cost: str) -> str:
    metrics = model.metrics
    turns = format_int(metrics.turn_count)
    sample_warning = (
        '<span class="project-economics-small-sample">Small sample</span>'
        if 0 < metrics.turn_count < 5
        else ""
    )
    return (
        "<tr>"
        f'<th scope="row">{html.escape(model.label)}</th>'
        f'<td class="num">{_primary_money(response_cost, metrics)}</td>'
        f'<td class="num" title="{_turn_response_detail(metrics)}">{_number_or_unavailable(metrics.responses_per_turn)}</td>'
        f'<td class="num" title="{_coverage_detail(model.coverage)}">{compact_token_count(metrics.tokens_per_turn)}</td>'
        f'<td class="num">{turns}{sample_warning}</td>'
        "</tr>"
    )


def _render_model_detail(model: ModelEconomics, turn_cost: str) -> str:
    coverage = model.coverage
    metrics = model.metrics
    return (
        "<tr>"
        f'<th scope="row">{html.escape(model.label)}</th>'
        f'<td class="num">{format_int(model.total.usage.total_tokens)}</td>'
        f'<td class="num">{model.token_share:.1%}</td>'
        f'<td class="num">{model.cost_share:.1%}</td>'
        f'<td class="num">{format_int(metrics.turn_count)}</td>'
        f'<td class="num">{_detail_money(turn_cost, metrics.average_cost_per_turn, _priced_turn_detail(metrics))}</td>'
        f'<td class="num">{_detail_money(_usd(metrics.average_cost_per_response), metrics.average_cost_per_response, _priced_response_detail(metrics))}</td>'
        f'<td>{format_int(coverage.measured_responses)} / {format_int(coverage.total_responses)} '
        f'({coverage.response_share:.0%}); {format_int(coverage.missing_responses)} missing turn IDs</td>'
        f'<td>{format_int(coverage.measured_tokens)} / {format_int(coverage.total_tokens)} '
        f'({coverage.token_share:.0%}); {format_int(coverage.missing_tokens)} missing-turn tokens</td>'
        f'<td>{format_int(metrics.priced_response_count)} / {format_int(metrics.response_count)} responses; '
        f'{format_int(metrics.priced_turn_count)} / {format_int(metrics.turn_count)} turns</td>'
        "</tr>"
    )


def _primary_money(label: str, metrics: TurnMetrics) -> str:
    if metrics.average_cost_per_response is None:
        return html.escape(label)
    title = (
        f"Exact average API-equivalent USD: ${_exact_number(metrics.average_cost_per_response)}; "
        f"{_priced_response_detail(metrics)}"
    )
    return f'<span title="{html.escape(title, quote=True)}">{html.escape(label)}</span>'


def _detail_money(label: str, value: float | None, denominator: str) -> str:
    if value is None:
        return html.escape(label)
    exact = f"${_exact_number(value)}"
    title = f"Exact API-equivalent USD {exact}; {denominator}"
    return (
        f'<span title="{html.escape(title, quote=True)}">{html.escape(label)}</span>'
        f'<small class="project-economics-exact">Exact: {html.escape(exact)}</small>'
    )


def _economics_metric(label: str, value: str, detail: str) -> str:
    return (
        f"<div><dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd>"
        f"<span>{html.escape(detail)}</span></div>"
    )


def _usd(value: float | None) -> str:
    return adaptive_usd((value,))[0]


def _exact_number(value: float) -> str:
    return format(Decimal(str(value)).normalize(), "g")


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
    return (
        f"{format_int(coverage.measured_responses)} of {format_int(coverage.total_responses)} responses; "
        f"{coverage.token_share:.0%} of tokens; {format_int(coverage.missing_responses)} responses and "
        f"{format_int(coverage.missing_tokens)} tokens have no turn ID"
    )
