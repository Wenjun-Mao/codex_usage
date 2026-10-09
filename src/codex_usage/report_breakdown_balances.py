"""Captured balances and original net-change intervals, never hourly debits."""
import html
from datetime import datetime
from decimal import Decimal, localcontext

from codex_usage.report_breakdown_axis import time_axis, timestamp_label
from codex_usage.report_breakdown_numbers import compact_decimal, numeric_axis


def balance_ticks(minimum, maximum):
    with localcontext() as context:
        context.prec = 40
        actual = [maximum, (maximum + minimum) / 2, minimum]
        labels = [compact_decimal(value) for value in actual]
        # Use a named offset only when compact absolute ticks lose movement.
        offset = minimum if len(set(labels)) < len(set(actual)) else None
        values = [value - minimum for value in actual] if offset is not None else actual
    return numeric_axis(values, actual=actual), offset


def balances(points, start, end, timezone):
    width, height = 720, 140
    selected = [p for p in points if
        start <= datetime.fromisoformat(p["timestamp"]).timestamp() <= end or
        (datetime.fromisoformat(p["origin"] or p["timestamp"]).timestamp() <= end and
        datetime.fromisoformat(p["timestamp"]).timestamp() >= start)]
    valid = [p for p in selected if p["balance"] is not None and not p["unlimited"] and not p["diagnostic"]]
    in_domain = [p for p in valid if start <= datetime.fromisoformat(p["timestamp"]).timestamp() <= end]
    raw_in_domain = [p for p in selected if start <= datetime.fromisoformat(p["timestamp"]).timestamp() <= end]
    maximum = max((Decimal(p["balance"]) for p in valid), default=Decimal(0))
    minimum = min((Decimal(p["balance"]) for p in valid), default=Decimal(0))
    scale = maximum-minimum or Decimal(1)
    known_changes = [Decimal(p["change"]) for p in selected if p["change"] is not None]
    change_maximum = max((change.copy_abs() for change in known_changes), default=Decimal(0))
    change_scale = change_maximum or Decimal(1)
    marks, changes, rows = [], [], []
    def x(at):
        return (at-start) / max(.000001, end-start) * width
    for point in selected:
        at = datetime.fromisoformat(point["timestamp"]).timestamp()
        origin = datetime.fromisoformat(point["origin"]).timestamp() if point["origin"] else None
        value = point["balance"] if point in valid else "Unlimited" if point["unlimited"] else "Unknown"
        label = f'{timestamp_label(at, timezone)} | balance {value} credits | {point["plan"] or "plan unavailable"}'
        if point in valid and start <= at <= end:
            y = height * (1-float((Decimal(point["balance"])-minimum)/scale)) if maximum != minimum else height/2
            marks.append(f'<circle cx="{x(at):.3f}" cy="{y:.3f}" r="3" fill="var(--accent)" role="img" aria-label="{html.escape(label, quote=True)}"><title>{html.escape(label)}</title></circle>')
        change = point["change"]
        crossing = origin is not None and (origin < start or at > end)
        interval = f'{point["origin"]} to {point["timestamp"]}' if origin is not None else point["timestamp"]
        movement = ("Unknown: " + point["reason"] if change is None else
            f'Net decrease {change} credits' if Decimal(change) < 0 else
            f'Increase +{change} credits (reload/grant/refund/adjustment possible)' if Decimal(change) > 0 else
            f'Unchanged {change} credits')
        movement += "; boundary-crossing, unallocatable" if crossing else "; interval net change, not hourly allocation"
        if change is not None and origin is not None and at > origin:
            # Signed interval magnitude, not an interpolated balance/debit rate.
            color = "#bf4565" if Decimal(change) < 0 else "#24896e"
            title = html.escape(interval + " | " + movement)
            y = 50-float(Decimal(change)/change_scale)*45
            changes.append(f'<line x1="{x(max(start, origin)):.3f}" x2="{x(min(end, at)):.3f}" y1="{y:.3f}" y2="{y:.3f}" stroke="{color}" stroke-dasharray="3 3" stroke-width="3" vector-effect="non-scaling-stroke" role="img" aria-label="{html.escape(interval + " | " + movement, quote=True)}"><title>{title}</title></line>')
        rows.append(f'<tr><td>{html.escape(label)}<br>{html.escape(point["timestamp"])}</td><td>{html.escape(interval)}</td><td>{html.escape(movement)}</td></tr>')
    grid = ''.join(f'<line x1="0" x2="{width}" y1="{height*f}" y2="{height*f}" stroke="var(--border)"/>' for f in (0, .5, 1))
    balance_axis, offset = balance_ticks(minimum, maximum) if valid else ('<span>Unknown</span><span></span><span></span>', None)
    change_axis = numeric_axis([change_maximum, Decimal(0), change_maximum.copy_negate()], signed=True) if known_changes else '<span>Unknown</span><span></span><span></span>'
    offset_label = f' Axis offset: +{format(offset, "f")} credits; ticks show credits above this balance.' if offset is not None else ''
    balance_name = f'Captured account-wide credit balances, observed range {minimum} to {maximum}' if valid else 'No finite valid captured credit balances'
    change_name = 'Signed net credit changes over original intervals' if known_changes else 'No known net credit changes'
    availability = ('' if in_domain else
        '<p class="ub-note">No finite valid balances among in-domain captures; missing/invalid/unlimited readings remain inspectable below.</p>' if raw_in_domain else
        '<p class="ub-note">No in-domain balance captures; boundary-spanning evidence remains inspectable below.</p>' if selected else
        '<p class="ub-note">Credit balance unavailable: no captures or spanning evidence on this time domain.</p>')
    return ('<h3>Captured credit balance · account-wide</h3>'
        f'<small>Credits · observed balance range, not zero-based; captured points only.{offset_label}</small>'
        f'<div class="ub-chart ub-meter ub-balances"><div class="ub-axis">{balance_axis}</div><div class="ub-scroll"><svg width="100%" height="{height}" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="{balance_name}">{grid}{"".join(marks)}</svg>{time_axis(start, end, timezone)}</div></div>'
        + availability
        + '<div class="ub-unit">Account-wide net change · credits per original capture interval</div>'
        + f'<div class="ub-chart ub-credit-changes"><div class="ub-axis">{change_axis}</div><div class="ub-scroll"><svg width="100%" height="100" viewBox="0 0 {width} 100" preserveAspectRatio="none" role="img" aria-label="{change_name}"><line x1="0" x2="{width}" y1="50" y2="50" stroke="var(--border)"/>{"".join(changes)}</svg>{time_axis(start, end, timezone)}</div></div>'
        + '<small>Dashed spans retain original intervals; no hourly allocation or balance interpolation. Negative: net decrease. Positive: possible reload/grant/refund/adjustment.</small>'
        + f'<details><summary>Exact balances and net-change intervals ({len(selected)})</summary><div class="table-wrap"><table><thead><tr><th>Captured balance / plan</th><th>Original UTC interval</th><th>Account-wide net change</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>')
