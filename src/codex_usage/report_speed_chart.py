"""Responsive, script-free timing geometry and collision-spaced calendar ticks."""
import html
from datetime import date
from math import ceil, floor, log10

PLOT_HEIGHT = 224
PLOT_TOP = 10
PLOT_SPAN = 200


def nice_scale(points):
    maximum = max((point["p75"] for point in points if point["median"] is not None), default=1)
    raw = max(maximum * 1.08 / 4, .01)
    magnitude = 10 ** floor(log10(raw))
    step = next(value * magnitude for value in (1, 2, 2.5, 5, 10) if value * magnitude >= raw)
    ceiling = ceil(maximum * 1.08 / step) * step
    return ceiling, [step * index for index in range(round(ceiling / step) + 1)]


def x_position(index, count):
    return 50 if count == 1 else 2 + index * 96 / (count - 1)


def tick_indices(buckets, granularity, budget):
    count = len(buckets)
    if count <= 1:
        return list(range(count))
    candidates = list(range(count))
    if granularity == "hourly" and count > 30:
        candidates = [0, *[i for i, bucket in enumerate(buckets) if "T00:00:" in bucket], count - 1]
    capacity = min(7, max(2, budget // 72), count)
    chosen = {0, count - 1}
    for index in range(1, capacity - 1):
        target = index * (count - 1) / (capacity - 1)
        chosen.add(min(candidates, key=lambda candidate: abs(candidate - target)))
    # Endpoints are mandatory; remove crowded interior ticks instead of appending
    # the last date to a cadence that has already put a label beside it.
    result = [0]
    for index in sorted(chosen - {0, count - 1}):
        if min(index - result[-1], count - 1 - index) * budget / (count - 1) >= 72:
            result.append(index)
    result.append(count - 1)
    return result


def tick_html(buckets, granularity):
    groups = []
    for name, budget in (("wide", 550), ("medium", 350), ("compact", 220)):
        ticks = []
        for index in tick_indices(buckets, granularity, budget):
            bucket = buckets[index]
            day = bucket[5:10]
            clock = f'<span>{bucket[11:16]}</span>' if granularity == "hourly" else ""
            edge = "first" if index == 0 else "last" if index == len(buckets) - 1 else "middle"
            if len(buckets) == 1:
                edge = "middle"
            ticks.append(f'<time class="speed-tick speed-tick-{edge}" datetime="{html.escape(bucket, quote=True)}" '
                         f'title="{html.escape(bucket, quote=True)}" style="left:{x_position(index, len(buckets)):.4f}%">'
                         f'<span>{day}</span>{clock}</time>')
        groups.append(f'<div class="speed-ticks speed-ticks-{name}">{"".join(ticks)}</div>')
    return f'<div class="speed-x-axis">{"".join(groups)}</div>'


def date_label(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first == last:
        return f'{first:%b} {first.day}, {first.year}'
    first_year = f", {first.year}" if first.year != last.year else ""
    return f'{first:%b} {first.day}{first_year} - {last:%b} {last.day}, {last.year}'


def selection_band(buckets, start, end):
    if len(buckets) == 1:
        left, right = 0, 100
    else:
        indices = [i for i, bucket in enumerate(buckets) if start <= bucket <= end]
        if not indices:
            return ""
        half = 48 / (len(buckets) - 1)
        left = max(0, x_position(indices[0], len(buckets)) - half)
        right = min(100, x_position(indices[-1], len(buckets)) + half)
    return (f'<rect class="speed-selection" x="{left:.4f}%" y="0" '
            f'width="{right - left:.4f}%" height="100%"/>')


def render_plot(points, buckets, models, slots, detail, *, overview=False, highlight=None):
    lookup = {(point["model"], point["bucket"]): point for point in points}
    bucket_set = set(buckets)
    selected = [point for point in points if point["bucket"] in bucket_set]
    ceiling, ticks = nice_scale(selected)
    height, top, span = (54, 6, 42) if overview else (PLOT_HEIGHT, PLOT_TOP, PLOT_SPAN)
    marks, rows = [], []
    if highlight:
        marks.append(selection_band(buckets, *highlight))
    if not overview:
        for value in ticks:
            y = top + span * (1 - value / ceiling)
            marks.append(f'<line x1="0" y1="{y:.2f}" x2="100%" y2="{y:.2f}" class="speed-grid"/>')
    for model in models:
        color = f"var(--model-{slots[model]})"
        previous = None
        for index, bucket in enumerate(buckets):
            point = lookup.get((model, bucket))
            if not point or point["median"] is None:
                previous = None
                continue
            x = x_position(index, len(buckets))
            y = top + span * (1 - point["median"] / ceiling)
            if previous:
                marks.append(f'<line x1="{previous[0]:.4f}%" y1="{previous[1]:.2f}" '
                             f'x2="{x:.4f}%" y2="{y:.2f}" stroke="{color}" stroke-width="2"/>')
            previous = (x, y)
            label = html.escape(f"{model}, {bucket}: {detail(point)}", quote=True)
            dash = ' stroke-dasharray="2 2"' if point["small"] else ""
            if overview:
                marks.append(f'<circle cx="{x:.4f}%" cy="{y:.2f}" r="2.5" fill="{color}" '
                             f'role="img" aria-label="{label}"><title>{label}</title></circle>')
                continue
            target = f"speed-detail-{len(rows)}"
            marks.append(f'<line x1="{x:.4f}%" x2="{x:.4f}%" '
                         f'y1="{top + span * (1 - point["p25"] / ceiling):.2f}" '
                         f'y2="{top + span * (1 - point["p75"] / ceiling):.2f}" '
                         f'stroke="{color}" opacity=".45" stroke-width="4"/>')
            marks.append(f'<a href="#{target}" tabindex="0" aria-label="{label}">'
                         f'<circle cx="{x:.4f}%" cy="{y:.2f}" r="4" fill="var(--surface)" '
                         f'stroke="{color}" stroke-width="2"{dash}><title>{label}</title></circle></a>')
            rows.append(f'<tr id="{target}" tabindex="0"><th scope="row">{html.escape(model)}</th>'
                        f'<td>{html.escape(bucket)}</td><td>{point["median"]:.1f}</td>'
                        f'<td>{point["p25"]:.1f}-{point["p75"]:.1f}</td><td>{point["n"]}</td>'
                        f'<td>{point["tasks"]}</td><td>{point["sources"]}</td></tr>')
    label = "Daily overview of the selected range" if overview else "Median observed output tokens per second"
    svg = (f'<svg width="100%" height="{height}" role="group" aria-label="{label}">'
           f'{"".join(marks)}</svg>')
    if overview:
        return svg, rows
    axis = "".join(f'<span style="top:{top + span * (1 - value / ceiling):.2f}px">{value:g}</span>' for value in reversed(ticks))
    granularity = "hourly" if buckets and "T" in buckets[0] else "daily"
    return (f'<div class="speed-chart"><div class="speed-unit">tok/s</div>'
            f'<div class="speed-chart-grid"><div class="speed-y-axis" aria-hidden="true">{axis}</div>'
            f'<div class="speed-plot">{svg}{tick_html(buckets, granularity)}</div></div></div>'), rows
