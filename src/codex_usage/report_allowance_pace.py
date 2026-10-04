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


def cycle_span_label(seconds):
    minutes = max(0, round(seconds / 60))
    if minutes < 1440:
        return span_label(seconds)
    days, minutes = divmod(minutes, 1440)
    return f"{days}d {span_label(minutes * 60)}" if minutes else f"{days}d"


def reset_gap_label(seconds):
    return cycle_span_label(round(seconds / 3600) * 3600) if seconds >= 3600 else span_label(seconds)


def _runout_time(exhaustion, now, timezone):
    local = datetime.fromtimestamp(round(exhaustion / 900) * 900, timezone)
    days = (local.date() - datetime.fromtimestamp(now, timezone).date()).days
    day = "today" if days == 0 else "tomorrow" if days == 1 else local.strftime("%Y-%m-%d")
    stamp = f"{day}, {local:%H:%M %Z}"
    offset = local.strftime("%z")
    title = f"{local:%Y-%m-%d %H:%M %Z} (UTC{offset[:3]}:{offset[3:]})"
    return (f'<time datetime="{escape(local.isoformat())}" title="{escape(title)}" '
            f'aria-label="{escape(title)}">{escape(stamp)}</time>')


def _message(pace, status, now, timezone):
    """Return safe message markup, retaining exact date/offset on the time element."""
    state = pace_state(pace, status, now)
    if state == "awaiting":
        return "Forecast awaiting fresh capture"
    if state == "reported full":
        return "Meter reports 100% used"
    if state == "unmeasurable":
        reason = pace.get("calibrated_reason") or pace.get("reason", "")
        if "insufficient signed movement" in pace.get("reason", ""):
            reason += "; " if reason != "insufficient signed movement" else ""
            if reason == "insufficient signed movement":
                reason = ""
            reason += "direct measurement needs at least two net percentage points within this period"
        return "Pace not yet measurable" + (f" ({escape(reason)})" if reason else "")
    if state == "missing reset":
        return "Forecast awaiting fresh capture"
    exhaustion, reset = pace["exhaustion"], pace["reset"]
    if exhaustion is None:
        return f'About {round(pace["reset_balance"])}% would remain at reset.'
    if abs(exhaustion - reset) <= 900:
        return "Estimated to run out near reset."
    if exhaustion < reset:
        return (f"Estimated to run out {_runout_time(exhaustion, now, timezone)} · "
                f"~{reset_gap_label(reset - exhaustion)} before reset.")
    balance = pace["reset_balance"]
    remaining = "less than 1%" if round(balance) == 0 else f"{round(balance)}%"
    return f"About {remaining} would remain at reset."


def pace_rows(paces, status, *, timezone, now=None):
    clock = (now or datetime.now(UTC)).timestamp()
    return ''.join(
        '<p class="allowance-pace">'
        f'<strong title="{escape(span_label(p["span_seconds"]))} observed">'
        f'{escape("Cycle average" if p["name"] == "Cycle" else p["name"])} · '
        f'{(cycle_span_label if p["name"] == "Cycle" else span_label)(p["span_seconds"])}'
        f'{" (estimated)" if p.get("method") == "calibrated cost" else ""}:</strong> '
        f'{_message(p, status, clock, timezone)}</p>' for p in paces
    )


def pace_details(paces, status, *, now=None):
    clock = (now or datetime.now(UTC)).timestamp()
    items = []
    for row in paces:
        for p in row:
            method = ("captured cost / reference / observed elapsed hours" if p.get("method") == "calibrated cost"
                      else "signed net elapsed-time rate")
            reference = p.get("reference")
            calibration = (f'; reference ${reference["value"]:g}, {"previous" if reference["previous"] else "current"} cycle, '
                           f'{reference["start"]} to {reference["end"]}, available {reference["available_at"]}, {reference["confidence"]}' if reference else "")
            if "calibrated_reason" in p:
                calibration += (f'; cost {p["cost"] if p["cost"] is not None else "unavailable"}, '
                                f'interval {p["observed_start"] or "unavailable"} to captured anchor; '
                                f'coverage complete: {p["coverage_complete"]}; {p["unpriced_tokens"]} unpriced tokens; '
                                f'calibration: {p["calibrated_reason"] or "eligible"}')
            lookback = ("entire observed coherent suffix; reset instant may be unobserved"
                        if p["name"] == "Cycle" else f'up to {span_label(p["horizon_seconds"])} lookback')
            rate = f'{p["rate"]:.3f} pp/hour' if p["rate"] is not None else "unavailable"
            state = pace_state(p, status, clock)
            reason = ("awaiting fresh capture" if state == "awaiting" else "") or p["reason"] or ("missing live reset" if p["reset"] is None else "eligible; conditional on captured reading")
            items.append(
                f'<p>{escape(p["limit_id"])} · {p["duration_minutes"]} min · {escape(p["name"])}: {method}; {lookback}; '
                f'{span_label(p["span_seconds"])} observed; {p["observations"]} observations; '
                f'{p["movement"]:g} signed percentage points; {rate}; '
                f'maximum gap {span_label(p["gap_seconds"])}; {p["corrections"]} corrections; '
                f'{p["conflicts"]} conflicts; boundary: {escape(p["boundary"])}; {escape(reason)}{escape(calibration)}.</p>'
            )
    return ''.join(items)
