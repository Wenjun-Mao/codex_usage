"""Accessible, content-free HTML for independent image activity reporting."""

from __future__ import annotations

import html

from codex_usage.image_aggregation import ImageActivitySummary, ImageValueCoverage
from codex_usage.image_reporting import ImageReport, ImageReportCoverage
from codex_usage.report_tables import format_int


def render_image_activity_section(report: ImageReport | None) -> str:
    if report is None:
        return ""
    summary = report.summary
    if summary.operation_count == 0:
        body = _empty_activity_notice(report)
    else:
        body = (
            f'<dl class="image-activity-metrics">{_metric("Operations", format_int(summary.operation_count))}'
            f'{_metric("Outputs", format_int(summary.output_count))}'
            f'{_metric("Succeeded", format_int(summary.succeeded_count), _outcomes(summary))}'
            f'{_metric("API equivalent", _coverage(summary.api_usd, "$"))}'
            "</dl>"
            f"{_model_table(report)}{_project_details(report)}"
        )
    return (
        '<section class="section image-activity" data-report-section="image-activity" '
        'aria-labelledby="image-activity-heading">'
        '<div class="image-activity-heading"><div><h2 id="image-activity-heading">Image Generation</h2>'
        '<p class="muted">Ledger-only image operations. Image values are separate from language tokens, costs, and Project Economics; prompts and image contents are never retained.</p>'
        '</div><span class="image-activity-source">Separate accounting</span></div>'
        f"{body}</section>"
    )


def _empty_activity_notice(report: ImageReport) -> str:
    coverage = report.coverage
    if coverage.complete:
        return '<p class="muted">No image-generation activity was found for this selection.</p>'
    return (
        '<p class="muted">No recorded image-generation activity was found for this selection. '
        "Historical image coverage is incomplete, so this selection may omit earlier activity. "
        f"{_coverage_counts(coverage)}</p>"
    )


def _coverage_counts(coverage: ImageReportCoverage) -> str:
    return (
        f"{coverage.tasks_completed:,} complete, "
        f"{coverage.pending_tasks:,} pending, "
        f"{coverage.tasks_unavailable:,} unavailable task owners across "
        f"{coverage.artifacts_total:,} artifacts."
    )


def image_activity_css() -> str:
    return """
    .image-activity { display: grid; gap: 12px; }
    .image-activity-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
    .image-activity-heading h2, .image-activity-heading p { margin: 0; }.image-activity-heading p { max-width: 760px; margin-top: 4px; }
    .image-activity-source { display: inline-block; border: 1px solid var(--border); border-radius: 999px; color: var(--muted); font-size: 11px; font-weight: 650; line-height: 1.2; padding: 3px 7px; white-space: nowrap; }
    .image-activity-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 0; }.image-activity-metrics > div { min-width: 0; padding: 10px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface-soft); }.image-activity-metrics dt { color: var(--muted); font-size: 11px; }.image-activity-metrics dd { margin: 2px 0 0; font-size: 15px; font-weight: 650; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }.image-activity-metrics small { display: block; margin-top: 3px; color: var(--muted); font-size: 11px; line-height: 1.3; }
    .image-activity-projects { display: grid; gap: 6px; }.image-activity-project { border: 1px solid var(--border); border-radius: 7px; background: var(--surface); padding: 0 10px; }.image-activity-project[open] { padding-bottom: 10px; }.image-activity-project > summary { cursor: pointer; display: flex; align-items: baseline; justify-content: space-between; gap: 12px; min-height: 42px; color: var(--text); font-weight: 650; }.image-activity-project-summary { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; text-align: right; }
    @media (max-width: 720px) { .image-activity-heading, .image-activity-project > summary { align-items: flex-start; flex-direction: column; gap: 4px; }.image-activity-project > summary { min-height: 0; padding: 9px 0; }.image-activity-project-summary { text-align: left; }.image-activity-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    """


def _metric(label: str, value: str, detail: str = "") -> str:
    detail_html = f"<small>{html.escape(detail)}</small>" if detail else ""
    return f"<div><dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd>{detail_html}</div>"


def _model_table(report: ImageReport) -> str:
    rows = "".join(
        "<tr>"
        f"<th scope=\"row\">{html.escape(model.label)}</th>"
        f'<td class="num">{format_int(model.summary.operation_count)}</td>'
        f'<td class="num">{format_int(model.summary.output_count)}</td>'
        f'<td class="num">{html.escape(_coverage(model.summary.api_usd, "$"))}</td>'
        f'<td class="num">{html.escape(_coverage(model.summary.credits, "credits"))}</td>'
        "</tr>"
        for model in report.models
    )
    return (
        '<div class="table-wrap"><table><thead><tr><th>Model evidence</th>'
        '<th class="num">Operations</th><th class="num">Outputs</th>'
        '<th class="num">API equivalent</th><th class="num">Codex credits</th>'
        f"</tr></thead><tbody>{rows}</tbody></table></div>"
    )


def _project_details(report: ImageReport) -> str:
    if not report.projects:
        return ""
    rows = "".join(
        '<details class="image-activity-project"><summary>'
        f"<span>{html.escape(project.label)}</span>"
        f'<span class="image-activity-project-summary">{format_int(project.summary.operation_count)} operations · {format_int(project.summary.output_count)} outputs · {html.escape(_coverage(project.summary.api_usd, "$"))}</span>'
        "</summary>"
        f'<dl class="image-activity-metrics">{_metric("Succeeded", format_int(project.summary.succeeded_count), _outcomes(project.summary))}{_metric("API equivalent", _coverage(project.summary.api_usd, "$"))}{_metric("Codex credits", _coverage(project.summary.credits, "credits"))}{_metric("Unpriced API operations", format_int(project.summary.api_usd.unpriced_operation_count))}</dl>'
        "</details>"
        for project in report.projects
    )
    return (
        '<div class="image-activity-projects" aria-label="Image generation by project">'
        f"{rows}</div>"
    )


def _coverage(value: ImageValueCoverage, unit: str) -> str:
    def amount(number: float) -> str:
        return f"{unit}{number:.4f}" if unit == "$" else f"{number:.4f} {unit}"

    parts: list[str] = []
    if value.exact_operation_count:
        parts.append(f"exact {amount(value.exact_amount)}")
    if value.estimated_operation_count:
        parts.append(
            f"estimated {amount(value.estimated_low)}–{amount(value.estimated_high)}"
        )
    if value.unpriced_operation_count:
        parts.append(f"{value.unpriced_operation_count} unpriced")
    return "; ".join(parts) or "No priceable operations"


def _outcomes(summary: ImageActivitySummary) -> str:
    values = []
    if summary.attempted_count:
        values.append(f"{summary.attempted_count} attempted")
    if summary.failed_count:
        values.append(f"{summary.failed_count} failed")
    return ", ".join(values)
