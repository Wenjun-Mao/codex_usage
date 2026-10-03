"""Compact credit balance and folded, account-wide balance observations."""
from decimal import Decimal
from html import escape


def credit_amount(value):
    amount = Decimal(value)
    magnitude = amount.copy_abs()
    return "<0.01" if 0 < magnitude < Decimal("0.01") else f"{magnitude:,.2f}"


def credit_heading(credits, observed_display):
    if not credits:
        return ""
    if credits["unlimited"]:
        amount = "Unlimited credits"
    elif credits["balance"] is not None:
        amount = f'{credit_amount(credits["balance"])} credits'
    else:
        return ""
    stale = credits["freshness"] != "fresh"
    label = "Last known balance" if stale else "Current balance"
    exact = f' · Exact balance: {credits["balance"]}' if credits["balance"] is not None else ""
    title = f"{label} · {observed_display}{exact}"
    suffix = " · last known" if stale else ""
    return (f'<span class="allowance-credit-balance" title="{escape(title)}">'
            f'{escape(amount)}{suffix}</span>')


def credit_details(credits, history, observation_time):
    if not credits and not history.get("count"):
        return ""
    if credits:
        label = "Current balance" if credits["freshness"] == "fresh" else "Last known balance"
        metadata = f'<p>Credits · {label} · {observation_time(credits["observed_at"])}</p>'
    else:
        metadata = '<p>Credit balance unavailable.</p>'
    observations = history.get("observations", [])
    count = history.get("count", len(observations))
    rows = []
    for item in observations:
        if item["diagnostic"]:
            balance = "Unavailable"
        elif item["unlimited"]:
            balance = "Unlimited"
        elif item["balance"] is not None:
            balance = credit_amount(item["balance"])
        else:
            balance = "Unavailable"
        change = item["change"]
        if change is None:
            change_label = "Unavailable"
        elif Decimal(change) == 0:
            change_label = "No change"
        else:
            kind = "Decrease" if Decimal(change) < 0 else "Increase"
            change_label = f"{kind}: {credit_amount(change)}"
        exact = item["balance"] or "Unavailable"
        delta = change or "Unavailable"
        rows.append(f'<tr><td>{observation_time(item["timestamp"])}</td>'
                    f'<td class="num" title="Exact balance: {escape(exact)}">{escape(balance)}</td>'
                    f'<td title="Exact change: {escape(delta)}">{escape(change_label)}</td></tr>')
    return (
        metadata + '<details><summary>Credit balance captures</summary>'
        f'<p>Newest {len(observations)} of {count} captures. Account-wide balance changes may include adjustments; '
        'they are separate from token-based estimated credits and banked resets.</p>'
        '<div class="table-scroll" tabindex="0" role="region" aria-label="Credit balance captures">'
        '<table class="allowance-credit-observations"><thead><tr><th>Observed at</th><th class="num">Balance</th>'
        f'<th>Net change</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>'
    )
