"""Accessible script-free SVG and semantic detail for observed speed."""
import html
import json
from datetime import date, timedelta
from urllib.parse import quote

from codex_usage.model_presentation import assign_model_color_slots, model_display_sort_key
from codex_usage.speed_queries import calendar_buckets
from codex_usage.report_speed_chart import date_label, render_plot


def summary_html(stats: dict | None) -> str:
    if not stats or stats["median"] is None:
        return '<span title="Fewer than five eligible responses">Unavailable</span>'
    label = detail(stats)
    marker = ' <small class="speed-small">Small sample</small>' if stats["small"] else ""
    return f'<span title="{html.escape(label, quote=True)}">{stats["median"]:.1f}</span>{marker}'


def detail(stats):
    if stats["median"] is None:
        return f'{stats["n"]} eligible responses; insufficient evidence'
    return (f'{stats["median"]:.1f} tok/s; middle 50% {stats["p25"]:.1f}-{stats["p75"]:.1f}; '
            f'{stats["n"]} responses; {stats["tasks"]} tasks; {stats["sources"]} sources'
            + ("; small sample" if stats["small"] else ""))


def command(nav, granularity, window_start=None, label=""):
    args = {"scope": nav["scope"], "granularity": granularity,
            "windowStart": window_start or nav["window_start"]}
    uri = "command:codexUsage.navigateSpeed?" + quote(json.dumps([args], separators=(",", ":")), safe="")
    selected = ' aria-current="true"' if granularity == nav["granularity"] and not window_start else ""
    return f'<a href="{html.escape(uri, quote=True)}"{selected}>{html.escape(label or granularity.title())}</a>'


def render_speed(aggregates, nav, status, timezone):
    models = sorted(aggregates["summaries"], key=model_display_sort_key)
    slots = assign_model_color_slots(tuple(models[:7]))
    slots.update({m: i % 7 for i, m in enumerate(models[7:])})
    buckets = calendar_buckets(nav, timezone)
    chart, rows = render_plot(aggregates[nav["granularity"]], buckets, models, slots, detail)
    legend = "".join(f'<span><i style="background:var(--model-{slots[m]})"></i>{html.escape(m)}</span>' for m in models)
    navigation = ""
    overview = ""
    full_range = date_label(nav["min_date"], nav["max_date"])
    total_days = (date.fromisoformat(nav["max_date"]) - date.fromisoformat(nav["min_date"])).days + 1
    days_label = "day" if total_days == 1 else "days"
    if nav["granularity"] == "hourly":
        previous = command(nav, "hourly", nav["previous"], "Previous") if nav["previous"] else '<span aria-disabled="true">Previous</span>'
        next_link = command(nav, "hourly", nav["next"], "Next") if nav["next"] else '<span aria-disabled="true">Next</span>'
        latest_start = max(date.fromisoformat(nav["min_date"]), date.fromisoformat(nav["max_date"]) - timedelta(days=6)).isoformat()
        latest = command(nav, "hourly", latest_start, "Latest week") if nav["window_start"] != latest_start else '<span aria-disabled="true">Latest week</span>'
        window_days = (date.fromisoformat(nav["window_end"]) - date.fromisoformat(nav["window_start"])).days + 1
        navigation = (f'<div class="speed-window"><div><strong>{nav["window_start"]} to {nav["window_end"]}</strong>'
                      f'<small>Hourly detail &middot; {window_days} of {total_days} {days_label}</small></div>'
                      f'<nav aria-label="Hourly window">{previous}{next_link}{latest}</nav></div>')
        if total_days > window_days:
            daily_nav = {**nav, "granularity": "daily"}
            daily_buckets = calendar_buckets(daily_nav, timezone)
            mini, _ = render_plot(aggregates["daily"], daily_buckets, models, slots, detail,
                                 overview=True, highlight=(nav["window_start"], nav["window_end"]))
            overview = (f'<div class="speed-overview"><div class="speed-overview-label">Daily overview &middot; {html.escape(full_range)}</div>'
                        f'{mini}<div class="speed-overview-dates"><span>{nav["min_date"]}</span><span>{nav["max_date"]}</span></div></div>')
    exclusions = "; ".join(f"{reason.replace('_', ' ')}: {n}" for reason, n in aggregates["reasons"].items()) or "None"
    coverage = (f'{status.get("complete", 0)} measured sources; {status.get("pending", 0)} pending; '
                f'{status.get("unmeasurable", 0)} unmeasurable. ')
    checked = status.get("complete", 0) + status.get("unmeasurable", 0)
    progress = f'Account-wide timing history: {checked:,} sources checked &middot; {status.get("pending", 0):,} pending'
    if not rows:
        chart = '<div class="speed-empty">No measurable speed in this window.</div>'
    return (
        '<section class="section observed-speed" aria-labelledby="observed-speed-heading">'
        '<div class="speed-heading"><h2 id="observed-speed-heading">Observed Output Speed</h2>'
        f'<nav class="speed-modes" aria-label="Speed granularity">{command(nav, "daily")}{command(nav, "hourly")}</nav></div>'
        f'<div class="speed-scope">{html.escape(full_range)} &middot; {total_days} {days_label}</div>'
        f'<div class="speed-legend">{legend}</div>{overview}{navigation}'
        f'{chart}<div class="speed-progress">{progress}</div>'
        + ('<p class="muted">No buckets with at least five eligible responses. Missing timing is not missing usage.</p>' if not rows else "")
        + f'<details class="speed-evidence"><summary>Timing evidence and coverage</summary><p>{html.escape(coverage)}Client-observed output-phase tokens per second, including reasoning once. Not server decode speed or task throughput. Efforts are pooled; client, workload, routing and unknown service tier can affect results. Responses need at least 500 output tokens and 10 ms per timed model item. The middle 50% shows variation, not a confidence interval. Dashed points have 5-19 responses; fewer than five leaves a gap.</p><p>Exclusions: {html.escape(exclusions)}.</p><div class="table-wrap"><table><thead><tr><th>Model</th><th>Local bucket (offset)</th><th>tok/s</th><th>Middle 50%</th><th>Responses</th><th>Tasks</th><th>Sources</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></details></section>'
    )


def speed_css():
    return """
    .observed-speed { min-width:0; margin-top:20px; }
    .speed-heading,.speed-window { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; }
    .speed-modes { display:flex; border:1px solid var(--border); border-radius:4px; }
    .speed-modes a,.speed-window a,.speed-window > span { padding:6px 10px; color:var(--muted); }
    .speed-modes a[aria-current] { background:var(--surface-soft); color:var(--text); font-weight:650; }
    .speed-scope,.speed-progress { color:var(--muted); font-size:12px; margin:8px 0; }
    .speed-window { margin:12px 0; font-size:12px; }.speed-window small { display:block; color:var(--muted); margin-top:4px; }
    .speed-window nav { display:flex; flex-wrap:wrap; gap:4px; }.speed-window a { border:1px solid var(--border); border-radius:4px; }
    .speed-window [aria-disabled] { opacity:.65; }
    .speed-legend { display:flex; gap:12px; flex-wrap:wrap; font-size:12px; margin:10px 0; }
    .speed-legend span { overflow-wrap:anywhere; }.speed-legend i { display:inline-block; width:9px; height:9px; margin-right:5px; }
    .speed-chart { container-type:inline-size; min-width:0; }.speed-unit { font-size:12px; color:var(--muted); margin-bottom:4px; }
    .speed-chart-grid { display:grid; grid-template-columns:44px minmax(0,1fr); }
    .speed-y-axis { position:relative; height:224px; font-size:12px; color:var(--muted); }
    .speed-y-axis span { position:absolute; right:8px; transform:translateY(-50%); }
    .speed-plot { min-width:0; padding:0 8px; }.speed-plot svg { display:block; width:100%; height:224px; overflow:visible; }
    .speed-grid { stroke:var(--border); }.speed-plot a:focus circle { stroke-width:4; fill:var(--text); }
    .speed-x-axis { position:relative; height:44px; color:var(--muted); font-size:12px; }
    .speed-ticks { position:absolute; inset:0; }.speed-ticks-medium,.speed-ticks-compact { display:none; }
    .speed-tick { position:absolute; top:8px; white-space:nowrap; line-height:16px; text-align:center; transform:translateX(-50%); }
    .speed-tick span { display:block; }.speed-tick-first { transform:none; text-align:left; }.speed-tick-last { transform:translateX(-100%); text-align:right; }
    @container(max-width:650px) { .speed-ticks-wide { display:none; }.speed-ticks-medium { display:block; } }
    @container(max-width:400px) { .speed-ticks-medium { display:none; }.speed-ticks-compact { display:block; } }
    .speed-overview { margin:14px 0; }.speed-overview-label,.speed-overview-dates { font-size:11px; color:var(--muted); }
    .speed-overview svg { display:block; margin:6px 0; width:100%; height:54px; background:var(--surface-soft); }
    .speed-selection { fill:var(--highlight); fill-opacity:.12; stroke:var(--highlight); stroke-opacity:.5; }
    .speed-overview-dates { display:flex; justify-content:space-between; gap:12px; }
    .speed-empty { padding:28px 0; color:var(--muted); font-size:13px; }
    .speed-evidence { margin:10px 0; font-size:12px; }
    .speed-evidence summary { cursor:pointer; }.speed-small { display:block; color:var(--highlight); font-size:10px; }
    .speed-evidence tr:target { outline:2px solid var(--highlight); }
    @media(max-width:430px) { .speed-heading h2 { font-size:18px; }.speed-window { gap:4px; } }
    """
