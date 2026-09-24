"""Script-free account allowance report shared by both application shells."""
from html import escape
from statistics import median


def duration_label(minutes):
    if minutes is None:
        return "Unknown duration"
    if minutes % 1440 == 0:
        return f"{minutes // 1440} days"
    if minutes % 60 == 0:
        return f"{minutes // 60} hours"
    return f"{minutes} min"


def trend_svg(windows):
    values = [w["estimate"]["value"] for w in windows[-12:]]
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    points = " ".join(f"{10 + 280 * i / (len(values)-1):.1f},{60 - 45 * (v-low) / (high-low or 1):.1f}" for i, v in enumerate(values))
    return ('<svg class="allowance-trend" viewBox="0 0 300 75" role="img" aria-label="Qualified completed-window trend">'
            f'<title>Qualified full-allowance estimates: {escape(", ".join(money(v) for v in values))}</title>'
            f'<polyline points="{points}" fill="none" stroke="currentColor" stroke-width="2"/></svg>')


def text(value):
    return escape(str(value))


def money(value):
    return f"${value:,.2f}" if value is not None else "Insufficient data"


def economic_card(window, *, headline):
    if not headline:
        label = "Latest completed · qualified"
    elif window is None:
        label = "Latest window"
    elif window["closure"] == "ongoing":
        label = "Current · provisional"
    elif window["estimate"]["confidence"] in {"High", "Medium"}:
        label = "Latest window · qualified"
    else:
        label = "Latest window · provisional"
    card_class = "allowance-economic allowance-headline" if headline else "allowance-economic"
    if window is None:
        reason = ("The latest window has no valid priced estimate."
                  if headline else "No completed High/Medium window is available.")
        return (f'<div class="{card_class}"><h3>{label}</h3>'
                f'<p class="allowance-value">Insufficient data</p><p class="muted">{reason}</p></div>')
    estimate = window["estimate"]
    return (
        f'<div class="{card_class}"><h3>{label}</h3>'
        f'<p class="allowance-value">{money(estimate["value"])}</p>'
        f'<p>{text(window["limit_id"])} · {text(window["plan"] or "Unknown plan")} · '
        f'{text(duration_label(window["duration_minutes"]))}</p>'
        f'<p>Observed {text(window["start"][:10])}–{text(window["end"][:10])} · '
        f'{text(estimate["confidence"])} confidence</p>'
        f'<p class="muted">Evidence: {estimate["span"]:g} percentage points, '
        f'{estimate["bins"]} bins, {money(estimate["cost_span"])} local priced usage.</p></div>'
    )


def render_allowance_section(report):
    if report is None:
        return ""
    status = report["status"]
    buckets = []
    for bucket in status["active_buckets"]:
        reset = bucket["resets_at"]
        if reset is not None:
            from datetime import UTC, datetime
            reset = datetime.fromtimestamp(reset, UTC).strftime("%Y-%m-%d %H:%M UTC")
        buckets.append(
            '<div class="allowance-bucket">'
            f'<strong>{text(bucket["limit_id"])} · {text(duration_label(bucket["duration_minutes"]))}</strong>'
            f'<p>{bucket["used_percent"]:g}% used · {100-bucket["used_percent"]:g}% remaining</p>'
            f'<meter min="0" max="100" value="{bucket["used_percent"]}" aria-label="Percentage used"></meter>'
            f'<p class="muted">Reset: {text(reset or "Unavailable")}</p></div>'
        )
    qualified = report["qualified"]
    trends = []
    groups = {}
    for window in qualified:
        groups.setdefault((window["limit_id"], window["plan"], window["duration_minutes"]), []).append(window)
    for (limit_id, plan, duration), windows in groups.items():
        rolling = (f'<p>Four-window rolling median: {money(median(w["estimate"]["value"] for w in windows[-4:]))}</p>'
                   if len(windows) >= 4 else "")
        items = ''.join(f'<li>{text(w["end"][:10])}: {money(w["estimate"]["value"])} · {text(w["estimate"]["confidence"])}</li>' for w in windows[-12:])
        trends.append(f'<div><h4>{text(limit_id)} · {text(plan or "Unknown plan")} · {text(duration_label(duration))}</h4>'
                      f'{trend_svg(windows)}{rolling}'
                      f'<details><summary>Qualified completed-window trend</summary><ol>{items}</ol></details></div>')
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
    return (
        '<section class="card plan-allowance" id="plan-allowance" aria-labelledby="plan-allowance-title">'
        '<h2 id="plan-allowance-title">Plan Allowance</h2>'
        '<p class="muted">Account-wide · unaffected by project and date filters.</p>'
        f'<div class="allowance-buckets">{"".join(buckets) or "<p>Quota information is unavailable.</p>"}</div>'
        '<h3>Observed API-equivalent value per 100% allowance</h3>'
        f'<div class="allowance-economics">{economic_card(report.get("headline"), headline=True)}'
        f'{economic_card(report.get("latest_completed"), headline=False)}</div>'
        '<p class="muted">A workload-specific estimate from local priced language usage, not cash value or a contractual allowance. '
        'Other devices, missing history, model mix, and pricing can affect coverage.</p>'
        '<details><summary>Probe, coverage, and trend diagnostics</summary>'
        f'<p>Plan: {text(status["plan"] or "Unavailable")} · Probe: {text(status["probe_status"])} · '
        f'Last checked: {text(status["last_probe_at"] or "Not captured")} · '
        f'Last observed: {text(status.get("last_observed_at") or "Not captured")}</p>'
        f'<p>Probe diagnostic: {text(status.get("diagnostics") or "None")}</p>'
        f'<p>Bounded recovered history: {recovery["complete"]} sources checked, '
        f'{recovery["pending"]} pending, {recovery["unavailable"]} unavailable. Endpoint sampling is partial.</p>'
        f'<p>Account lifetime tokens (coverage diagnostic only): {text(status["lifetime_tokens"] if status["lifetime_tokens"] is not None else "Unavailable")}</p>'
        f'{"".join(trends) or "<p>No qualified completed-window trend.</p>"}</details>'
        '<details><summary>Reset windows and capture details</summary>'
        f'{"".join(details) or "<p>No observations captured yet.</p>"}</details></section>'
    )


def allowance_css():
    return """
.plan-allowance { margin: 18px 0; padding: 20px; border: 1px solid var(--border, var(--line)); border-radius: 12px; overflow-wrap: anywhere; }
.allowance-buckets { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(220px,100%),1fr)); gap: 16px; }
.allowance-economics { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(280px,100%),1fr)); gap: 12px; }
.allowance-economic { padding: 14px; border: 1px solid var(--border, var(--line)); border-radius: 8px; }
.allowance-economic h3 { margin-top: 0; }
.allowance-economic p { margin: 6px 0; }
.allowance-headline .allowance-value { font-size: clamp(2rem, 3vw, 2.7rem); }
.allowance-bucket meter { width: 100%; }
.allowance-trend { display: block; width: min(100%, 360px); height: 72px; color: var(--accent, var(--astra)); }
.allowance-value { font-size: 1.35rem; font-weight: 700; }
.allowance-window { margin: 12px 0; padding: 10px; border: 1px solid var(--border, var(--line)); }
.allowance-provisional { border-style: dashed; }
.plan-allowance summary { cursor: pointer; }
.plan-allowance .table-scroll { overflow-x: auto; }
"""
