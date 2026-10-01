"""Compact local-time presentation of independent conditional quota paces."""
from datetime import UTC, datetime
from html import escape

from codex_usage.allowance_pace import pace_state


def span_label(seconds):
    minutes = max(0, round(seconds / 60))
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def _message(pace, status, now, timezone):
    state = pace_state(pace, status, now)
    if state == "awaiting":
        return "Forecast awaiting fresh capture"
    if state == "reported full":
        return "Meter reports 100% used"
    if state == "unmeasurable":
        return "Pace not yet measurable"
    if state == "missing reset":
        return "Forecast awaiting fresh capture"
    exhaustion, reset = pace["exhaustion"], pace["reset"]
    if abs(exhaustion - reset) <= 900:
        return "At this pace, quota would run out near reset."
    if exhaustion < reset:
        local = datetime.fromtimestamp(round(exhaustion / 900) * 900, timezone)
        anchor_day = datetime.fromtimestamp(pace["anchor"], timezone).date()
        stamp = local.strftime("%Y-%m-%d %H:%M" if local.date() != anchor_day else "%H:%M")
        # Offset disambiguates repeated local times at the autumn DST transition.
        stamp += f" {local.tzname() or ''} ({local:%z})"
        return (f"At this pace, quota would run out around {stamp}, "
                f"about {span_label(reset - exhaustion)} before reset.")
    balance = pace["reset_balance"]
    remaining = "less than 1%" if round(balance) == 0 else f"{round(balance)}%"
    return f"At this pace, about {remaining} would remain at reset."


def pace_rows(paces, status, *, timezone, now=None):
    clock = (now or datetime.now(UTC)).timestamp()
    return ''.join(
        '<p class="allowance-pace">'
        f'<strong>{escape(p["name"])} pace · {span_label(p["span_seconds"])} observed:</strong> '
        f'{escape(_message(p, status, clock, timezone))}</p>' for p in paces
    )


def pace_details(paces, status, *, now=None):
    clock = (now or datetime.now(UTC)).timestamp()
    items = []
    for row in paces:
        for p in row:
            method = "signed net elapsed-time rate" if p["name"] == "Recent" else "weighted signed intervals, six-hour half-life"
            rate = f'{p["rate"]:.3f} pp/hour' if p["rate"] is not None else "unavailable"
            state = pace_state(p, status, clock)
            reason = ("awaiting fresh capture" if state == "awaiting" else "") or p["reason"] or ("missing live reset" if p["reset"] is None else "eligible; conditional on captured reading")
            items.append(
                f'<p>{escape(p["limit_id"])} · {p["duration_minutes"]} min · {escape(p["name"])}: {method}; up to {span_label(p["horizon_seconds"])} lookback; '
                f'{span_label(p["span_seconds"])} observed; {p["observations"]} observations; '
                f'{p["movement"]:g} signed percentage points; {rate}; '
                f'maximum gap {span_label(p["gap_seconds"])}; {p["corrections"]} corrections; '
                f'{p["conflicts"]} conflicts; boundary: {escape(p["boundary"])}; {escape(reason)}.</p>'
            )
    return ''.join(items)
