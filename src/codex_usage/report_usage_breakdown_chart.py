"""Fixed-size, visibly bounded charts; semantic exact values live beside them."""
import html
from codex_usage.model_presentation import model_color
from codex_usage.report_breakdown_axis import time_axis
from codex_usage.report_breakdown_numbers import metric_label, numeric_axis, tick_ceiling
from codex_usage.report_breakdown_hover import bucket_hover, css as hover_css
from codex_usage.report_breakdown_overlay import CapturedLayer, captured_layer
from codex_usage.report_breakdown_layout import axis_linked_chart


# Separate project/account palette; retained for callers of the overlay API.
COLORS = ("#087ea4", "#bf4565", "#24896e", "#a57515", "#7855b6", "#df6c32", "#56859c")


def plot(bars, *, metric, labels, links=None, title="", height=180, incomplete=None, intervals=None, display_names=None, bucket_labels=None, bucket_details=None, timezone=None, daily=False, account_points=(), account_overlay="none", color_domain="model"):
    observed_maximum = max((sum(v.values()) for v in bars), default=0)
    maximum = tick_ceiling(observed_maximum)
    width = 720
    step = width / max(1, len(bars))
    slots = {label: (model_color(label) if color_domain == "model" else
        "var(--model-7)" if label == "__other_projects__" else COLORS[i % len(COLORS)])
        for i, label in enumerate(labels)}
    marks = []
    hover_targets = []
    for index, values in enumerate(bars):
        local_step = step
        left = index * step
        if intervals:
            domain_start, domain_end = intervals[0][0], intervals[-1][1]
            left = (intervals[index][0] - domain_start) / max(.000001, domain_end - domain_start) * width
            local_step = (intervals[index][1] - intervals[index][0]) / max(.000001, domain_end - domain_start) * width
        bar_width = local_step * .5
        x, bottom = left + (local_step-bar_width)/2, height
        parts = []
        context = (bucket_labels or [title] * len(bars))[index]
        details = (bucket_details or [""] * len(bars))[index]
        for label, value in values.items():
            display = (display_names or {}).get(label, label)
            exact = html.escape(f'{context} | {display}: {metric_label(value, metric)} | {details}')
            size = value / maximum * height
            if value <= 0:
                continue
            if size < 1 or bar_width < 1:
                parts.append(f'<line class="ub-tiny-segment" x1="{x:.3f}" x2="{x+bar_width:.3f}" y1="{bottom:.3f}" y2="{bottom:.3f}" stroke="{slots[label]}" stroke-width=".75" vector-effect="non-scaling-stroke"><desc>{exact} (below chart resolution)</desc></line>')
            else:
                parts.append(f'<rect x="{x:.3f}" y="{bottom - size:.3f}" width="{bar_width:.3f}" height="{size:.6f}" fill="{slots[label]}"><desc>{exact}</desc></rect>')
            bottom -= size
        if incomplete and incomplete[index]:
            unknown_label = "Unknown estimated credits; not known zero" if metric == "credits" else "Unknown or API-excluded cost; not zero"
            parts.append(f'<path d="M{x + bar_width/2:.3f},{height - 5} l4,5 l-4,5 l-4,-5 z" fill="none" stroke="var(--text)" vector-effect="non-scaling-stroke"><desc>{html.escape(context + " | " + details)} | {unknown_label}</desc></path>')
        inspection = html.escape(f'Inspect {context} | total {metric_label(sum(values.values()), metric)} | {details}', quote=True)
        if not parts:
            parts.append(f'<rect x="{x:.3f}" y="0" width="{bar_width:.3f}" height="{height}" fill="transparent"><desc>{inspection} | no captured local usage; not proof of zero account workload</desc></rect>')
        marks.append("".join(parts))
        stack_height = sum(values.values()) / maximum * height
        hit_height = max(6, stack_height) if values else height
        hover_targets.append(bucket_hover(context, values, metric, slots, display_names or {},
            left=x/width*100, width=bar_width/width*100, top=height-hit_height+7,
            height=hit_height, center=(x+bar_width/2)/width*100,
            href=links[index] if links else None, incomplete=bool(incomplete and incomplete[index])))
    grid = ''.join(f'<line x1="0" x2="{width}" y1="{height * f}" y2="{height * f}" stroke="var(--border)"/>' for f in (0, .5, 1))
    scale = (numeric_axis([maximum, maximum / 2, 0], unit=metric)
             if observed_maximum else '<span>No known values</span><span></span><span>0 known</span>')
    layer = captured_layer(account_points, account_overlay, intervals[0][0], intervals[-1][1],
        timezone, COLORS, height=height, compact_key=True) if intervals else CapturedLayer()
    visible = {label for bar in bars for label in bar}
    content = axis_linked_chart(metric=metric, title=title, scale=scale, usage_marks="".join(marks),
        layer=layer, grid=grid,
        timeline=time_axis(intervals[0][0], intervals[-1][1], timezone, daily=daily) if intervals else "",
        labels=[((display_names or {}).get(label, label), slots[label]) for label in labels
            if not display_names or label in visible], width=width, height=height, kind=account_overlay,
        hover_targets="".join(hover_targets))
    return content


def css():
    return """<style>
    .usage-breakdown {min-width:0;margin:20px 0; border-top:1px solid var(--border);padding-top:18px}
    .usage-breakdown h2 {font-size:18px}.usage-breakdown h3 {font-size:14px;margin:14px 0 8px}
    .ub-controls,.ub-window {display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:10px 0}
    .ub-segment {display:inline-flex;border:1px solid var(--border);border-radius:4px}
    .ub-window-picker {font-size:12px;max-width:100%;margin:0!important}
    .ub-window-picker>div {display:grid;max-height:240px;overflow:auto;max-width:100%;border-left:2px solid var(--border)}
    .ub-window-picker a {overflow-wrap:anywhere}
    .ub-controls a,.ub-window a {padding:5px 8px;color:var(--accent);font-size:12px;text-decoration:none}
    .usage-breakdown a:focus-visible {outline:2px solid var(--accent)}
    .usage-breakdown a[aria-current=true] {background:var(--surface-soft);color:var(--text);font-weight:650}
    .ub-note,.ub-unit,.ub-window, .usage-breakdown small {font-size:12px;color:var(--muted);overflow-wrap:anywhere}
    .ub-chart {display:grid;grid-template-columns:94px minmax(0,1fr);margin:8px 0 4px}
    .ub-chart.ub-shared {grid-template-columns:94px minmax(0,1fr) 94px}
    .ub-right-axis {padding:0 0 0 8px!important;text-align:left!important}
    .ub-axis .ub-scale {overflow-wrap:anywhere;position:absolute;top:190px;max-width:90px;font-size:10px}
    .ub-axis {position:relative}
    .ub-axis {height:180px;display:flex;flex-direction:column;justify-content:space-between;padding-right:8px;text-align:right;font-size:12px;line-height:14px}
    .ub-scroll {overflow:visible;padding:3px 0;min-width:0}

    .ub-scroll svg {display:block;overflow:visible}.ub-bounds {display:flex;justify-content:space-between;gap:16px;font-size:12px;margin:6px 0 14px;overflow-wrap:anywhere}.ub-bounds span {min-width:0;max-width:48%}
    .ub-time-axis {position:relative;height:calc(14px + var(--ub-tick-rows,2)*15px);margin-top:5px;font-size:12px;line-height:15px}
    .ub-time-context {font-size:12px;color:var(--muted);line-height:17px;margin:3px 0 8px;overflow-wrap:anywhere}
    .ub-tick {position:absolute;top:0;width:0;height:5px;border-left:1px solid var(--muted)}
    .ub-tick>span {position:absolute;top:7px;white-space:nowrap;text-align:center;width:82px}
    .ub-tick.first>span {left:0;text-align:left}.ub-tick.middle>span {left:-41px}.ub-tick.last>span {left:-82px;text-align:right}
    .ub-tick.last>span {transform:translateX(-1px)}
    .ub-legend {display:flex;flex-wrap:wrap;gap:8px 14px;margin:8px 0;font-size:12px}
    .ub-legend span {overflow-wrap:anywhere}.ub-legend i {display:inline-block;width:10px;height:10px;margin-right:5px}
    .ub-legend .ub-account-swatch {width:7px;height:7px;border-radius:50%}.ub-meter-legend {color:var(--text)}
    .ub-account-point {stroke-width:1;vector-effect:non-scaling-stroke}
    .ub-account-point:hover {r:3px;stroke-width:2}.ub-account-title {color:var(--text)}
    .ub-rank {display:grid;grid-template-columns:minmax(100px,190px) minmax(60px,1fr) minmax(70px,110px);gap:8px;align-items:center;margin:10px 0;font-size:12px}
    .ub-rank a {overflow-wrap:anywhere}.ub-stack {display:flex;height:18px;min-width:0;background:var(--surface-soft)}
    .ub-rank strong {text-align:right;font-size:12px;overflow-wrap:anywhere}.usage-breakdown td {font-size:12px}
    .usage-breakdown table {font-variant-numeric:tabular-nums}.usage-breakdown details {margin:10px 0}
    .usage-breakdown summary {cursor:pointer}.ub-hour-labels {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;font-size:12px}
    @media(max-width:900px) {.ub-tick-secondary {display:none}}
    @media(max-width:560px) {.ub-chart {grid-template-columns:72px minmax(0,1fr)}.ub-chart.ub-shared {grid-template-columns:72px minmax(0,1fr) 72px}.ub-tick-secondary,.ub-tick-center {display:none}.ub-rank {grid-template-columns:100px minmax(40px,1fr) 75px}.ub-controls {gap:6px}.ub-hour-labels {grid-template-columns:repeat(2,minmax(0,1fr))}}
    </style>""" + hover_css()
