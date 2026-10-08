"""Accessible script-free SVG and semantic detail for observed speed."""
import html
import json
from urllib.parse import quote

from codex_usage.model_presentation import assign_model_color_slots, model_display_sort_key
from codex_usage.speed_queries import calendar_buckets


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
    bucket_set = set(buckets)
    points = {(p["model"], p["bucket"]): p for p in aggregates[nav["granularity"]]}
    width, height = max(720, len(buckets) * 9 + 90), 280
    eligible = [p for (m, b), p in points.items() if b in bucket_set and p["median"] is not None]
    ymax = max((p["p75"] for p in eligible), default=1) * 1.1
    svg = []
    for fraction in (0, .25, .5, .75, 1):
        y = 230 - fraction * 200
        svg.append(f'<line x1="55" y1="{y}" x2="{width - 15}" y2="{y}" class="speed-grid"/><text x="48" y="{y + 4}" text-anchor="end">{fraction * ymax:.1f}</text>')
    rows = []
    for model in models:
        color = f"var(--model-{slots[model]})"
        previous = None
        for i, bucket in enumerate(buckets):
            point = points.get((model, bucket))
            if not point or point["median"] is None:
                previous = None
                continue
            x = 60 + i * (width - 90) / max(1, len(buckets) - 1)
            y = 230 - point["median"] / ymax * 200
            if previous:
                svg.append(f'<line x1="{previous[0]:.2f}" y1="{previous[1]:.2f}" x2="{x:.2f}" y2="{y:.2f}" stroke="{color}" stroke-width="2"/>')
            previous = (x, y)
            label = f"{model}, {bucket}: {detail(point)}"
            target = f"speed-detail-{len(rows)}"
            dash = ' stroke-dasharray="2 2"' if point["small"] else ""
            svg.append(f'<line x1="{x:.2f}" x2="{x:.2f}" y1="{230 - point["p25"] / ymax * 200:.2f}" y2="{230 - point["p75"] / ymax * 200:.2f}" stroke="{color}" opacity=".45" stroke-width="4"/>')
            svg.append(f'<a href="#{target}" tabindex="0" aria-label="{html.escape(label, quote=True)}"><circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="var(--surface)" stroke="{color}" stroke-width="2"{dash}><title>{html.escape(label)}</title></circle></a>')
            rows.append(f'<tr id="{target}" tabindex="0"><th scope="row">{html.escape(model)}</th><td>{html.escape(bucket)}</td><td>{point["median"]:.1f}</td><td>{point["p25"]:.1f}-{point["p75"]:.1f}</td><td>{point["n"]}</td><td>{point["tasks"]}</td><td>{point["sources"]}</td></tr>')
    for i, bucket in enumerate(buckets):
        if i % max(1, len(buckets) // 7) == 0 or i == len(buckets) - 1:
            x = 60 + i * (width - 90) / max(1, len(buckets) - 1)
            label = bucket[5:10] if nav["granularity"] == "daily" else bucket[5:16].replace("T", " ")
            svg.append(f'<text x="{x:.2f}" y="254" text-anchor="middle">{html.escape(label)}</text>')
    legend = "".join(f'<span><i style="background:var(--model-{slots[m]})"></i>{html.escape(m)}</span>' for m in models)
    navigation = ""
    if nav["granularity"] == "hourly":
        previous = command(nav, "hourly", nav["previous"], "Previous") if nav["previous"] else '<span aria-disabled="true">Previous</span>'
        next_link = command(nav, "hourly", nav["next"], "Next") if nav["next"] else '<span aria-disabled="true">Next</span>'
        navigation = f'<div class="speed-window">{previous}<strong>{nav["window_start"]} to {nav["window_end"]}</strong>{next_link}</div>'
    exclusions = "; ".join(f"{reason.replace('_', ' ')}: {n}" for reason, n in aggregates["reasons"].items()) or "None"
    coverage = (f'{status.get("complete", 0)} measured sources; {status.get("pending", 0)} pending; '
                f'{status.get("unmeasurable", 0)} unmeasurable. ')
    return (
        '<section class="section observed-speed" aria-labelledby="observed-speed-heading">'
        '<div class="speed-heading"><h2 id="observed-speed-heading">Observed Output Speed</h2>'
        f'<nav class="speed-modes" aria-label="Speed granularity">{command(nav, "daily")}{command(nav, "hourly")}</nav></div>'
        f'{navigation}<div class="speed-legend">{legend}</div>'
        '<div class="speed-scroll" tabindex="0" aria-label="Observed speed timeline">'
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="group" aria-label="Median observed output tokens per second"><text x="8" y="18">tok/s</text>{"".join(svg)}</svg></div>'
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
    .speed-window { margin:8px 0; font-size:12px; }.speed-legend { display:flex; gap:12px; flex-wrap:wrap; font-size:12px; margin:10px 0; }
    .speed-legend span { overflow-wrap:anywhere; }.speed-legend i { display:inline-block; width:9px; height:9px; margin-right:5px; }
    .speed-scroll { overflow-x:auto; max-width:100%; }.speed-scroll svg { display:block; }
    .speed-scroll text { fill:var(--muted); font-size:11px; }.speed-grid { stroke:var(--border); }
    .speed-scroll a:focus circle { stroke-width:4; fill:var(--text); }.speed-evidence { margin:10px 0; font-size:12px; }
    .speed-evidence summary { cursor:pointer; }.speed-small { display:block; color:var(--highlight); font-size:10px; }
    .speed-evidence tr:target { outline:2px solid var(--highlight); }
    @media(max-width:430px) { .speed-heading h2 { font-size:18px; }.speed-window { gap:4px; } }
    """
