from __future__ import annotations

import csv
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import TextIO

from codex_usage.aggregation import AggregateRow, UsageSummary
from codex_usage.charts import (
    render_daily_cost_svg,
    render_hourly_heatmap_html,
    render_model_mix_svg,
    render_project_breakdown_svg,
)
from codex_usage.pricing import PRICING_AS_OF, PRICING_METHOD
from codex_usage.report_view import ReportViewModel, build_report_view_model
from codex_usage.report_theme import normalize_report_theme, report_css


def summary_payload(
    *,
    rows: list[AggregateRow],
    total: UsageSummary,
    generated_at: datetime,
    range_name: str,
    group_by: str,
    sessions_dirs: list[Path],
    files_scanned: int,
    storage_roots: list[str] | None = None,
    files_archived: int = 0,
    files_retained_missing: int = 0,
    project_keys: list[str] | None = None,
    project_transitions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "generated_at": generated_at.isoformat(),
        "pricing_as_of": PRICING_AS_OF,
        "pricing_method": PRICING_METHOD,
        "range": range_name,
        "group_by": group_by,
        "project_keys": project_keys or [],
        "project_transitions": project_transitions or [],
        "sessions_dirs": [str(path) for path in sessions_dirs],
        "storage_roots": storage_roots or [str(path) for path in sessions_dirs],
        "files_scanned": files_scanned,
        "files_archived": files_archived,
        "files_retained_missing": files_retained_missing,
        "total": total.to_dict(),
        "rows": [row.to_dict() for row in rows],
    }
    return payload


def print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def write_csv(rows: list[AggregateRow], destination: str | Path | None) -> None:
    if destination in (None, "-"):
        _write_csv_rows(rows, sys.stdout)
        return

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        _write_csv_rows(rows, handle)


def render_terminal(
    *,
    rows: list[AggregateRow],
    total: UsageSummary,
    range_name: str,
    group_by: str,
    files_scanned: int,
    files_archived: int = 0,
    files_retained_missing: int = 0,
) -> str:
    storage_bits = _storage_bits(
        files_scanned=files_scanned,
        files_archived=files_archived,
        files_retained_missing=files_retained_missing,
    )
    lines = [
        f"Codex usage summary ({range_name}, by {group_by})",
        f"{' | '.join(storage_bits)} | Usage events: {total.record_count} | Pricing table as of: {PRICING_AS_OF}",
        "Pricing uses rates effective at each usage event.",
        "",
        _format_row(
            "TOTAL",
            total.usage.total_tokens,
            total.usage.input_tokens,
            total.usage.cached_input_tokens,
            total.usage.output_tokens,
            total.cost.total_usd,
            total.credits.total_credits,
            total.cost.unpriced_tokens,
            total.credits.unpriced_tokens,
        ),
        "",
    ]
    lines.append(_format_header())
    for row in rows:
        lines.append(
            _format_row(
                row.label,
                row.usage.total_tokens,
                row.usage.input_tokens,
                row.usage.cached_input_tokens,
                row.usage.output_tokens,
                row.cost.total_usd,
                row.credits.total_credits,
                row.cost.unpriced_tokens,
                row.credits.unpriced_tokens,
            )
        )
    return "\n".join(lines)


def render_html_report(
    *,
    output_path: Path,
    generated_at: datetime,
    range_name: str,
    total: UsageSummary,
    daily_rows: list[AggregateRow],
    hourly_rows: list[AggregateRow],
    project_rows: list[AggregateRow],
    model_rows: list[AggregateRow],
    sessions_dirs: list[Path],
    files_scanned: int,
    storage_roots: list[str] | None = None,
    files_archived: int = 0,
    files_retained_missing: int = 0,
    project_keys: list[str] | None = None,
    project_transitions: list[dict[str, object]] | None = None,
    theme: str = "auto",
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    theme = normalize_report_theme(theme)
    view_model = build_report_view_model(
        generated_at=generated_at,
        range_name=range_name,
        total=total,
        daily_rows=daily_rows,
        hourly_rows=hourly_rows,
        project_rows=project_rows,
        model_rows=model_rows,
        sessions_dirs=sessions_dirs,
        files_scanned=files_scanned,
        files_archived=files_archived,
        files_retained_missing=files_retained_missing,
        storage_roots=storage_roots,
    )
    pricing_notice_html = _pricing_notice(view_model)
    project_filter_label = _project_filter_label(project_keys)
    project_transitions_html = _project_transitions_section(project_transitions)
    storage_summary = " | ".join(
        _storage_bits(
            files_scanned=view_model.files_scanned,
            files_archived=view_model.files_archived,
            files_retained_missing=view_model.files_retained_missing,
        )
    )

    body = f"""<!doctype html>
<html lang="en" data-codex-theme="{html.escape(theme)}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Codex Usage Report</title>
  <style>
{report_css()}
  </style>
</head>
<body>
  <main>
    <h1>Codex Usage Report</h1>
    <div class="muted summary-line">Generated {html.escape(generated_at.isoformat())} | Range: {html.escape(range_name)} | Pricing table as of {PRICING_AS_OF}</div>
    <div class="muted summary-line">Pricing uses rates effective at each usage event.</div>
    <div class="muted summary-line">Projects: {html.escape(project_filter_label)}</div>
    <div class="muted summary-line">Sessions: {html.escape(', '.join(str(path) for path in sessions_dirs))}</div>
    <div class="muted summary-line">{html.escape(storage_summary)}</div>
    {_render_kpis(view_model)}
    {pricing_notice_html}
    {_empty_report_notice(view_model)}
    {project_transitions_html}
    <div class="dashboard-grid">
      {_chart_section("Daily Cost Trend", render_daily_cost_svg(view_model.daily_points), _table_section("Daily Details", daily_rows))}
      {_chart_section("Hourly Heatmap", render_hourly_heatmap_html(view_model.hourly_cells), _table_section("Hourly Details", hourly_rows))}
      {_chart_section("Project Breakdown", render_project_breakdown_svg(view_model.project_points), _table_section("Project Details", project_rows))}
      {_chart_section("Model Mix", render_model_mix_svg(view_model.model_points), _table_section("Model Details", model_rows))}
    </div>
  </main>
</body>
</html>"""
    output_path.write_text(body, encoding="utf-8")
    return output_path


def _project_filter_label(project_keys: list[str] | None) -> str:
    selected = [key for key in project_keys or [] if key]
    if not selected:
        return "All Projects"
    return ", ".join(selected)


def _storage_bits(*, files_scanned: int, files_archived: int, files_retained_missing: int) -> list[str]:
    bits = [f"Files scanned: {files_scanned}"]
    if files_archived:
        bits.append(f"Archived files included: {files_archived}")
    if files_retained_missing:
        bits.append(f"Retained missing files: {files_retained_missing}")
    return bits


def _write_csv_rows(rows: list[AggregateRow], handle: TextIO) -> None:
    writer = csv.DictWriter(
        handle,
        fieldnames=[
            "key",
            "label",
            "record_count",
            "total_tokens",
            "input_tokens",
            "cached_input_tokens",
            "uncached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "cost_usd",
            "codex_credits",
            "unpriced_tokens",
            "credit_unpriced_tokens",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "key": row.key,
                "label": row.label,
                "record_count": row.record_count,
                "total_tokens": row.usage.total_tokens,
                "input_tokens": row.usage.input_tokens,
                "cached_input_tokens": row.usage.cached_input_tokens,
                "uncached_input_tokens": row.usage.uncached_input_tokens,
                "output_tokens": row.usage.output_tokens,
                "reasoning_output_tokens": row.usage.reasoning_output_tokens,
                "cost_usd": f"{row.cost.total_usd:.6f}",
                "codex_credits": f"{row.credits.total_credits:.6f}",
                "unpriced_tokens": row.cost.unpriced_tokens,
                "credit_unpriced_tokens": row.credits.unpriced_tokens,
            }
        )


def _render_kpis(view_model: ReportViewModel) -> str:
    cards = []
    for card in view_model.kpis:
        cards.append(
            "<div class=\"kpi\">"
            f"<div class=\"kpi-label\">{html.escape(card.label)}</div>"
            f"<strong class=\"kpi-value\">{html.escape(card.value)}</strong>"
            f"<div class=\"kpi-detail\">{html.escape(card.detail)}</div>"
            "</div>"
        )
    return "<section class=\"kpis\" aria-label=\"Usage summary\">" + "".join(cards) + "</section>"


def _pricing_notice(view_model: ReportViewModel) -> str:
    notices = []
    if view_model.has_partial_cost:
        notices.append(
            "<p class=\"notice\">API USD excludes "
            f"{_fmt_int(view_model.total.cost.unpriced_tokens)} tokens from models without API USD rates. "
            "Codex credit estimates are shown separately.</p>"
        )
    if view_model.no_price_data_tokens:
        notices.append(
            "<p class=\"notice warn\">No price data is available for "
            f"{_fmt_int(view_model.no_price_data_tokens)} tokens; these models have neither API USD nor Codex credit rates.</p>"
        )
    return "".join(notices)


def _empty_report_notice(view_model: ReportViewModel) -> str:
    if view_model.has_usage:
        return ""
    return "<p class=\"notice\">No Codex usage was found for this report range.</p>"


def _project_transitions_section(project_transitions: list[dict[str, object]] | None) -> str:
    if not project_transitions:
        return ""

    rows = []
    for transition in project_transitions:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(transition.get('source_label', '')))}</td>"
            f"<td>{html.escape(str(transition.get('target_label', '')))}</td>"
            f"<td>{html.escape(str(transition.get('effective_from', '')))}</td>"
            f"<td class=\"num\">{html.escape(str(transition.get('confidence', '')))}</td>"
            "</tr>"
        )

    return (
        "<section class=\"section\">"
        "<h2>Project Transitions</h2>"
        "<p class=\"muted\">Usage is split at verified local repository switch points.</p>"
        "<div class=\"table-wrap\"><table>"
        "<thead><tr><th>From</th><th>To</th><th>Effective From</th><th class=\"num\">Confidence</th></tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
        "</section>"
    )


def _chart_section(title: str, svg: str, table_html: str) -> str:
    return (
        "<section class=\"section\">"
        f"<h2>{html.escape(title)}</h2>"
        f"<div class=\"chart-scroll\">{svg}</div>"
        f"{table_html}"
        "</section>"
    )


def _format_header() -> str:
    return (
        f"{'Label':<34} {'Total':>14} {'Input':>14} {'Cached':>14} "
        f"{'Output':>14} {'Cost':>11} {'Credits':>12} {'API Excl.':>14} {'No Credit':>14}"
    )


def _format_row(
    label: str,
    total: int,
    input_tokens: int,
    cached: int,
    output: int,
    cost: float,
    credits: float,
    unpriced: int,
    credit_unpriced: int,
) -> str:
    return (
        f"{label[:34]:<34} {_fmt_int(total):>14} {_fmt_int(input_tokens):>14} "
        f"{_fmt_int(cached):>14} {_fmt_int(output):>14} ${cost:>10.4f} "
        f"{_fmt_credits(credits):>12} {_fmt_int(unpriced):>14} {_fmt_int(credit_unpriced):>14}"
    )


def _table_section(title: str, rows: list[AggregateRow]) -> str:
    if not rows:
        return f"<h3>{html.escape(title)}</h3><p class=\"muted\">No usage found.</p>"
    max_total = max(row.usage.total_tokens for row in rows) or 1
    table_rows = []
    for row in rows[:200]:
        width = max(1, round(row.usage.total_tokens / max_total * 100))
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(row.label)}</td>"
            f"<td class=\"num\">{_fmt_int(row.usage.total_tokens)}</td>"
            f"<td class=\"num\">{_fmt_int(row.usage.input_tokens)}</td>"
            f"<td class=\"num\">{_fmt_int(row.usage.cached_input_tokens)}</td>"
            f"<td class=\"num\">{_fmt_int(row.usage.output_tokens)}</td>"
            f"<td class=\"num\">${row.cost.total_usd:.4f}</td>"
            f"<td class=\"num\">{_fmt_credits(row.credits.total_credits)}</td>"
            f"<td class=\"num\">{_fmt_int(row.cost.unpriced_tokens)}</td>"
            f"<td class=\"num\">{_fmt_int(row.credits.unpriced_tokens)}</td>"
            f"<td><div class=\"bar-wrap\"><div class=\"bar\" style=\"width:{width}%\"></div></div></td>"
            "</tr>"
        )
    return (
        f"<h3>{html.escape(title)}</h3><div class=\"table-wrap\">"
        "<table><thead><tr><th>Label</th><th class=\"num\">Total</th><th class=\"num\">Input</th>"
        "<th class=\"num\">Cached</th><th class=\"num\">Output</th><th class=\"num\">API Cost</th>"
        "<th class=\"num\">Codex Credits</th><th class=\"num\">API Excl.</th><th class=\"num\">No Credit Rate</th><th>Share</th>"
        "</tr></thead><tbody>"
        + "".join(table_rows)
        + "</tbody></table></div>"
    )


def _fmt_int(value: int) -> str:
    return f"{value:,}"


def _fmt_credits(value: float) -> str:
    if value >= 1_000:
        return f"{value:,.0f}"
    return f"{value:,.1f}"
