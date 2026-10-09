"""Additive composition of trusted dashboard-valued language records."""
from collections import defaultdict
from bisect import bisect_right
from datetime import UTC, datetime, timedelta

from codex_usage.allowance_costs import allowance_cost_components
from codex_usage.breakdown_evidence import interval_calibration
from codex_usage.breakdown_intervals import BreakdownInterval
from codex_usage.subscription_usage import is_included_subscription_usage


FIELDS = ("tokens", "cost", "unknown", "api_excluded", "credits", "credit_unknown", "allowance_cost", "allowance_unknown", "records")


def empty():
    return dict.fromkeys(FIELDS, 0)


def add(target, source):
    for key in FIELDS:
        target[key] += source[key]
    return target


def total(rows):
    result = empty()
    for row in rows:
        add(result, row)
    return result


def local_hours(day, timezone):
    start = datetime.fromisoformat(day).replace(tzinfo=timezone)
    end = (start + timedelta(days=1)).astimezone(UTC)
    at = start.astimezone(UTC)
    result = []
    def identity(value):
        local = value.astimezone(timezone)
        return local.date(), local.hour, local.utcoffset()
    first = at
    previous = identity(at)
    # Sample chronological UTC, then locate the exact transition second. Local
    # hour floors can be nonexistent at partial-hour DST jumps (e.g. Chatham).
    while at < end:
        following = min(end, at + timedelta(minutes=1))
        current = identity(following) if following < end else None
        if current != previous:
            boundary = following
            if following < end:
                left, right = int(at.timestamp()), int(following.timestamp())
                while left + 1 < right:
                    middle = (left + right) // 2
                    if identity(datetime.fromtimestamp(middle, UTC)) == previous:
                        left = middle
                    else:
                        right = middle
                boundary = datetime.fromtimestamp(right, UTC)
            local = first.astimezone(timezone)
            result.append({"key": first.isoformat(), "label": local.strftime("%H:%M %z"),
                           "start": first.timestamp(), "end": boundary.timestamp()})
            first, previous = boundary, current
        at = following
    return result


def aggregate(valued, timezone, evidence, *, start, end, complete, causal=False):
    interval = BreakdownInterval(start, end, causal)
    days = defaultdict(list)
    projects, daily = {}, {}
    cells = {}
    calendars = {}
    for item in valued:
        record, summary = item.record, item.summary
        at = record.timestamp.timestamp()
        if not interval.contains(at):
            continue
        occurrence_at = interval.occurrence_time(at)
        local = datetime.fromtimestamp(occurrence_at, timezone)
        day = local.date().isoformat()
        if day not in calendars:
            buckets = local_hours(day, timezone)
            calendars[day] = buckets, [h["start"] for h in buckets]
        buckets, starts = calendars[day]
        hour = buckets[bisect_right(starts, occurrence_at) - 1]["key"]
        key = (hour, record.project_key, record.model)
        if key not in cells:
            cells[key] = dict(empty(), hour=hour, project=record.project_key,
                              model=record.model, label=record.project_label, day=day)
        allowance_cost, allowance_unknown = allowance_cost_components(summary.cost,
            model=record.model, at=record.timestamp, total_tokens=summary.usage.total_tokens)
        excluded = summary.cost.unpriced_tokens if is_included_subscription_usage(record.model, record.timestamp) else 0
        add(cells[key], {"tokens": summary.usage.total_tokens, "cost": summary.cost.total_usd,
            "unknown": summary.cost.unpriced_tokens - excluded, "api_excluded": excluded, "credits": summary.credits.total_credits,
            "credit_unknown": summary.credits.unpriced_tokens, "records": summary.record_count,
            "allowance_cost": allowance_cost, "allowance_unknown": allowance_unknown})
    for row in cells.values():
        days[row["day"]].append(row)
        project = projects.setdefault(row["project"], {"label": row["label"], "models": {}})
        add(project["models"].setdefault(row["model"], empty()), row)
        add(daily.setdefault(row["day"], empty()), row)
    all_total = total(cells.values())
    def calibrate(bounds, values):
        if not bounds.causal:
            return {"value": None, "reason": "calendar membership differs from capture-causal (origin, capture] evidence"}
        return interval_calibration(evidence, bounds.start, bounds.end,
            values["allowance_cost"], values["allowance_unknown"], complete)
    calibration = calibrate(interval, all_total)
    partitions = {}
    for day, rows in days.items():
        hour_calibrations = {}
        for hour in local_hours(day, timezone):
            values = total(r for r in rows if r["hour"] == hour["key"])
            hour_calibrations[hour["key"]] = calibrate(interval.clip(hour["start"], hour["end"]), values)
        partitions["day:" + day] = {"rows": rows, "calibrations": hour_calibrations}
    for project in projects:
        partitions["project:" + project] = [r for r in cells.values() if r["project"] == project]
    return {"projects": projects, "daily": daily, "total": all_total,
            "calibration": calibration, "start": start, "end": end,
            "causal": causal, "interval_notation": interval.notation}, partitions


def ranked_projects(projects, metric):
    ordered = sorted(projects, key=lambda p: (-total(projects[p]["models"].values())[metric], p))
    result = [(p, projects[p]) for p in ordered[:10]]
    if len(ordered) > 10:
        models = {}
        for p in ordered[10:]:
            for model, value in projects[p]["models"].items():
                add(models.setdefault(model, empty()), value)
        result.append((None, {"label": "Other", "models": models, "members": ordered[10:]}))
    return result
