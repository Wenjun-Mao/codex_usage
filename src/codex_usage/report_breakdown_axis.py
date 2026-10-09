"""Fixed-font HTML ticks positioned on the chart's actual UTC time domain."""
import html
from datetime import datetime


def timestamp_label(at, timezone):
    return datetime.fromtimestamp(at, timezone).strftime("%Y-%m-%d %H:%M:%S %z")


def time_axis(start, end, timezone, *, daily=False):
    ticks = []
    fractions = (0, .25, .5, .75, 1) if end > start else (0,)
    for fraction in fractions:
        at = start + fraction * (end - start)
        local = datetime.fromtimestamp(at, timezone)
        label = local.strftime("%b %d<br>%H:%M") if daily else local.strftime("%H:%M<br>%z")
        anchor = "first" if fraction == 0 else "last" if fraction == 1 else "middle"
        secondary = " ub-tick-secondary" if fraction in (.25, .75) else ""
        exact = timestamp_label(at, timezone)
        ticks.append(f'<span class="ub-tick {anchor}{secondary}" style="left:{fraction * 100:g}%" data-at="{at:.6f}" title="{html.escape(exact)}"><span>{label}</span></span>')
    return f'<div class="ub-time-axis" data-start="{start:.6f}" data-end="{end:.6f}" aria-label="Time axis">{"".join(ticks)}</div>'
