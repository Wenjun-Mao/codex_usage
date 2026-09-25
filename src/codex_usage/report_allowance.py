"""Script-free account allowance report shared by both application shells."""
from datetime import UTC, datetime, tzinfo
from html import escape


ALLOWANCE_HISTORY_LIMIT = 12


def duration_label(minutes):
    if minutes is None:
        return "Unknown duration"
    if minutes % 1440 == 0:
        return f"{minutes // 1440} days"
    if minutes % 60 == 0:
        return f"{minutes // 60} hours"
    return f"{minutes} min"


def text(value):
    return escape(str(value))


def money(value):
    return f"${value:,.2f}" if value is not None else "Insufficient data"


def series_label(window):
    return (f'{text(window["limit_id"])} · {text(window["plan"] or "Unknown plan")} · '
            f'{text(duration_label(window["duration_minutes"]))}')


def evidence_line(window, label):
    estimate = window["estimate"]
    return (f'<p>{label}: {estimate["span"]:g} percentage points, {estimate["bins"]} bins, '
            f'{money(estimate["cost_span"])} local priced usage.</p>')


def economic_summary(window, *, latest, show_series, is_previous=False):
    if is_previous:
        label = "Previous window"
    elif window is None:
        label = "Latest window"
    elif window["closure"] == "ongoing":
        label = "Current · provisional"
    elif window["estimate"]["confidence"] in {"High", "Medium"}:
        label = "Latest window · qualified"
    else:
        label = "Latest window · provisional"
    if window is None:
        series = f'{series_label(latest)} · ' if latest and show_series else ""
        context = (f'<p>{series}Observed {text(latest["start"][:10])}–'
                   f'{text(latest["end"][:10])}</p>' if latest else "")
        return (f'<div class="allowance-economic"><h3>{label}</h3>'
                '<p class="allowance-value">Insufficient data</p>'
                f'{context}<p class="muted">The latest window has no valid priced estimate.</p></div>')
    estimate = window["estimate"]
    series = f'<p>{series_label(window)}</p>' if show_series or is_previous else ""
    confidence = (f' · {text(estimate["confidence"])} confidence'
                  if is_previous or estimate["confidence"] in {"High", "Medium"} else "")
    return (
        f'<div class="allowance-economic"><h3>{label}</h3>'
        f'<p class="allowance-value">{money(estimate["value"])}</p>'
        f'{series}'
        f'<p>Observed {text(window["start"][:10])}–{text(window["end"][:10])}{confidence}</p></div>'
    )


def _history_html(history):
    if not history:
        return '<h3>Allowance history</h3><p>No valid priced window estimate yet.</p>'

    shown = history[:ALLOWANCE_HISTORY_LIMIT]
    items = []
    for window in shown:
        estimate = window["estimate"]
        if window["closure"] == "ongoing":
            window_status, status_class = "Current", "current"
        elif window["completed"]:
            window_status, status_class = "Completed", "completed"
        else:
            window_status, status_class = "Ended after plan change", "ended"
        ledger_coverage = "complete ledger" if window.get("coverage_complete", True) else "partial ledger"
        items.append(
            f'<li class="allowance-history-item allowance-history-{status_class}">'
            f'<div class="allowance-history-heading"><span class="allowance-history-series">{series_label(window)}</span>'
            f'<strong class="allowance-history-value">{money(estimate["value"])}</strong></div>'
            f'<p class="allowance-history-meta">Observed {text(window["start"][:10])}–{text(window["end"][:10])} · '
            f'{window_status} · {text(estimate["confidence"])} confidence · '
            f'{estimate["span"]:g} percentage points · {estimate["bins"]} bins · 100% priced · {ledger_coverage}</p>'
            '</li>'
        )
    count = len(history)
    context = (f'<p class="muted allowance-history-count">Newest {len(shown)} of {count} valid priced windows; '
               'all reset windows are listed below.</p>' if count > len(shown) else
               f'<p class="muted allowance-history-count">{count} valid priced window'
               f'{"s" if count != 1 else ""}; newest first.</p>')
    return ('<h3>Allowance history</h3>' + context
            + f'<ol class="allowance-history" aria-label="Allowance estimate history">{"".join(items)}</ol>')


def _series_key(item):
    return (item["limit_id"], item.get("plan") or "", item["duration_minutes"])


def _headline_needs_series(report, window):
    if window is None:
        return False
    active = report["status"]["active_buckets"]
    active_series = {
        (bucket["limit_id"], bucket.get("plan") or "", bucket["duration_minutes"])
        for bucket in active
    }
    return len(active_series) > 1 or _series_key(window) not in active_series


def _local_reset(timestamp, timezone):
    value = datetime.fromtimestamp(timestamp, timezone)
    offset = value.utcoffset()
    if offset is None:
        offset_label = "UTC offset unavailable"
    else:
        offset_minutes = int(offset.total_seconds() // 60)
        sign = "+" if offset_minutes >= 0 else "−"
        absolute_minutes = abs(offset_minutes)
        offset_label = f"UTC{sign}{absolute_minutes // 60:02d}:{absolute_minutes % 60:02d}"
    abbreviation = value.tzname()
    zone_label = f" {abbreviation}" if abbreviation else ""
    display = f"{value:%Y-%m-%d %H:%M}{zone_label} ({offset_label})"
    return value.isoformat(timespec="minutes"), display


def render_allowance_section(report, *, timezone: tzinfo = UTC):
    if report is None:
        return ""
    status = report["status"]
    buckets = []
    for bucket in status["active_buckets"]:
        reset = bucket["resets_at"]
        if reset is not None:
            reset_iso, reset_display = _local_reset(reset, timezone)
            reset_markup = (f'<time datetime="{text(reset_iso)}">'
                            f'{text(reset_display)}</time>')
        else:
            reset_markup = "Unavailable"
        identity = (f'{text(bucket["limit_id"])} · '
                    f'{text(duration_label(bucket["duration_minutes"]))}')
        buckets.append(
            '<div class="allowance-bucket">'
            '<div class="allowance-bucket-summary">'
            f'<strong>{identity}</strong>'
            f'<span class="allowance-bucket-usage">{bucket["used_percent"]:g}% used · '
            f'{100-bucket["used_percent"]:g}% remaining</span>'
            f'<span class="muted allowance-bucket-reset">Reset: {reset_markup}</span>'
            '</div>'
            f'<meter min="0" max="100" value="{bucket["used_percent"]}" '
            f'aria-label="{identity} percentage used" '
            f'aria-valuetext="{bucket["used_percent"]:g}% used"></meter></div>'
        )
    qualified = report["qualified"]
    details = []
    for window in reversed(report["windows"]):
        estimate = window["estimate"]
        provisional = " allowance-provisional" if not window["completed"] else ""
        shown_points = window["points"][-100:]
        shown_label = ("All" if len(shown_points) == len(window["points"])
                       else f'Most recent {len(shown_points)} of {len(window["points"])}')
        captures = ''.join(
            f'<tr><td>{text(p["timestamp"])}</td><td>{p["used_percent"]:g}%</td>'
            f'<td>{text(p["slot"])} · {text(p.get("provenance", "Captured"))}</td><td>{text(p["resets_at"] or "Unavailable")}</td></tr>'
            for p in shown_points
        )
        details.append(
            f'<details class="allowance-window{provisional}"><summary>{text(window["limit_id"])} · '
            f'{text(window["start"][:10])}–{text(window["end"][:10])} · {text(estimate["confidence"])}'
            f' · {text(window["closure"])}</summary>'
            f'<p>{text(window["plan"] or "Unknown plan")} · {text(window["duration_minutes"])} min · '
            f'{estimate["span"]:g} percentage points · {estimate["bins"]} bins · '
            f'local cost span {money(estimate["cost_span"])} · {money(estimate["value"])}</p>'
            f'<p>{"100% priced" if window.get("fully_priced", True) else "Unpriced usage: monetary estimate unavailable"} · {"Complete local ledger" if window.get("coverage_complete", True) else "Partial local ledger"}</p>'
            f'<p>R² {estimate["r_squared"]:.3f} · sensitivity P90/P10 {text(estimate["sensitivity_ratio"])} · '
            f'{window["corrections"]} meter corrections</p>'
            f'<details><summary>Captured observations ({len(window["points"])})</summary>'
            f'<p>{shown_label} observations shown.</p>'
            f'<div class="table-scroll"><table><thead><tr><th>Captured at</th><th>Used</th><th>Slot</th><th>Reset (Unix seconds)</th>'
            f'</tr></thead><tbody>{captures}</tbody></table></div></details></details>'
        )
    recovery = status["recovery"]
    latest = report["windows"][-1] if report["windows"] else None
    headline = report.get("headline")
    headline_previous = report.get("headline_previous", headline is not None and headline is not latest)
    show_headline_series = _headline_needs_series(report, headline or latest)
    evidence_label = "Previous window fit" if headline_previous else "Latest window fit"
    highlighted_evidence = evidence_line(headline, evidence_label) if headline else ""
    history = report.get("history", [])
    older_qualified = [window for window in qualified if window is not headline]
    shown_qualified = older_qualified[-3:]
    qualified_items = "".join(
        f'<li>{series_label(window)} · Observed {text(window["start"][:10])}–'
        f'{text(window["end"][:10])} · {money(window["estimate"]["value"])} · '
        f'{text(window["estimate"]["confidence"])}</li>' for window in reversed(shown_qualified)
    )
    qualified_context = (f'<p>Earlier qualified estimates (latest {len(shown_qualified)} of '
                         f'{len(older_qualified)}; all reset windows below):</p><ul>{qualified_items}</ul>'
                         if older_qualified else '<p>No earlier qualified completed estimate.</p>')
    return (
        '<section class="card plan-allowance" id="plan-allowance" aria-labelledby="plan-allowance-title">'
        '<h2 id="plan-allowance-title">Plan Allowance</h2>'
        '<p class="muted">Account-wide · unaffected by project and date filters.</p>'
        f'<div class="allowance-buckets">{"".join(buckets) or "<p>Quota information is unavailable.</p>"}</div>'
        '<h3>Observed API-equivalent value per 100% allowance</h3>'
        f'<div class="allowance-economics">{economic_summary(headline, latest=latest, show_series=show_headline_series, is_previous=headline_previous)}</div>'
        '<p class="muted">Workload-specific local estimate, not cash or a contractual allowance. '
        'Other devices and missing history may change it.</p>'
        '<details><summary>Probe, coverage, and allowance history</summary>'
        f'{highlighted_evidence}'
        f'<p>Plan: {text(status["plan"] or "Unavailable")} · Probe: {text(status["probe_status"])} · '
        f'Last checked: {text(status["last_probe_at"] or "Not captured")} · '
        f'Last observed: {text(status.get("last_observed_at") or "Not captured")}</p>'
        f'<p>Probe diagnostic: {text(status.get("diagnostics") or "None")}</p>'
        f'<p>Bounded recovered history: {recovery["complete"]} sources checked, '
        f'{recovery["pending"]} pending, {recovery["unavailable"]} unavailable. Endpoint sampling is partial.</p>'
        f'<p>Account lifetime tokens (coverage diagnostic only): {text(status["lifetime_tokens"] if status["lifetime_tokens"] is not None else "Unavailable")}</p>'
        f'{_history_html(history)}</details>'
        '<details><summary>Reset windows and capture details</summary>'
        f'{qualified_context}'
        f'{"".join(details) or "<p>No observations captured yet.</p>"}</details></section>'
    )


def allowance_css():
    return """
.plan-allowance { margin: 18px 0; padding: 20px; border: 1px solid var(--border, var(--line)); border-radius: 12px; overflow-wrap: anywhere; }
.allowance-buckets { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(320px,100%),1fr)); gap: 10px 18px; }
.allowance-bucket { min-width: 0; }
.allowance-bucket-summary { display: flex; align-items: baseline; flex-wrap: wrap; column-gap: 14px; row-gap: 3px; }
.allowance-bucket-summary > * { min-width: 0; margin: 0; }
.allowance-bucket-usage { font-weight: 600; }
.allowance-bucket-reset { overflow-wrap: anywhere; }
.allowance-economics { border-top: 1px solid var(--border, var(--line)); border-bottom: 1px solid var(--border, var(--line)); padding: 14px 0; }
.allowance-economic { min-width: 0; }
.allowance-economic h3 { margin-top: 0; }
.allowance-economic p { margin: 6px 0; }
.allowance-economic .allowance-value { font-size: 2.5rem; }
.allowance-bucket meter { -webkit-appearance: none; appearance: none; display: block; width: 100%; height: 14px; margin-top: 5px; padding: 0; color: var(--accent, var(--astra, #087ea4)); background: var(--surface-soft, var(--soft, #edf1f4)); border: 1px solid var(--border, var(--line, #d5dce1)); border-radius: 999px; overflow: hidden; }
.allowance-bucket meter::-webkit-meter-bar { background: var(--surface-soft, var(--soft, #edf1f4)); border: 0; border-radius: inherit; }
.allowance-bucket meter::-webkit-meter-optimum-value,
.allowance-bucket meter::-webkit-meter-suboptimum-value,
.allowance-bucket meter::-webkit-meter-even-less-good-value { background: var(--accent, var(--astra, #087ea4)); border-radius: inherit; }
.allowance-bucket meter::-moz-meter-bar { background: var(--accent, var(--astra, #087ea4)); border-radius: inherit; }
.allowance-history { list-style: none; margin: 8px 0 0; padding: 0; }
.allowance-history-item { min-width: 0; padding: 9px 0; border-top: 1px solid var(--border, var(--line)); }
.allowance-history-heading { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 4px 12px; min-width: 0; }
.allowance-history-series { min-width: 0; font-weight: 600; overflow-wrap: anywhere; }
.allowance-history-value { font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.allowance-history-meta { margin: 4px 0 0; color: var(--muted, #64717b); overflow-wrap: anywhere; }
.allowance-history-count { margin: 6px 0 0; }
.allowance-value { font-size: 1.35rem; font-weight: 700; }
.allowance-window { margin: 12px 0; padding: 10px; border: 1px solid var(--border, var(--line)); }
.allowance-provisional { border-style: dashed; }
.plan-allowance summary { cursor: pointer; }
.plan-allowance summary:focus-visible { outline: 2px solid var(--accent, var(--astra, #087ea4)); outline-offset: 2px; border-radius: 2px; }
.plan-allowance .table-scroll { overflow-x: auto; }
"""
