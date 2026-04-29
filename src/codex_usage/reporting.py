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
    render_hourly_heatmap_svg,
    render_model_mix_svg,
    render_project_breakdown_svg,
)
from codex_usage.pricing import PRICING_AS_OF
from codex_usage.report_view import ReportViewModel, build_report_view_model


def summary_payload(
    *,
    rows: list[AggregateRow],
    total: UsageSummary,
    generated_at: datetime,
    range_name: str,
    group_by: str,
    sessions_dirs: list[Path],
    files_scanned: int,
    subscription_usd: float | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "generated_at": generated_at.isoformat(),
        "pricing_as_of": PRICING_AS_OF,
        "range": range_name,
        "group_by": group_by,
        "sessions_dirs": [str(path) for path in sessions_dirs],
        "files_scanned": files_scanned,
        "total": total.to_dict(),
        "rows": [row.to_dict() for row in rows],
    }
    if subscription_usd is not None:
        payload["subscription_comparison"] = subscription_comparison(total.cost.total_usd, subscription_usd)
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
    subscription_usd: float | None,
) -> str:
    lines = [
        f"Codex usage summary ({range_name}, by {group_by})",
        f"Files scanned: {files_scanned} | Usage events: {total.record_count} | Pricing as of: {PRICING_AS_OF}",
        "",
        _format_row(
            "TOTAL",
            total.usage.total_tokens,
            total.usage.input_tokens,
            total.usage.cached_input_tokens,
            total.usage.output_tokens,
            total.cost.total_usd,
            total.cost.unpriced_tokens,
        ),
        "",
    ]
    if subscription_usd is not None:
        comparison = subscription_comparison(total.cost.total_usd, subscription_usd)
        lines.append(
            f"API-equivalent cost is {comparison['percent_of_subscription']:.1f}% "
            f"of ${subscription_usd:.2f} subscription."
        )
        lines.append("")

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
                row.cost.unpriced_tokens,
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
    subscription_usd: float | None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
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
    )
    comparison_html = ""
    if subscription_usd is not None:
        comparison = subscription_comparison(total.cost.total_usd, subscription_usd)
        comparison_html = (
            f"<p class=\"notice\">API-equivalent cost is {comparison['percent_of_subscription']:.1f}% "
            f"of ${subscription_usd:.2f} subscription.</p>"
        )
    partial_cost_html = _partial_cost_notice(view_model)

    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Codex Usage Report</title>
  <style>
    :root {{
      --bg: #fafafa;
      --text: #1f2933;
      --muted: #667085;
      --border: #d8dee4;
      --surface: #ffffff;
      --surface-soft: #f3f6f8;
      --accent: #0f766e;
      --accent-strong: #0d9488;
      --accent-warm: #c2410c;
      --warn: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
      margin: 0;
      background: var(--bg);
      color: var(--text);
      line-height: 1.4;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    h1 {{ font-size: 26px; margin: 0 0 4px; letter-spacing: 0; }}
    h2 {{ font-size: 17px; margin: 0 0 10px; letter-spacing: 0; }}
    h3 {{ font-size: 14px; margin: 18px 0 8px; letter-spacing: 0; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 10px; background: var(--surface); }}
    th, td {{ border-bottom: 1px solid var(--border); padding: 7px 8px; text-align: left; vertical-align: top; }}
    th {{ font-weight: 650; background: var(--surface-soft); }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .muted {{ color: var(--muted); font-size: 13px; }}
    .summary-line {{ margin-top: 4px; }}
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; margin: 20px 0 18px; }}
    .kpi {{ border: 1px solid var(--border); border-radius: 8px; background: var(--surface); padding: 12px; min-height: 92px; }}
    .kpi-label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; }}
    .kpi-value {{ display: block; font-size: 23px; font-weight: 700; margin-top: 6px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }}
    .kpi-detail {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
    .notice {{ border-left: 4px solid var(--accent-warm); background: #fff7ed; padding: 9px 12px; margin: 10px 0; }}
    .notice.warn {{ border-left-color: var(--warn); background: #fef3f2; }}
    .dashboard-grid {{ display: grid; grid-template-columns: minmax(0, 1fr); gap: 24px; margin-top: 18px; }}
    .section {{ border-top: 1px solid var(--border); padding-top: 18px; }}
    .chart-scroll {{ overflow-x: auto; padding-bottom: 4px; }}
    .chart-svg {{ display: block; width: 100%; height: auto; min-width: 680px; }}
    .axis-line {{ stroke: var(--border); stroke-width: 1; }}
    .axis-label {{ fill: var(--muted); font-size: 11px; }}
    .bar-label {{ fill: var(--text); font-size: 12px; }}
    .value-label {{ fill: var(--muted); font-size: 12px; }}
    .cost-bar {{ fill: var(--accent); }}
    .cost-bar:hover, .breakdown-bar:hover {{ fill: var(--accent-strong); }}
    .breakdown-bar {{ fill: var(--accent-warm); }}
    .heat-cell {{ stroke: #ffffff; stroke-width: 1; }}
    .empty-chart {{ fill: var(--muted); font-size: 14px; }}
    .table-wrap {{ overflow-x: auto; }}
    @media (max-width: 720px) {{
      main {{ padding: 16px; }}
      .kpi-value {{ font-size: 20px; }}
      th, td {{ padding: 6px; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Codex Usage Report</h1>
    <div class="muted summary-line">Generated {html.escape(generated_at.isoformat())} | Range: {html.escape(range_name)} | Pricing as of {PRICING_AS_OF}</div>
    <div class="muted summary-line">Sessions: {html.escape(', '.join(str(path) for path in sessions_dirs))} | Files scanned: {files_scanned}</div>
    {_render_kpis(view_model)}
    {partial_cost_html}
    {comparison_html}
    {_empty_report_notice(view_model)}
    <div class="dashboard-grid">
      {_chart_section("Daily Cost Trend", render_daily_cost_svg(view_model.daily_points), _table_section("Daily Details", daily_rows))}
      {_chart_section("Hourly Heatmap", render_hourly_heatmap_svg(view_model.hourly_cells), _table_section("Hourly Details", hourly_rows))}
      {_chart_section("Project Breakdown", render_project_breakdown_svg(view_model.project_points), _table_section("Project Details", project_rows))}
      {_chart_section("Model Mix", render_model_mix_svg(view_model.model_points), _table_section("Model Details", model_rows))}
    </div>
  </main>
</body>
</html>"""
    output_path.write_text(body, encoding="utf-8")
    return output_path


def subscription_comparison(cost_usd: float, subscription_usd: float) -> dict[str, float]:
    percent = (cost_usd / subscription_usd * 100) if subscription_usd > 0 else 0.0
    return {
        "subscription_usd": round(subscription_usd, 2),
        "api_equivalent_usd": round(cost_usd, 6),
        "difference_usd": round(cost_usd - subscription_usd, 6),
        "percent_of_subscription": percent,
    }


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
            "unpriced_tokens",
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
                "unpriced_tokens": row.cost.unpriced_tokens,
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


def _partial_cost_notice(view_model: ReportViewModel) -> str:
    if not view_model.has_partial_cost:
        return ""
    return (
        "<p class=\"notice warn\">Cost is partial because "
        f"{_fmt_int(view_model.total.cost.unpriced_tokens)} tokens came from models without checked-in USD API rates.</p>"
    )


def _empty_report_notice(view_model: ReportViewModel) -> str:
    if view_model.has_usage:
        return ""
    return "<p class=\"notice\">No Codex usage was found for this report range.</p>"


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
        f"{'Output':>14} {'Cost':>11} {'Unpriced':>14}"
    )


def _format_row(label: str, total: int, input_tokens: int, cached: int, output: int, cost: float, unpriced: int) -> str:
    return (
        f"{label[:34]:<34} {_fmt_int(total):>14} {_fmt_int(input_tokens):>14} "
        f"{_fmt_int(cached):>14} {_fmt_int(output):>14} ${cost:>10.4f} {_fmt_int(unpriced):>14}"
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
            f"<td class=\"num\">{_fmt_int(row.cost.unpriced_tokens)}</td>"
            f"<td><div class=\"bar-wrap\"><div class=\"bar\" style=\"width:{width}%\"></div></div></td>"
            "</tr>"
        )
    return (
        f"<h3>{html.escape(title)}</h3><div class=\"table-wrap\">"
        "<table><thead><tr><th>Label</th><th class=\"num\">Total</th><th class=\"num\">Input</th>"
        "<th class=\"num\">Cached</th><th class=\"num\">Output</th><th class=\"num\">Cost</th>"
        "<th class=\"num\">Unpriced</th><th>Share</th>"
        "</tr></thead><tbody>"
        + "".join(table_rows)
        + "</tbody></table></div>"
    )


def _fmt_int(value: int) -> str:
    return f"{value:,}"
