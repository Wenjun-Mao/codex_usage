"""Exact captured balances and original intervals; no plotted delta allocation."""
import html
from datetime import datetime
from decimal import Decimal, localcontext

from codex_usage.report_breakdown_numbers import compact_decimal, numeric_axis


def balance_ticks(minimum, maximum):
    with localcontext() as context:
        context.prec = max(40, len(minimum.as_tuple().digits) + len(maximum.as_tuple().digits) + 4)
        actual = [maximum, (maximum + minimum) / 2, minimum]
        labels = [compact_decimal(value) for value in actual]
        offset = minimum if len(set(labels)) < len(set(actual)) else None
        values = [value - minimum for value in actual] if offset is not None else actual
    return numeric_axis(values, actual=actual), offset


def selected_balances(points, start, end):
    return [p for p in points if
        start <= datetime.fromisoformat(p["timestamp"]).timestamp() < end or
        (p["origin"] and datetime.fromisoformat(p["origin"]).timestamp() < end and
         datetime.fromisoformat(p["timestamp"]).timestamp() >= start)]


def balances(points, start, end, timezone):
    selected = selected_balances(points, start, end)
    in_domain = [p for p in selected if start <= datetime.fromisoformat(p["timestamp"]).timestamp() < end]
    finite = [p for p in in_domain if p["balance"] is not None and not p["unlimited"] and not p["diagnostic"]]
    availability = "" if finite else ("No finite valid balances among in-domain captures." if in_domain else
        "No in-domain balance captures; spanning evidence retained." if selected else "Credit balance unavailable: no captures or spanning evidence.")
    rows = []
    for point in selected:
        value = point["balance"] if point["balance"] is not None and not point["diagnostic"] and not point["unlimited"] else "Unlimited" if point["unlimited"] else "Unknown"
        change = point["change"]
        origin = datetime.fromisoformat(point["origin"]).timestamp() if point["origin"] else None
        at = datetime.fromisoformat(point["timestamp"]).timestamp()
        crossing = origin is not None and (origin < start or at >= end)
        interval = f'{point["origin"]} to {point["timestamp"]}' if origin is not None else point["timestamp"]
        movement = ("Unknown: " + point["reason"] if change is None else
            f'Net decrease {change} credits' if Decimal(change) < 0 else
            f'Increase +{change} credits (purchase/grant/refund/adjustment possible)' if Decimal(change) > 0 else
            f'Unchanged {change} credits')
        movement += "; boundary-crossing, unallocatable" if crossing else "; interval net change, not hourly allocation"
        label = f'{point["timestamp"]} | balance {value} credits | {point["plan"] or "plan unavailable"}'
        rows.append(f'<tr><td>{html.escape(label)}</td><td>{html.escape(interval)}</td><td>{html.escape(movement)}</td></tr>')
    return (f'<p class="ub-note">{availability}</p><details><summary>Exact balances and net-change intervals ({len(selected)})</summary>'
        '<div class="table-wrap"><table><thead><tr><th>Captured balance / plan</th><th>Original UTC interval</th><th>Account-wide net change</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div></details>')
