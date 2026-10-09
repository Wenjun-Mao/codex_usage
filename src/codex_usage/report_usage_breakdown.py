"""Native command links, composition charts and complete exact-value inspection."""
import html
import json
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import quote

from codex_usage.breakdown_aggregation import empty, add, local_hours, ranked_projects, total
from codex_usage.report_usage_breakdown_chart import COLORS, css, meter, plot
from codex_usage.report_breakdown_axis import timestamp_label
from codex_usage.report_breakdown_balances import balances


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


def detail_table(rows, calibration, nav, state):
    body = []
    for row in sorted(rows, key=lambda r: (r["project"], r["model"], r.get("hour", ""))):
        cost = f'${row["cost"]:.9g}'
        if row["unknown"]:
            cost += f' + unknown ({row["unknown"]:,} tokens)'
        if row["api_excluded"]:
            cost += f'; API-excluded review tokens {row["api_excluded"]:,}'
        credits = f'{row["credits"]:.9g}' + (f' + unknown ({row["credit_unknown"]:,} tokens)' if row["credit_unknown"] else "")
        pp = f'{100 * row["allowance_cost"] / calibration["value"]:.9g} pp estimated' if calibration.get("value") else "Unavailable"
        label = command(nav, state, row["label"], view="hour", detail="project:" + row["project"])
        body.append(f'<tr><td>{label}</td><td>{html.escape(row["model"])}</td><td>{html.escape(row.get("hour", "Interval total"))}</td><td>{row["tokens"]:,}</td><td>{cost}</td><td>{credits}</td><td>{pp}</td></tr>')
    explanation = (f'Capture-causal, cost-calibrated retrospective interval contributions; {calibration["confidence"]}; {calibration["reference_kind"]}; reference observed through {calibration["reference_end"]}, available at {calibration["available_at"]}. Not a forecast or exact quota attribution.'
                   if calibration.get("value") else 'Estimated percentage-point contributions unavailable: ' + calibration["reason"] + '.')
    return (f'<p class="ub-note">{html.escape(explanation)}</p><div class="table-wrap"><table><thead><tr><th>Project</th><th>Model</th><th>UTC occurrence</th><th>Tokens</th><th>API-equivalent cost</th><th>Estimated credits</th><th>Included contribution</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def render_breakdown(metadata, info, state, nav, reason, timezone, partition, *, global_filtered):
    basis = state["basis"]
    controls = []
    for key, values in (("view", (("hour", "Hour"), ("project", "Project"))),
                        ("metric", (("tokens", "Tokens"), ("cost", "API cost"), ("credits", "Estimated credits")))):
        links = []
        for value, label in values:
            changes = {key: value}
            links.append(command(nav, state, label, **changes))
        controls.append('<span class="ub-segment">' + ''.join(links) + '</span>')
    options = []
    if "cycle" in metadata["ranges"] and not reason:
        options.append(command(nav, state, "Current observed window", basis="cycle",
            day=metadata["ranges"]["cycle"]["latest_day"], detail=""))
    for key, window in metadata["evidence"]["windows"].items():
        label = (f'{timestamp_label(datetime.fromisoformat(window["start"]).timestamp(), timezone)} to '
            f'{timestamp_label(datetime.fromisoformat(window["end"]).timestamp(), timezone)} · '
            f'{window["limit_id"]} / {window["plan"] or "plan unavailable"} · {window["boundary"]} · observed portion')
        options.append(command(nav, state, label, basis=key, day=metadata["ranges"][key]["latest_day"], detail=""))
    options.append(command(nav, state, "Selected range", basis="selected",
        day=metadata["ranges"]["selected"]["latest_day"], detail=""))
    selected_label = "Current observed window" if basis == "cycle" else "Selected range"
    if basis not in {"cycle", "selected"}:
        window = metadata["evidence"]["windows"][basis]
        dates = [datetime.fromisoformat(window[k]).astimezone(timezone).date().isoformat() for k in ("start", "end")]
        selected_label = f'{dates[0]} to {dates[1]} · {window["limit_id"]} / {window["plan"] or "plan unavailable"} · {window["boundary"]}'
    controls.append(f'<details class="ub-window-picker"><summary>{html.escape(selected_label)}</summary><div>{"".join(options)}</div></details>')
    if state["view"] == "hour":
        controls.append('<span class="ub-segment">' + ''.join(command(nav, state, label, group=value)
            for value, label in (("model", "By model"), ("project", "By project"))) + '</span>')
    cycle = metadata["evidence"]["cycle"] if basis == "cycle" else metadata["evidence"]["windows"].get(basis)
    notice = (f'Observed weekly portion; opening not assumed. {cycle["limit_id"]} / {cycle["plan"] or "plan unavailable"}. Continuity boundary: {cycle["boundary"]}; {cycle["corrections"]} reported corrections.'
              if cycle else 'Dashboard selected range.' + (f' Current cycle unavailable: {reason}.' if reason else ""))
    accounting = 'Usage follows global project selection.' if global_filtered else 'Captured local usage; not proof of complete account workload.'
    accounting += ' Language tokens include cached input and included reviews; API-equivalent dollars are not subscription charges. Images remain separate.'
    start_label = timestamp_label(info["start"], timezone)
    end_label = timestamp_label(info["end"], timezone)
    content = f'<p class="ub-note">{start_label} to {end_label} · {"Complete local baseline" if metadata["complete"] else "Partial local baseline"}</p><details><summary>Scope and accounting evidence</summary><p class="ub-note">{html.escape(notice + " " + accounting)} Membership {info["interval_notation"]}.</p></details>'
    model_names = sorted({m for p in info["projects"].values() for m in p["models"]})
    ranking = ranked_projects(info["projects"], state["metric"])
    if state["view"] == "project":
        observed_maximum = max((total(p["models"].values())[state["metric"]] for _, p in ranking), default=0)
        maximum = observed_maximum or 1
        units = {"tokens": "tokens", "cost": "known USD", "credits": "estimated Standard credits"}
        content += f'<p class="ub-note">Ranked interval totals · visible scale 0 to {observed_maximum:.9g} {units[state["metric"]]}</p>'
        for key, project in ranking:
            value = total(project["models"].values())
            segments = ''.join(f'<span style="width:{v[state["metric"]] / maximum * 100:.6f}%;background:{COLORS[model_names.index(m) % len(COLORS)]}" title="{html.escape(start_label + " to " + end_label + " | " + project["label"] + " | " + m)}: {v[state["metric"]]:.9g} {state["metric"]}"></span>' for m, v in project["models"].items())
            below = any(0 < v[state["metric"]] / maximum < .001 for v in project["models"].values())
            label = command(nav, state, project["label"], detail="other" if key is None else "project:" + key, view="hour" if key is not None else "project")
            unknown = value["credit_unknown"] if state["metric"] == "credits" else value["unknown"] if state["metric"] == "cost" else 0
            content += f'<div class="ub-rank">{label}<div class="ub-stack">{segments}</div><strong>{value[state["metric"]]:,.9g}{" *" if below else ""}{" + unknown" if unknown else ""}{" + excluded" if state["metric"] == "cost" and value["api_excluded"] else ""}</strong></div>'
        content += '<small>* Nonzero stacks below chart resolution retain exact values in details. API-excluded reviews are not zero-cost API usage.</small>'
    else:
        content += hour_view(metadata, info, state, nav, timezone, partition, ranking)
    legend = model_names if state["view"] == "project" or state["group"] == "model" else [p["label"] for _, p in ranking]
    content += '<div class="ub-legend">' + ''.join(f'<span><i style="background:{COLORS[i % len(COLORS)]}"></i>{html.escape(label)}</span>' for i, label in enumerate(legend)) + '</div>'
    rows = [dict(v, project=p, label=project["label"], model=m) for p, project in info["projects"].items() for m, v in project["models"].items()]
    if state["detail"] == "other":
        members = next((p["members"] for key, p in ranking if key is None), [])
        rows = [r for r in rows if r["project"] in members]
        content += '<h3>Other · every retained project</h3>' + detail_table(rows, info["calibration"], nav, state)
    content += '<details><summary>All interval project/model values</summary>' + detail_table(rows, info["calibration"], nav, state) + '</details>'
    values = info["total"]
    content += f'<p class="ub-note">Interval totals: {values["tokens"]:,} tokens; ${values["cost"]:.9g} known API-equivalent; {values["unknown"]:,} unknown-price tokens; {values["api_excluded"]:,} API-excluded review tokens; {values["credits"]:.9g} known estimated Standard credits; {values["credit_unknown"]:,} unknown-credit tokens. Credit estimates are not observed per-event debits.</p>'
    return css() + f'<section class="section usage-breakdown" data-scope="{nav["scope"]}" data-state="{html.escape(json.dumps(state), quote=True)}"><h2>Usage &amp; Allowance Breakdown</h2><nav class="ub-controls" aria-label="Usage breakdown controls">{"".join(controls)}</nav>{content}</section>'


def hour_view(metadata, info, state, nav, timezone, partition, ranking):
    basis, day = state["basis"], state["day"]
    selected_project = state["detail"][8:] if state["detail"].startswith("project:") else None
    data = partition(basis + ":day:" + day, {"rows": [], "calibrations": {}})
    rows = data["rows"]
    daily = info["daily"]
    if selected_project is not None:
        project_rows = partition(basis + ":project:" + selected_project, [])
        rows = [r for r in rows if r["project"] == selected_project]
        daily = {}
        for row in project_rows:
            add(daily.setdefault(row["day"], empty()), row)
    content = '<h3>Full-range daily context' + (' · selected project' if selected_project else '') + '</h3>'
    dates = []
    at = datetime.fromisoformat(info["min_date"]).date()
    last = datetime.fromisoformat(info["max_date"]).date()
    while at <= last:
        dates.append(at.isoformat())
        at += timedelta(days=1)
    daily_intervals = [(max(info["start"], datetime.fromisoformat(d).replace(tzinfo=timezone).timestamp()),
        min(info["end"], (datetime.fromisoformat(d).replace(tzinfo=timezone) + timedelta(days=1)).timestamp())) for d in dates]
    project_context = info["projects"][selected_project]["label"] if selected_project else "All selected projects"
    content += plot([{ "Captured": daily.get(d, empty())[state["metric"]]} for d in dates],
                    metric=state["metric"], labels=["Captured"], title="Daily context",
                    intervals=daily_intervals, timezone=timezone, daily=True,
                    bucket_labels=dates, bucket_details=[project_context + " / All models"] * len(dates),
                    incomplete=[bool(daily.get(d, empty())["credit_unknown"]) if state["metric"] == "credits" else
                        bool(daily.get(d, empty())["unknown"] or daily.get(d, empty())["api_excluded"]) if state["metric"] == "cost" else False for d in dates],
                    links=[uri(command(nav, state, d, day=d, detail="project:" + selected_project if selected_project else "")) for d in dates])
    content += '<details><summary>Inspect every day</summary><div class="ub-hour-labels">' + ''.join(command(nav, state, d, day=d, detail="project:" + selected_project if selected_project else "") for d in dates) + '</div></details>'
    content += f'<div class="ub-window"><strong>{day} · one local day</strong>'
    for delta, label in ((-1, "Previous"), (1, "Next"), (0, "Latest day")):
        target = (datetime.fromisoformat(day).date() + timedelta(days=delta)).isoformat() if delta else info["latest_day"]
        content += (command(nav, state, label, day=target, detail="project:" + selected_project if selected_project else "")
                    if info["min_date"] <= target <= info["max_date"] and target != day else f'<span aria-disabled="true">{label}</span>')
    content += command(nav, state, "All projects", detail="") + '</div>'
    buckets = [h for h in local_hours(day, timezone) if h["end"] > info["start"] and h["start"] < info["end"]]
    group_labels = {(key if key is not None else "__other_projects__"): p["label"] for key, p in ranking}
    top = {key for key, _ in ranking if key is not None}
    bars, labels, links, incomplete, bucket_details = [], set(), [], [], []
    for hour in buckets:
        values = defaultdict(float)
        for row in rows:
            if row["hour"] == hour["key"]:
                label = row["model"] if state["group"] == "model" else row["project"] if row["project"] in top else "__other_projects__"
                values[label] += row[state["metric"]]
        bars.append(values)
        incomplete.append(any((r["unknown"] or r["api_excluded"]) if state["metric"] == "cost" else r["credit_unknown"] if state["metric"] == "credits" else False for r in rows if r["hour"] == hour["key"]))
        labels.update(values)
        links.append(uri(command(nav, state, hour["label"], detail="hour:" + hour["key"])))
        bucket_details.append("; ".join(f'{r["label"]} / {r["model"]}: {r[state["metric"]]:.9g} {state["metric"]}' for r in rows if r["hour"] == hour["key"]) or project_context + " / All models: 0 known")
    color_order = sorted({m for p in info["projects"].values() for m in p["models"]}) if state["group"] == "model" else list(group_labels)
    content += plot(bars, metric=state["metric"], labels=color_order, links=links, incomplete=incomplete,
                    display_names=group_labels if state["group"] == "project" else None,
                    bucket_labels=[day + " " + h["label"] for h in buckets], bucket_details=bucket_details, timezone=timezone,
                    intervals=[(max(info["start"], h["start"]), min(info["end"], h["end"])) for h in buckets],
                    title="Chronological local hour occurrences")
    if any(incomplete):
        content += '<small>Open diamonds: unknown estimates or API-excluded cost, not known zero.</small>'
    content += '<details><summary>Inspect every hour occurrence</summary><div class="ub-hour-labels">' + ''.join(command(nav, state, h["label"], detail="hour:" + h["key"]) for h in buckets) + '</div></details>'
    first = max(info["start"], buckets[0]["start"]) if buckets else info["start"]
    end = min(info["end"], buckets[-1]["end"]) if buckets else info["end"]
    points = [p for p in partition("meter:" + day, []) if first <= datetime.fromisoformat(p["timestamp"]).timestamp() <= end]
    end_day = datetime.fromtimestamp(end, timezone).date().isoformat()
    if end_day != day:
        points.extend(p for p in partition("meter:" + end_day, [])
            if first <= datetime.fromisoformat(p["timestamp"]).timestamp() <= end)
    weekly_identity = None
    if state["basis"] != "selected":
        cycle = metadata["evidence"]["cycle"] if basis == "cycle" else metadata["evidence"]["windows"][basis]
        weekly_identity = (cycle["limit_id"], cycle["plan"])
    content += meter(points, first, end, timezone, weekly_identity=weekly_identity)
    balance_points = partition("balance:" + day, [])
    if end_day != day:
        balance_points = list({p["read_id"]: p for p in balance_points + partition("balance:" + end_day, [])}.values())
    content += balances(balance_points, first, end, timezone)
    calibration = {"value": None, "reason": "no exact-interval calibration for this local day"}
    if state["detail"].startswith("hour:"):
        key = state["detail"][5:]
        rows = [r for r in data["rows"] if r["hour"] == key]
        calibration = data["calibrations"].get(key, calibration)
        content += f'<h3>Hour detail · {html.escape(key)}</h3>'
    elif selected_project is not None:
        content += '<h3>Project hourly detail</h3>'
    else:
        content += '<details><summary>Exact hourly project/model values</summary>'
    content += detail_table(rows, calibration, nav, state)
    if not state["detail"].startswith("hour:") and selected_project is None:
        content += '</details>'
    return content
