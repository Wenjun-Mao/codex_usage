"""Issued controls and exact inspection for the unified calendar view."""
import html
import json
from urllib.parse import quote

from codex_usage.breakdown_aggregation import ranked_projects, total
from codex_usage.report_breakdown_numbers import compact_decimal
from codex_usage.report_usage_breakdown_chart import COLORS, css
from codex_usage.report_breakdown_time import time_view


def command(nav, state, label, **changes):
    target = {**state, **changes}
    args = {"scope": nav["scope"], "state": target}
    if args not in nav["actions"]:
        nav["actions"].append(args)
    uri = "command:codexUsage.navigateBreakdown?" + quote(json.dumps([args], separators=(",", ":")), safe="")
    active = ' aria-current="true"' if target == state else ""
    return f'<a href="{html.escape(uri, quote=True)}"{active}>{html.escape(label)}</a>'


def uri(link):
    return html.unescape(link.split('href="', 1)[1].split('"', 1)[0])


def detail_table(rows, calibration, nav, state, *, selected_projects):
    body = []
    for row in sorted(rows, key=lambda r: (r["project"], r["model"], r.get("hour", ""))):
        cost = f'${row["cost"]!r}'
        if row["unknown"]:
            cost += f' + unknown ({row["unknown"]:,} tokens)'
        if row["api_excluded"]:
            cost += f'; API-excluded review tokens {row["api_excluded"]:,}'
        credits = f'{row["credits"]!r}' + (f' + unknown ({row["credit_unknown"]:,} tokens)' if row["credit_unknown"] else "")
        pp = f'{100 * row["allowance_cost"] / calibration["value"]!r} pp estimated' if calibration.get("value") else "Unavailable"
        label = (command(nav, state, row["label"], view="time", project=row["project"], detail="")
            if row["project"] in selected_projects else html.escape(row["label"]) + ' · No selected-range usage')
        body.append(f'<tr><td>{label}</td><td>{html.escape(row["model"])}</td><td>{html.escape(row.get("hour", "Selected calendar total"))}</td><td>{row["tokens"]:,}</td><td>{cost}</td><td>{credits}</td><td>{pp}</td></tr>')
    explanation = (f'Capture-causal retrospective contributions; {calibration["confidence"]}; {calibration["reference_kind"]}; reference through {calibration["reference_end"]}, available at {calibration["available_at"]}. Not exact quota attribution.'
        if calibration.get("value") else 'Estimated percentage-point contributions unavailable: ' + calibration["reason"] + '.')
    return f'<p class="ub-note">{html.escape(explanation)}</p><div class="table-wrap"><table><thead><tr><th>Project</th><th>Model</th><th>UTC occurrence</th><th>Tokens</th><th>API-equivalent cost</th><th>Estimated credits</th><th>Included contribution</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def render_breakdown(metadata, info, state, nav, reason, timezone, partition, *, global_filtered):
    controls = []
    groups = [("view", (("time", "Time"), ("project", "Projects"))),
              ("metric", (("tokens", "Tokens"), ("cost", "API cost"), ("credits", "Estimated credits")))]
    if state["view"] == "time":
        groups += [("grain", (("daily", "Daily"), ("hourly", "Hourly"))),
                   ("group", (("model", "Model"), ("project", "Project")))]
    for key, values in groups:
        controls.append('<span class="ub-segment">' + ''.join(command(nav, state, label, **({key: value, "detail": ""} if key == "grain" else {key: value})) for value, label in values) + '</span>')
    if state["view"] == "time":
        labels = {"weekly": "Weekly allowance", "balance": "Credit balance", "none": "None"}
        controls.append('<details class="ub-window-picker"><summary>' + labels[state["overlay"]] + '</summary><div>' +
            ''.join(command(nav, state, label, overlay=value) for value, label in labels.items()) + '</div></details>')
    content = f'<p class="ub-note">Selected range: {info["min_date"]} to {info["max_date"]} · {"Complete" if metadata["complete"] else "Partial"} local baseline</p>'
    accounting = 'Usage follows global project selection. ' if global_filtered else 'Captured local usage is not proof of complete account workload. '
    accounting += 'Language tokens include cached input and included reviews. Dedicated codex-auto-review approval checks are free for ChatGPT subscription use after the October 6 announcement: zero estimated credits, with tokens retained and API-excluded. Earlier review pricing remains unknown. API-equivalent dollars are not subscription charges. Images remain separate. Account overlays are account-wide, never project-filtered. Empty/future spans are unobserved, not measured zero workload.'
    content += '<details><summary>Scope and continuity evidence</summary><p class="ub-note">' + html.escape(accounting) + f' Calendar membership {info["interval_notation"]}.</p>'
    if reason:
        content += '<p class="ub-note">' + html.escape(reason) + '</p>'
    for key, window in metadata["evidence"]["windows"].items():
        content += '<p class="ub-note">' + html.escape(f'{window["start"]} to {window["end"]} | {window["limit_id"]} / {window["plan"] or "plan unavailable"} | {window["boundary"]} | observed continuity fragment, not a complete reset cycle') + '</p>'
        content += command(nav, state, "Inspect continuity interval", detail="evidence:" + key)
    content += '</details>'
    if state["detail"].startswith("evidence:"):
        key = state["detail"][9:]
        evidence_info = partition(key + ":summary", {})
        evidence_rows = [dict(v, project=p, label=project["label"], model=m) for p, project in evidence_info["projects"].items() for m, v in project["models"].items()]
        content += '<details open><summary>Capture-causal interval inspection, not calendar totals</summary>' + detail_table(evidence_rows, evidence_info["calibration"], nav, state, selected_projects=info["projects"]) + '</details>'
    models = sorted({m for p in info["projects"].values() for m in p["models"]})
    ranking = ranked_projects(info["projects"], state["metric"])
    if state["view"] == "time":
        content += time_view(info, state, nav, timezone, partition, ranking, command, uri, detail_table)
    else:
        maximum = max((total(p["models"].values())[state["metric"]] for _, p in ranking), default=0) or 1
        for key, project in ranking:
            value = total(project["models"].values())
            segments = ''.join(f'<span style="width:{v[state["metric"]] / maximum * 100:.6f}%;background:{COLORS[models.index(m) % len(COLORS)]}" title="{html.escape(project["label"] + " | " + m)}: {v[state["metric"]]!r} {state["metric"]}"></span>' for m, v in project["models"].items())
            label = command(nav, state, project["label"], detail="other" if key is None else "", project=key or "", view="time" if key is not None else "project")
            unknown = value["credit_unknown"] if state["metric"] == "credits" else value["unknown"] if state["metric"] == "cost" else 0
            content += f'<div class="ub-rank">{label}<div class="ub-stack">{segments}</div><strong title="{value[state["metric"]]!r}">{compact_decimal(value[state["metric"]], unit=state["metric"])}{" + unknown" if unknown else ""}{" + excluded" if state["metric"] == "cost" and value["api_excluded"] else ""}</strong></div>'
    if state["view"] == "project":
        legend = [(m, i) for i, m in enumerate(models)]
        content += '<div class="ub-legend">' + ''.join(f'<span><i style="background:{COLORS[i % len(COLORS)]}"></i>{html.escape(label)}</span>' for label, i in legend) + '</div>'
    rows = [dict(v, project=p, label=project["label"], model=m) for p, project in info["projects"].items() for m, v in project["models"].items()]
    if state["detail"] == "other":
        members = next((p["members"] for key, p in ranking if key is None), [])
        content += '<h3>Other · every retained project</h3>' + detail_table([r for r in rows if r["project"] in members], info["calibration"], nav, state, selected_projects=info["projects"])
    content += '<details><summary>All selected-range project/model values</summary>' + detail_table(rows, info["calibration"], nav, state, selected_projects=info["projects"]) + '</details>'
    values = info["total"]
    content += f'<p class="ub-note">Selected range totals: {compact_decimal(values["tokens"], unit="tokens")} tokens; {compact_decimal(values["cost"], unit="cost")} known API-equivalent; {values["unknown"]:,} unknown-price tokens; {values["api_excluded"]:,} API-excluded review tokens; {compact_decimal(values["credits"])} known estimated Standard credits; {values["credit_unknown"]:,} unknown-credit tokens. Estimates are not observed debits.</p>'
    return css() + f'<section class="section usage-breakdown" data-scope="{nav["scope"]}" data-state="{html.escape(json.dumps(state), quote=True)}"><h2>Usage &amp; Allowance Breakdown</h2><nav class="ub-controls" aria-label="Usage breakdown controls">{"".join(controls)}</nav>{content}</section>'
