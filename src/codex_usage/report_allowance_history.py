"""Bounded issued inspection of every period, fragment, fit and exact capture."""
from datetime import datetime
import json
from urllib.parse import quote

from codex_usage.allowance_display_history import SUPPORTED
from codex_usage.allowance_history_navigation import (
    CAPTURE_LIMIT, DEFAULT_STATE, FIT_LIMIT, PERIOD_LIMIT, page_slice, selection,
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


def _fragment(report, fragment, timezone, link):
    from codex_usage.report_allowance import _local_reset, series_label, text
    reset = fragment["next_reset"]
    next_reset = ""
    if reset is not None and (fragment["current"] or not fragment["uncertain"] and not fragment["ended_by"]):
        iso, label = _local_reset(reset, timezone)
        reset_label = "Captured reset" if fragment["current"] else "Next reset"
        next_reset = f' · {reset_label} <time datetime="{text(iso)}">{text(label)}</time>'
    status = ("Current · uncertain boundary" if fragment["current"] and fragment["uncertain"] else
              "Current" if fragment["current"] else "Uncertain" if fragment["uncertain"] else
              "Ended" if fragment["ended_by"] in SUPPORTED | {"plan change"} else
              "Coverage ended" if fragment["ended_by"] else "Last observed")
    counts = f'Capture details ({len(fragment["capture_indices"])}) · Fits ({len(fragment["fit_indices"])})'
    opening = " · Opening unobserved" if fragment["boundary"] not in SUPPORTED else ""
    return (
        '<li class="allowance-history-item">'
        f'<div class="allowance-history-heading"><span class="allowance-history-series">{series_label(fragment)}</span>'
        f'<strong>{status}</strong></div>'
        f'<p class="allowance-history-meta">{text(_observed(report["display_history"], fragment, timezone))}{opening}{next_reset}</p>'
        f'{link(counts) or text(counts)}</li>'
    )


def period_history(report, timezone, *, nav=None):
    from codex_usage.report_allowance import text, series_label
    history = report["display_history"]
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
        uncertain_markup = (
            f'<details class="allowance-uncertain"{expanded}><summary>Uncertain readings ({count})</summary>'
            f'<p>{len(uncertain)} fragments · Newest first · {len(cross)} cross-boundary fits.</p>'
            f'{_pages(nav, state, "uncertain_page", len(uncertain), PERIOD_LIMIT, "uncertain fragments", reset=True)}'
            f'<ol class="allowance-history">{rows("uncertain")}</ol>{cross_link}</details>'
        )
    detail = ""
    if state["kind"]:
        owner = selection(history, state)
        label = ("Uncertain / cross-boundary fits" if state["kind"] == "cross" else
                 f'{series_label(owner)} · {text(_observed(history, owner, timezone))}')
        boundary = (f'<p>Boundary: {text(owner["boundary"])} · End: {text(owner["ended_by"] or "not observed")}. '
                    'Actual start not established.</p>' if state["kind"] != "cross" else "")
        if owner.get("evidence_reasons"):
            boundary += f'<p>Evidence: {text("; ".join(owner["evidence_reasons"]))}</p>'
        detail = (f'<div class="allowance-history-inspection"><h4>{label}</h4>{boundary}'
                  f'{_captures(history, owner["capture_indices"], timezone, nav, state)}'
                  f'{_fits(report, owner["fit_indices"], timezone, nav, state)}</div>')
    return (
        '<h3>Allowance history</h3>'
        f'<p class="allowance-history-count">{len(periods)} observed periods · Newest first · '
        f'{len(history["captures"])} exact captures. Observed coverage is not the subscription start.</p>'
        f'{_pages(nav, state, "period_page", len(periods), PERIOD_LIMIT, "periods", reset=True)}'
        f'<ol class="allowance-history" aria-label="Allowance period history">{rows("periods")}</ol>'
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
