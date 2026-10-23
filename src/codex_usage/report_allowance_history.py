"""Bounded issued inspection of every period, fragment, fit and exact capture."""
from datetime import datetime
import json
from urllib.parse import quote

from codex_usage.allowance_history_navigation import (
    CAPTURE_LIMIT, DEFAULT_STATE, FIT_LIMIT, PERIOD_LIMIT, page_slice, selection,
    report_history,
)


def _link(nav, target, label):
    from codex_usage.report_allowance import text
    action = next((a for a in nav["actions"] if a["state"] == target), None) if nav else None
    if action is None:
        return ""
    uri = "command:codexUsage.navigateAllowanceHistory?" + quote(json.dumps([action], separators=(",", ":")), safe="")
    return f'<a href="{text(uri)}">{text(label)}</a>'


def _pages(nav, state, field, count, size, label, *, reset=False, chronological=False):
    from codex_usage.report_allowance import text
    pages = max(1, (count+size-1)//size)
    links = []
    directions = ("Earlier", "Later") if chronological else ("Newer", "Older")
    for page, direction in zip((state[field]-1, state[field]+1), directions, strict=True):
        target = dict(state, **{field: page})
        if reset:
            target.update(kind="", index=-1, fit_page=0, capture_page=0, capture_order="newest")
        if 0 <= page < pages:
            links.append(_link(nav, target, f"{direction} {label}"))
    return (f'<nav class="allowance-history-nav" aria-label="{text(label)} pages">'
            f'<span>Page {state[field]+1} of {pages}</span>{"".join(links)}</nav>')


def _observed(history, fragment, timezone):
    indices = fragment["capture_indices"]
    dates = [datetime.fromisoformat(history["captures"][i]["timestamp"]).astimezone(timezone).date()
             for i in (indices[0], indices[-1])]
    return f"Observed {dates[0]} to {dates[1]}"


def _time(timestamp, timezone):
    from codex_usage.report_allowance import text
    value = datetime.fromtimestamp(timestamp, timezone)
    return (f'<time datetime="{text(value.isoformat())}" title="{text(value.isoformat())}">'
            f'{text(value.strftime("%b %d, %H:%M"))}</time>')


def _edge(boundary, timezone):
    prefix = "by " if boundary["earliest"] != boundary["latest"] else ""
    return prefix + _time(boundary["latest"], timezone)


def _window(history, fragment, timezone):
    opening, closure = fragment.get("reset_opening"), fragment.get("reset_closure")
    if opening or closure or fragment["current"]:
        start = _edge(opening, timezone) if opening else "Start unknown"
        end = _edge(closure, timezone) if closure else "Now" if fragment["current"] else "End unknown"
        return f"{start} – {end}"
    return _observed(history, fragment, timezone)


def _boundary_details(fragment, timezone):
    from codex_usage.report_allowance import _local_reset, text
    rows = []
    for key, label in (("reset_opening", "Opening reset"), ("reset_closure", "Closing reset")):
        boundary = fragment.get(key)
        if boundary:
            first, last = [_local_reset(boundary[field], timezone)[1] for field in ("earliest", "latest")]
            stamp = last if first == last else f"after {first}, by {last}"
            rows.append(f"{label}: {text(stamp)} ({text(boundary['kind'])}).")
    if not fragment.get("reset_opening"):
        rows.append("Actual start not established.")
    return " ".join(rows)


def _fragment(report, fragment, timezone, link):
    from codex_usage.report_allowance import text
    reset = fragment["next_reset"]
    next_reset = ""
    if reset is not None and fragment["current"]:
        next_reset = f' · Next reset {_time(reset, timezone)}'
    status = "Current" if fragment["current"] else "Reset" if fragment.get("reset_closure") else "Partial"
    identity = f'{text(fragment["limit_id"])} · {text(fragment["plan"] or "Unknown plan")}'
    detail = " · " + (link("Details") or "Details")
    return (
        '<li class="allowance-history-item">'
        f'<div class="allowance-history-heading"><span class="allowance-history-series">'
        f'{_window(report_history(report), fragment, timezone)}</span>'
        f'<strong>{status}</strong></div>'
        f'<p class="allowance-history-meta">{identity}{next_reset}{detail}</p></li>'
    )


def period_history(report, timezone, *, nav=None):
    from codex_usage.report_allowance import text, series_label
    history = report_history(report)
    state = nav["state"] if nav else dict(DEFAULT_STATE)

    def rows(kind):
        page = state["period_page" if kind == "periods" else "uncertain_page"]
        return "".join(_fragment(report, fragment, timezone,
            lambda label, index=index: _link(nav, dict(state, kind=kind, index=index, fit_page=0,
                                                       capture_page=0, capture_order="newest"), label))
            for index, fragment in enumerate(page_slice(history[kind], page, PERIOD_LIMIT), start=page*PERIOD_LIMIT))

    periods, uncertain, cross = history["periods"], history["uncertain"], history["cross_boundary_fit_indices"]
    uncertain_markup = ""
    if uncertain or cross:
        count = sum(len(fragment["capture_indices"]) for fragment in uncertain)
        expanded = " open" if state["kind"] in ("uncertain", "cross") or state["uncertain_page"] else ""
        cross_link = _link(nav, dict(state, kind="cross", index=-1, fit_page=0, capture_page=0,
                                    capture_order="newest"), f"Uncertain / cross-boundary fits ({len(cross)})")
        label = "Capture diagnostics" if "reset_history" in report else "Uncertain readings"
        uncertain_markup = (
            f'<details class="allowance-uncertain"{expanded}><summary>{label} ({count})</summary>'
            f'<p>{len(uncertain)} fragments · Newest first · {len(cross)} cross-boundary fits.</p>'
            f'{_pages(nav, state, "uncertain_page", len(uncertain), PERIOD_LIMIT, "uncertain fragments", reset=True)}'
            f'<ol class="allowance-history">{rows("uncertain")}</ol>{cross_link}</details>'
        )
    detail = ""
    if state["kind"]:
        owner = selection(history, state)
        label = ("Uncertain / cross-boundary fits" if state["kind"] == "cross" else
                 f'{series_label(owner)} · {text(_observed(history, owner, timezone))}')
        boundary = (f'<p>{_boundary_details(owner, timezone)}</p>'
                    f'<p>Boundary: {text(owner["boundary"])} · End: {text(owner["ended_by"] or "not observed")}.</p>'
                    if state["kind"] != "cross" else "")
        if owner.get("evidence_reasons"):
            boundary += f'<p>Evidence: {text("; ".join(owner["evidence_reasons"]))}</p>'
        detail = (f'<div class="allowance-history-inspection"><h4>{label}</h4>{boundary}'
                  f'{_captures(history, owner["capture_indices"], timezone, nav, state)}'
                  f'{_fits(report, owner["fit_indices"], timezone, nav, state)}</div>')
    if "reset_history" in report:
        from codex_usage.report_allowance_reset_periods import reset_table
        primary = reset_table(history, timezone, nav, state)
        noun = "reset periods"
    else:
        primary = f'<ol class="allowance-history" aria-label="Allowance period history">{rows("periods")}</ol>'
        noun = "observed periods"
    return (
        f'<p class="allowance-history-count">{len(periods)} {noun} · Newest first</p>'
        f'{_pages(nav, state, "period_page", len(periods), PERIOD_LIMIT, "periods", reset=True)}'
        f'{primary}'
        f'{uncertain_markup}{detail}'
    )


def _captures(history, indices, timezone, nav, state):
    from codex_usage.report_allowance import _observation_row, _SOURCE_DESCRIPTION, text
    if not indices:
        return ""
    selected = page_slice(indices, state["capture_page"], CAPTURE_LIMIT, newest=state["capture_order"] == "newest")
    order = state["capture_order"]
    target = dict(state, capture_order="oldest" if order == "newest" else "newest", capture_page=0)
    toggle = _link(nav, target, f'{target["capture_order"].title()} first')
    rows = "".join(_observation_row(history["captures"][index], timezone, full=True) for index in selected)
    pages = _pages(nav, state, "capture_page", len(indices), CAPTURE_LIMIT, "captures", chronological=order == "oldest")
    return (
        f'<p>{len(selected)} of {len(indices)} exact captures · {order.title()} first · {toggle}</p>{pages}'
        '<div class="table-scroll" tabindex="0" role="region" aria-label="Quota observations">'
        '<table class="allowance-observations"><thead><tr><th>Observed at</th><th>Used</th>'
        f'<th title="{text(_SOURCE_DESCRIPTION)}">Slot · Source</th><th>Reset</th>'
        '<th>Plan</th><th>Duration (min)</th><th>Reset credits</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div>'
    )


def _fits(report, indices, timezone, nav, state):
    from codex_usage.report_allowance import estimate_number, money, text, _local_observation
    items = []
    for index in page_slice(indices, state["fit_page"], FIT_LIMIT, newest=True):
        window = report["windows"][index]
        estimate = window["estimate"]
        _, start = _local_observation(window["start"], timezone, detailed=True)
        _, end = _local_observation(window["end"], timezone, detailed=True)
        excluded = window.get("excluded_observations", 0)
        items.append(
            f'<details class="allowance-fit"><summary>Fit {index + 1} · {text(estimate["confidence"])} · '
            f'{money(estimate["value"])}</summary>'
            f'<p>Observed {text(start)} to {text(end)} · {text(window["closure"])}</p>'
            f'<p>{estimate_number(estimate["span"])} percentage points · {estimate["bins"]} bins · '
            f'local cost span {money(estimate["cost_span"])}</p>'
            f'<p>R² {estimate["r_squared"]:.3f} · sensitivity P90/P10 '
            f'{estimate_number(estimate["sensitivity_ratio"])} · {window["corrections"]} meter corrections · '
            f'{len(window["points"])} fit-window captures · {excluded} excluded from first reported-full onward.</p>'
            f'<p>{"100% priced" if window.get("fully_priced", True) else "Unpriced usage: monetary estimate unavailable"} · '
            f'{"Complete local ledger" if window.get("coverage_complete", True) else "Partial local ledger"}</p></details>'
        )
    return (f'<p>{len(indices)} independent fits · Newest first</p>'
            f'{_pages(nav, state, "fit_page", len(indices), FIT_LIMIT, "fits")}' + "".join(items))
