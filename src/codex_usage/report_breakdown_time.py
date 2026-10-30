"""Bounded chronological windows and cached full-calendar composition."""
import html
from collections import defaultdict
from datetime import datetime, timedelta

from codex_usage.breakdown_aggregation import add, empty, local_hours
from codex_usage.report_usage_breakdown_chart import plot
from codex_usage.report_breakdown_overlay import overlay
from codex_usage.report_usage_breakdown_chart import COLORS
from codex_usage.breakdown_display import identity
from codex_usage.report_breakdown_axis import timestamp_label
from codex_usage.report_breakdown_numbers import metric_label


def dates_between(first, last):
    at = datetime.fromisoformat(first).date()
    end = datetime.fromisoformat(last).date()
    while at <= end:
        yield at.isoformat()
        at += timedelta(days=1)


def window_days(info, day):
    end = min(info["max_date"], max(info["min_date"], day))
    start = max(info["min_date"], (datetime.fromisoformat(end) - timedelta(days=6)).date().isoformat())
    return list(dates_between(start, end))


def time_view(info, state, nav, timezone, partition, ranking, command, uri, detail_table):
    daily = state["grain"] == "daily"
    days = list(dates_between(info["min_date"], info["max_date"])) if daily else window_days(info, state["day"])
    rows = []
    if not daily:
        for day in days:
            suffix = ":project:" + state["project"] if state["project"] else ""
            rows.extend(partition("selected:day:" + day + suffix, {"rows": []})["rows"])
    stacks = info["daily_stacks"]
    if daily and state["project"]:
        stacks = {}
        for day in days:
            models = info["daily_project_models"].get(day, {}).get(state["project"], {})
            combined = empty()
            for v in models.values():
                add(combined, v)
            stacks[day] = {"model": models, "project": {state["project"]: combined}}
    content = ""
    if not daily:
        content += f'<div class="ub-window"><strong>Hourly: {days[0]} to {days[-1]}</strong>'
        for delta, label in ((-7, "Previous"), (7, "Next"), (0, "Latest")):
            target = min(info["max_date"], max(info["min_date"], (datetime.fromisoformat(state["day"]) + timedelta(days=delta)).date().isoformat())) if delta else info["latest_day"]
            enabled = days[0] > info["min_date"] if delta < 0 else days[-1] < info["max_date"] if delta > 0 else target != state["day"]
            content += command(nav, state, label, day=target, detail="") if enabled else f'<span aria-disabled="true">{label}</span>'
        content += '</div>'
    if state["project"]:
        content += '<p class="ub-note">Usage detail: ' + html.escape(info["projects"][state["project"]]["label"]) + ' · overlay remains account-wide</p>' + command(nav, state, "All projects", project="", detail="")
    buckets = []
    for day in days:
        hours = [{"key": day, "label": day, "start": datetime.fromisoformat(day).replace(tzinfo=timezone).timestamp(), "end": (datetime.fromisoformat(day).replace(tzinfo=timezone) + timedelta(days=1)).timestamp()}] if daily else local_hours(day, timezone)
        buckets.extend(dict(h, day=day, start=max(info["start"], h["start"]), end=min(info["end"], h["end"])) for h in hours if h["end"] > info["start"] and h["start"] < info["end"])
    row_groups = defaultdict(list)
    for row in rows:
        row_groups[row["hour"]].append(row)
    top = {key for key, _ in ranking if key is not None}
    names = {p: v["label"] for p, v in info["projects"].items()}
    names["__other_projects__"] = "Other"
    labels = sorted({m for p in info["projects"].values() for m in p["models"]}) if state["group"] == "model" else sorted(info["projects"]) + ["__other_projects__"]
    bars, links, unknown, descriptions = [], [], [], []
    for bucket in buckets:
        composition = stacks.get(bucket["day"], {}).get(state["group"], {}) if daily else {}
        if not daily:
            for row in row_groups[bucket["key"]]:
                add(composition.setdefault(row[state["group"]], empty()), row)
        values = defaultdict(float)
        for key, value in composition.items():
            label = key if state["group"] == "model" or key in top or state["project"] else "__other_projects__"
            values[label] += value[state["metric"]]
        bars.append(values)
        unknown.append(any(v["credit_unknown"] if state["metric"] == "credits" else v["unknown"] or v["api_excluded"] if state["metric"] == "cost" else False for v in composition.values()))
        descriptions.append("; ".join(f'{names.get(k, k) if state["group"] == "project" else k}: {metric_label(v[state["metric"]], state["metric"])}' for k, v in composition.items()) or "No captured local usage; not measured zero workload")
        changes = {"grain": "hourly", "day": bucket["day"], "detail": "day:" + bucket["day"]} if daily else {"detail": "hour:" + bucket["key"]}
        links.append(uri(command(nav, state, bucket["label"], **changes)))
    points = {}
    if state["overlay"] != "none":
        for day in days:
            for p in partition(("meter-display:" if state["overlay"] == "weekly" else "balance-display:") + day, {"points": []})["points"]:
                points[json_identity(p)] = p
    content += plot(bars, metric=state["metric"], labels=labels, links=links, incomplete=unknown, intervals=[(b["start"], b["end"]) for b in buckets], display_names=names if state["group"] == "project" else None, bucket_labels=[b["day"] if daily else timestamp_label(b["start"], timezone) for b in buckets], bucket_details=descriptions, timezone=timezone, daily=daily, title="Daily selected range" if daily else "Chronological local hours", account_points=list(points.values()), account_overlay=state["overlay"], color_domain=state["group"])
    if state["overlay"] != "none":
        content += '<details><summary>Exact account readings by local day</summary><div class="ub-hour-labels">' + ''.join(command(nav, state, day, detail="readings:" + day) for day in days) + '</div></details>'
        if state["detail"].startswith("readings:"):
            day = state["detail"][9:]
            raw = partition(("meter:" if state["overlay"] == "weekly" else "balance:") + day, [])
            local = datetime.fromisoformat(day).replace(tzinfo=timezone)
            _, _, _, exact = overlay(raw, state["overlay"], max(info["start"], local.timestamp()), min(info["end"], (local+timedelta(days=1)).timestamp()), timezone, COLORS, inspection=True)
            content += '<h3>Exact account readings · ' + day + '</h3>' + exact
    content += '<details><summary>Inspect every ' + ("day" if daily else "hour occurrence") + '</summary><div class="ub-hour-labels">' + ''.join(command(nav, state, b["day"] + " " + b["label"], **({"grain": "hourly", "day": b["day"], "detail": "day:" + b["day"]} if daily else {"detail": "hour:" + b["key"]})) for b in buckets) + '</div></details>'
    if state["detail"].startswith(("day:", "hour:")):
        kind, key = state["detail"].split(":", 1)
        selected = [r for r in rows if r[kind] == key]
        content += '<h3>Exact detail · ' + html.escape(key) + '</h3>' + detail_table(selected, info["calibration"], nav, state, selected_projects=info["projects"])
    elif not daily:
        content += '<details><summary>Exact hourly project/model values</summary>' + detail_table(rows, info["calibration"], nav, state, selected_projects=info["projects"]) + '</details>'
    return content


def json_identity(point):
    return identity(point)
