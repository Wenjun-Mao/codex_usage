"""Raw day partitions and the adjacent readings required for lazy display."""
from collections import defaultdict
from datetime import datetime

from codex_usage.breakdown_display import display_partitions, series


def partition_readings(points, kind, timezone):
    """Preserve raw order; retain each series' two cross-day boundary neighbors."""
    prefix = "meter" if kind == "weekly" else "balance"
    raw_prefix = "meter:" if kind == "weekly" else "balance-points:"
    partitions = defaultdict(list)
    days, ordered = {}, []
    for point in points:
        at = datetime.fromisoformat(point["timestamp"])
        stamp = at.timestamp()
        day = at.astimezone(timezone).date().isoformat()
        partitions[raw_prefix + day].append(point)
        days[day] = max(days.get(day, stamp), stamp)
        ordered.append((stamp, day, point))
    previous = {}
    for _, day, point in sorted(ordered, key=lambda row: row[0]):
        key = series(point, kind)
        prior = previous.get(key)
        if prior is not None and prior[0] != day:
            old_day, old_point = prior
            partitions[prefix + "-context:" + day].append(old_point)
            partitions[prefix + "-context:" + old_day].append(point)
        previous[key] = (day, point)
    extent = [min(row[0] for row in ordered), max(row[0] for row in ordered)] if ordered else []
    return days, extent, dict(partitions)


def display_day(name, timezone, read):
    """Reduce only a requested day, with exactly its original boundary context."""
    prefix, day = name.split("-display:", 1)
    raw_prefix = "meter:" if prefix == "meter" else "balance-points:"
    points = read(raw_prefix + day) or []
    if not points:
        return {"count": 0, "points": []}
    context = read(prefix + "-context:" + day) or []
    return display_partitions(points + context,
        "weekly" if prefix == "meter" else "balance", timezone)[name]
