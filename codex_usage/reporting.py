from __future__ import annotations

import csv
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import TextIO

from codex_usage.aggregation import AggregateRow, UsageSummary
from codex_usage.pricing import PRICING_AS_OF


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
    comparison_html = ""
    if subscription_usd is not None:
        comparison = subscription_comparison(total.cost.total_usd, subscription_usd)
        comparison_html = (
            f"<p>API-equivalent cost is {comparison['percent_of_subscription']:.1f}% "
            f"of ${subscription_usd:.2f} subscription.</p>"
        )

    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Codex Usage Report</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 24px; color: #1f2937; }}
    h1 {{ font-size: 24px; margin-bottom: 4px; }}
    h2 {{ font-size: 16px; margin-top: 28px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
    th, td {{ border-bottom: 1px solid #d1d5db; padding: 7px 8px; text-align: left; }}
    th {{ font-weight: 650; background: #f3f4f6; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .muted {{ color: #6b7280; font-size: 13px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 18px 0; }}
    .card {{ border: 1px solid #d1d5db; border-radius: 8px; padding: 12px; }}
    .card strong {{ display: block; font-size: 20px; margin-top: 4px; }}
    .bar {{ height: 9px; border-radius: 999px; background: #2563eb; min-width: 1px; }}
    .bar-wrap {{ width: 100%; background: #e5e7eb; border-radius: 999px; overflow: hidden; }}
  </style>
</head>
<body>
  <h1>Codex Usage Report</h1>
  <div class="muted">Generated {html.escape(generated_at.isoformat())} | Range: {html.escape(range_name)} | Pricing as of {PRICING_AS_OF}</div>
  <div class="muted">Sessions: {html.escape(', '.join(str(path) for path in sessions_dirs))} | Files scanned: {files_scanned}</div>
  <div class="cards">
    <div class="card">Total tokens<strong>{_fmt_int(total.usage.total_tokens)}</strong></div>
    <div class="card">Input tokens<strong>{_fmt_int(total.usage.input_tokens)}</strong></div>
    <div class="card">Output tokens<strong>{_fmt_int(total.usage.output_tokens)}</strong></div>
    <div class="card">API-equivalent cost<strong>${total.cost.total_usd:.4f}</strong></div>
  </div>
  {comparison_html}
  {_table_section("Daily Usage", daily_rows)}
  {_table_section("Hourly Usage", hourly_rows)}
  {_table_section("Project Usage", project_rows)}
  {_table_section("Model Usage", model_rows)}
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
        return f"<h2>{html.escape(title)}</h2><p class=\"muted\">No usage found.</p>"
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
        f"<h2>{html.escape(title)}</h2>"
        "<table><thead><tr><th>Label</th><th class=\"num\">Total</th><th class=\"num\">Input</th>"
        "<th class=\"num\">Cached</th><th class=\"num\">Output</th><th class=\"num\">Cost</th>"
        "<th class=\"num\">Unpriced</th><th>Share</th>"
        "</tr></thead><tbody>"
        + "".join(table_rows)
        + "</tbody></table>"
    )


def _fmt_int(value: int) -> str:
    return f"{value:,}"
