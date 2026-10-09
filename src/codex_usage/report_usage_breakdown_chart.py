"""Fixed-size, visibly bounded charts; semantic exact values live beside them."""
import html
from datetime import datetime
from codex_usage.report_breakdown_axis import time_axis, timestamp_label


COLORS = ("#087ea4", "#bf4565", "#24896e", "#a57515", "#7855b6", "#df6c32", "#56859c")


def plot(bars, *, metric, labels, links=None, title="", height=180, incomplete=None, intervals=None, display_names=None, bucket_labels=None, bucket_details=None, timezone=None, daily=False):
    observed_maximum = max((sum(v.values()) for v in bars), default=0)
    maximum = observed_maximum or 1
    width = 720
    step = width / max(1, len(bars))
    slots = {label: COLORS[i % len(COLORS)] for i, label in enumerate(labels)}
    marks = []
    tiny = False
    for index, values in enumerate(bars):
        local_step = step
        left = index * step
        if intervals:
            domain_start, domain_end = intervals[0][0], intervals[-1][1]
            left = (intervals[index][0] - domain_start) / max(.000001, domain_end - domain_start) * width
            local_step = (intervals[index][1] - intervals[index][0]) / max(.000001, domain_end - domain_start) * width
        x, bottom = left + local_step * .15, height
        parts = []
        context = (bucket_labels or [title] * len(bars))[index]
        details = (bucket_details or [""] * len(bars))[index]
        for label, value in values.items():
            display = (display_names or {}).get(label, label)
            exact = html.escape(f'{context} | {display}: {value:.9g} {metric} | {details}')
            size = value / maximum * height
            if value <= 0:
                continue
            if size < 1:
                tiny = True
                parts.append(f'<circle cx="{x + local_step * .35:.3f}" cy="{bottom:.3f}" r="2.5" fill="none" stroke="{slots[label]}" vector-effect="non-scaling-stroke"><title>{exact} (below chart resolution)</title></circle>')
            else:
                parts.append(f'<rect x="{x:.3f}" y="{bottom - size:.3f}" width="{local_step * .7:.3f}" height="{size:.6f}" fill="{slots[label]}"><title>{exact}</title></rect>')
            bottom -= size
        if incomplete and incomplete[index]:
            parts.append(f'<path d="M{x + local_step * .35:.3f},{height - 5} l4,5 l-4,5 l-4,-5 z" fill="none" stroke="var(--text)" vector-effect="non-scaling-stroke"><title>{html.escape(context + " | " + details)} | Unknown or API-excluded cost; not zero</title></path>')
        inspection = html.escape(f'Inspect {context} | total {sum(values.values()):.9g} {metric} | {details}', quote=True)
        marks.append((f'<a href="{html.escape(links[index], quote=True)}" aria-label="{inspection}"><title>{inspection}</title>' if links else "") + "".join(parts) + ("</a>" if links else ""))
    grid = ''.join(f'<line x1="0" x2="{width}" y1="{height * f}" y2="{height * f}" stroke="var(--border)"/>' for f in (0, .5, 1))
    unit = "Tokens" if metric == "tokens" else "Known API-equivalent USD"
    scale = (f'<span>{maximum:,.6g}</span><span>{maximum / 2:,.6g}</span><span>0</span>'
             if observed_maximum else '<span>No known values</span><span></span><span>0 known</span>')
    return (f'<div class="ub-unit">{html.escape(title)} &middot; {unit}</div><div class="ub-chart">'
            f'<div class="ub-axis">{scale}</div>'
            f'<div class="ub-scroll"><svg width="100%" height="{height}" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="{html.escape(title)}; 0 to {observed_maximum:.9g} known values">{grid}{"".join(marks)}</svg>'
            + (time_axis(intervals[0][0], intervals[-1][1], timezone, daily=daily) if intervals else "") + '</div></div>'
            + ('<small>Open markers: nonzero values below chart resolution. Exact values remain in details.</small>' if tiny else ""))


def meter(points, start, end, timezone, *, weekly_identity=None):
    width, height = 720, 140
    marks, rows = [], []
    weekly = [p for p in points if p["duration_minutes"] == 10080 and
        (weekly_identity is None or (p["limit_id"], p["plan"]) == weekly_identity)]
    series = sorted({(p["limit_id"], p["duration_minutes"], p["plan"]) for p in weekly},
        key=lambda s: (s[0], s[1] is None, s[1] or 0, s[2] is None, s[2] or ""))
    for point in points:
        at = datetime.fromisoformat(point["timestamp"])
        remaining = 100 - point["used_percent"]
        x = (at.timestamp() - start) / max(.000001, end - start) * width
        duration = f'{point["duration_minutes"]} min' if point["duration_minutes"] is not None else 'duration unavailable'
        label = f'{timestamp_label(at.timestamp(), timezone)} · {point["limit_id"]} / {duration} / {point["plan"] or "plan unavailable"} · slot {point["slot"]} · {remaining:g}% remaining · {point["provenance"]}'
        if point in weekly:
            color = COLORS[series.index((point["limit_id"], point["duration_minutes"], point["plan"])) % len(COLORS)]
            marks.append(f'<circle cx="{x:.3f}" cy="{height * (1 - remaining / 100):.3f}" r="3" fill="{color}" role="img" aria-label="{html.escape(label, quote=True)}"><title>{html.escape(label)}</title></circle>')
        rows.append(f'<tr><td>{html.escape(label)}</td><td>{point["used_percent"]:g}% used</td><td>{point["resets_at"] if point["resets_at"] is not None else "Unknown reset"}</td></tr>')
    grid = ''.join(f'<line x1="0" x2="{width}" y1="{height * f}" y2="{height * f}" stroke="var(--border)"/>' for f in (0, .5, 1))
    legend = '<div class="ub-legend ub-meter-legend">' + ''.join(f'<span><i style="background:{COLORS[i % len(COLORS)]}"></i>{html.escape(limit)} · weekly · {html.escape(plan or "plan unavailable")}</span>' for i, (limit, _, plan) in enumerate(series)) + '</div>'
    return ('<h3>Captured weekly allowance remaining · account-wide</h3>'
            '<small>Captured points only; no interpolation across corrections or resets.</small>'
            + f'<div class="ub-chart ub-meter"><div class="ub-axis"><span>100%</span><span>50%</span><span>0%</span></div><div class="ub-scroll"><svg width="100%" height="{height}" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="Captured account-wide allowance remaining, 0 to 100 percent">{grid}{"".join(marks)}</svg>{time_axis(start, end, timezone)}</div></div>'
            + (legend if weekly else '<p>Weekly allowance unavailable: no supported weekly readings on this time domain.</p>')
            + f'<details><summary>Exact captured readings ({len(points)})</summary><div class="table-wrap"><table><thead><tr><th>Reading / source / series</th><th>Reported used</th><th>Reset Unix seconds</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>')


def css():
    return """<style>
    .usage-breakdown {min-width:0;margin:20px 0; border-top:1px solid var(--border);padding-top:18px}
    .usage-breakdown h2 {font-size:18px}.usage-breakdown h3 {font-size:14px;margin:14px 0 8px}
    .ub-controls,.ub-window {display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:10px 0}
    .ub-segment {display:inline-flex;border:1px solid var(--border);border-radius:4px}
    .ub-controls a,.ub-window a {padding:5px 8px;color:var(--accent);font-size:12px;text-decoration:none}
    .usage-breakdown a:focus-visible {outline:2px solid var(--accent)}
    .usage-breakdown a[aria-current=true] {background:var(--surface-soft);color:var(--text);font-weight:650}
    .ub-note,.ub-unit,.ub-window, .usage-breakdown small {font-size:12px;color:var(--muted);overflow-wrap:anywhere}
    .ub-chart {display:grid;grid-template-columns:70px minmax(0,1fr);margin:8px 0 4px}
    .ub-axis {height:180px;display:flex;flex-direction:column;justify-content:space-between;padding-right:8px;text-align:right;font-size:12px;line-height:14px}
    .ub-meter .ub-axis {height:140px}.ub-scroll {overflow:auto;padding:3px 0;min-width:0}
    .ub-scroll svg {display:block;overflow:visible}.ub-bounds {display:flex;justify-content:space-between;gap:16px;font-size:12px;margin:6px 0 14px;overflow-wrap:anywhere}.ub-bounds span {min-width:0;max-width:48%}
    .ub-time-axis {position:relative;height:38px;margin-top:5px;font-size:12px;line-height:15px}
    .ub-tick {position:absolute;top:0;width:0;height:5px;border-left:1px solid var(--muted)}
    .ub-tick>span {position:absolute;top:7px;white-space:nowrap;text-align:center;width:64px}
    .ub-tick.first>span {left:0;text-align:left}.ub-tick.middle>span {left:-32px}.ub-tick.last>span {left:-64px;text-align:right}
    .ub-legend {display:flex;flex-wrap:wrap;gap:8px 14px;margin:8px 0;font-size:12px}
    .ub-legend span {overflow-wrap:anywhere}.ub-legend i {display:inline-block;width:10px;height:10px;margin-right:5px}
    .ub-rank {display:grid;grid-template-columns:minmax(100px,190px) minmax(60px,1fr) minmax(70px,110px);gap:8px;align-items:center;margin:10px 0;font-size:12px}
    .ub-rank a {overflow-wrap:anywhere}.ub-stack {display:flex;height:18px;min-width:0;background:var(--surface-soft)}
    .ub-rank strong {text-align:right;font-size:12px;overflow-wrap:anywhere}.usage-breakdown td {font-size:12px}
    .usage-breakdown table {font-variant-numeric:tabular-nums}.usage-breakdown details {margin:10px 0}
    .usage-breakdown summary {cursor:pointer}.ub-hour-labels {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;font-size:12px}
    @media(max-width:560px) {.ub-tick-secondary {display:none}.ub-rank {grid-template-columns:100px minmax(40px,1fr) 75px}.ub-controls {gap:6px}.ub-hour-labels {grid-template-columns:repeat(2,minmax(0,1fr))}}
    </style>"""
