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
    first = datetime.fromtimestamp(start, timezone)
    last = datetime.fromtimestamp(max(start, end-.000001), timezone)
    single_day = first.date() == last.date()
    offsets = sorted({datetime.fromtimestamp(at, timezone).strftime("%z") for at in candidates})
    changing_offset = len(offsets) > 1
    for index, at in enumerate(selected):
        fraction = (at-start)/max(.000001, end-start)
        local = datetime.fromtimestamp(at, timezone)
        clock = "24:00" if single_day and local.date() > first.date() and local.hour == 0 else local.strftime("%H:%M")
        if changing_offset and not daily:
            clock += " " + local.strftime("%Z")
        label = local.strftime("%b %d") if daily else clock if single_day else local.strftime("%b %d<br>") + clock
        anchor = "first" if fraction == 0 else "last" if fraction == 1 else "middle"
        secondary = " ub-tick-center" if at == center else " ub-tick-secondary" if index not in (0, len(selected)-1) else ""
        exact = timestamp_label(at, timezone)
        ticks.append(f'<span class="ub-tick {anchor}{secondary}" style="left:{fraction * 100:g}%" data-at="{at:.6f}" title="{html.escape(exact)}"><span>{label}</span></span>')
    zone = str(timezone) + " · " + " / ".join("UTC" + value[:3] + ":" + value[3:] for value in offsets)
    caption = first.strftime("%b %d, %Y") + " · " + zone if single_day and not daily else zone
    return (f'<div class="ub-time-axis" style="--ub-tick-rows:{1 if daily or single_day else 2}" '
        f'data-start="{start:.6f}" data-end="{end:.6f}" aria-label="Time axis">{"".join(ticks)}</div>'
        f'<div class="ub-time-context">{html.escape(caption)}</div>')
