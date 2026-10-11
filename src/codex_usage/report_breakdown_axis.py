"""Fixed-font HTML ticks positioned on the chart's actual UTC time domain."""
import html
from datetime import datetime, timedelta


def timestamp_label(at, timezone):
    return datetime.fromtimestamp(at, timezone).strftime("%Y-%m-%d %H:%M:%S %z")


def time_axis(start, end, timezone, *, daily=False):
    ticks = []
    candidates = [start]
    local = datetime.fromtimestamp(start, timezone)
    at = local.replace(hour=0, minute=0, second=0, microsecond=0)
    step = timedelta(days=1) if daily or end-start > 86400 else timedelta(hours=1)
    while at.timestamp() < end:
        if start < at.timestamp() < end:
            candidates.append(at.timestamp())
        at += step
    if end > start:
        candidates.append(end)
    selected = [start, end] if end > start else [start]
    for fraction in (.5, .25, .75):
        target = start + fraction*(end-start)
        candidate = min(candidates, key=lambda t: abs(t-target))
        if all(abs(candidate-t) >= (end-start)*.18 for t in selected):
            selected.append(candidate)
    selected.sort()
    center = min(selected[1:-1], key=lambda t: abs(t-(start+end)/2)) if len(selected) > 2 else None
    for index, at in enumerate(selected):
        fraction = (at-start)/max(.000001, end-start)
        local = datetime.fromtimestamp(at, timezone)
        label = local.strftime("%b %d") if daily else local.strftime("%b %d<br>%H:%M<br>%z")
        anchor = "first" if fraction == 0 else "last" if fraction == 1 else "middle"
        secondary = " ub-tick-center" if at == center else " ub-tick-secondary" if index not in (0, len(selected)-1) else ""
        exact = timestamp_label(at, timezone)
        ticks.append(f'<span class="ub-tick {anchor}{secondary}" style="left:{fraction * 100:g}%" data-at="{at:.6f}" title="{html.escape(exact)}"><span>{label}</span></span>')
    return f'<div class="ub-time-axis" data-start="{start:.6f}" data-end="{end:.6f}" aria-label="Time axis">{"".join(ticks)}</div>'
