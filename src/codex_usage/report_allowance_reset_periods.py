"""Compact reset-period dollars and allowance comparison for human review."""
from datetime import datetime

from codex_usage.allowance_history_navigation import PERIOD_LIMIT, page_slice
from codex_usage.report_numbers import percentage_text


def _time(stamp, timezone, *, approximate=False):
    from codex_usage.report_allowance import text
    local = datetime.fromtimestamp(stamp, timezone)
    return (f'{"~" if approximate else ""}<time datetime="{text(local.isoformat())}" '
            f'title="{text(local.isoformat())}">{text(local.strftime("%b %d, %H:%M"))}</time>')


def reset_range(period, timezone):
    opening, closing = period["reset_opening"], period["reset_closure"] or period["identity_closure"]
    start = _time(period["start"], timezone,
                  approximate=bool(opening and opening["earliest"] != opening["latest"]))
    if not opening:
        start = "Captured from " + start
    end = (_time(period["end"], timezone, approximate=closing["earliest"] != closing["latest"])
           if closing else "Current" if period["current"] else _time(period["observed_end"], timezone))
    return f"{start} &ndash; {end}"


def reset_table(history, timezone, nav, state):
    from codex_usage.report_allowance import money, text
    from codex_usage.report_allowance_history import _link
    rows = []
    for index, period in enumerate(page_slice(history["periods"], state["period_page"], PERIOD_LIMIT),
                                   start=state["period_page"]*PERIOD_LIMIT):
        target = dict(state, kind="periods", index=index, fit_page=0, capture_page=0, capture_order="newest")
        link = _link(nav, target, "Details") or "Details"
        next_reset = ("Next reset " + _time(period["next_reset"], timezone)
                      if period["current"] and period["next_reset"] is not None else "")
        identity = f'{text(period["limit_id"])} &middot; {text(period["plan"] or "Unknown plan")}'
        approximate = (period["usage_usd_min"] != period["usage_usd_max"]
                       or not period["coverage_complete"] or period["unpriced_tokens_max"])
        coverage = (f'Known local usage; boundary range {money(period["usage_usd_min"])} to '
                    f'{money(period["usage_usd_max"])}; up to {period["unpriced_tokens_max"]:,} unpriced tokens')
        value = money(period["allowance_value"]) if period["allowance_value"] is not None else "Not enough data"
        rows.append('<tr class="allowance-reset-row">'
            f'<th scope="row"><strong>{reset_range(period, timezone)}</strong>'
            f'<small>{identity}{" &middot; " + next_reset if next_reset else ""}</small></th>'
            f'<td title="{text(coverage)}">{"~" if approximate else ""}{money(period["usage_usd"])}</td>'
            f'<td title="Last captured meter reading">{text(percentage_text(period["allowance_used"]))}%</td>'
            f'<td title="{text(period["allowance_confidence"])}">{value}</td><td>{link}</td></tr>')
    return ('<div class="table-scroll allowance-reset-scroll" tabindex="0" role="region" aria-label="Allowance reset periods">'
        '<table class="allowance-reset-periods"><thead><tr><th>Reset period</th><th>API-equivalent usage</th>'
        '<th>Allowance used</th><th>100% allowance value (est.)</th><th aria-label="Period details"></th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
        '<p class="muted allowance-history-count">Local API-equivalent usage, not a bill. ~ marks approximate timing or partial coverage.</p>')


def css():
    return """
.allowance-reset-periods {width:100%;min-width:850px;font-variant-numeric:tabular-nums}
.allowance-reset-periods th,.allowance-reset-periods td {padding:10px 12px;text-align:right;vertical-align:top}
.allowance-reset-periods th:first-child {text-align:left;min-width:300px}
.allowance-reset-periods td {white-space:nowrap}
.allowance-reset-periods small {display:block;color:var(--muted);font-weight:400;margin-top:4px}
.allowance-reset-periods thead th {font-size:.8rem}
.allowance-reset-periods tbody strong {font-weight:600}
.allowance-reset-scroll {margin-top:10px}
"""
