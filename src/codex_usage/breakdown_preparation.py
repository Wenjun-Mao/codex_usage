"""Shared account partitions and compact directories, independent of date selection."""
from datetime import datetime

from codex_usage.breakdown_balances import balance_partitions
from codex_usage.breakdown_readings import partition_readings
from codex_usage.breakdown_intervals import BreakdownInterval


def interval_directory(window, timezone):
    start = datetime.fromisoformat(window["start"]).timestamp()
    end = datetime.fromisoformat(window["end"]).timestamp()
    interval = BreakdownInterval(start, end, causal=True)
    return {"start": start, "end": end,
        "min_date": datetime.fromtimestamp(start, timezone).date().isoformat(),
        "max_date": datetime.fromtimestamp(max(start, end - .000001), timezone).date().isoformat(),
        "latest_day": datetime.fromtimestamp(interval.occurrence_time(end) if end > start else start, timezone).date().isoformat()}


def prepare_account(evidence, timezone):
    """Partition raw evidence once; no project selection or usage valuation."""
    times = []
    days = {}
    partitions = {}
    for kind, name in (("weekly", "points"), ("balance", "balances")):
        points = evidence.pop(name)
        point_days, extent, raw = partition_readings(points, kind, timezone)
        partitions.update(raw)
        times.extend(extent)
        for day, stamp in point_days.items():
            days[day] = max(days.get(day, stamp), stamp)
        if kind == "balance":
            partitions.update(balance_partitions(points, timezone))
    ranges = {key: {**interval_directory(window, timezone), "partition_basis": key}
        for key, window in evidence["windows"].items()}
    cycle = evidence["cycle"]
    if cycle:
        alias = next((key for key, candidate in evidence["windows"].items()
            if all(candidate[field] == cycle[field] for field in
                ("start", "end", "limit_id", "plan", "boundary", "full_at"))), "cycle")
        ranges["cycle"] = {**interval_directory(cycle, timezone), "partition_basis": alias}
    return {"evidence": evidence, "ranges": ranges, "days": days,
        "extent": [min(times), max(times)] if times else []}, partitions
