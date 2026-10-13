"""Actual-point display reduction; raw observations remain in day partitions."""
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal


def identity(point):
    return tuple(sorted((k, v) for k, v in point.items() if not k.startswith("_")))


def value(point, kind):
    if kind == "weekly":
        return Decimal(str(point["used_percent"]))
    return Decimal(point["balance"]) if point["balance"] is not None and not point["diagnostic"] and not point["unlimited"] else None


def series(point, kind):
    return (point["limit_id"], point["duration_minutes"]) if kind == "weekly" else ("balance",)


@dataclass(frozen=True, slots=True)
class _DisplayPoint:
    raw: dict
    at: datetime
    stamp: float
    signature: tuple
    metric: Decimal | None
    series: tuple

    @classmethod
    def prepare(cls, point, kind):
        at = datetime.fromisoformat(point["timestamp"])
        return cls(point, at, at.timestamp(), identity(point), value(point, kind), series(point, kind))


def reduce_points(points, kind, start, end, *, buckets=180, detect_boundaries=False):
    prepared = [_DisplayPoint.prepare(p, kind) for p in points]
    return [p.raw for p in _reduce_points(prepared, kind, start, end,
        buckets=buckets, detect_boundaries=detect_boundaries)]


def _reduce_points(points, kind, start, end, *, buckets, detect_boundaries=False):
    """Keep bucket endpoints/extrema plus both sides of every evidence boundary.

    Boundaries are exempt from the ordinary mark budget. In adversarial histories
    boundary count can dominate; no conflict is silently discarded for a cap.
    """
    groups = defaultdict(list)
    for point in points:
        groups[point.series].append(point)
    retained = {}
    for group in groups.values():
        ordered = sorted(group, key=lambda p: p.stamp)
        bins = defaultdict(list)
        previous = None
        for p in ordered:
            at = p.stamp
            if start <= at < end:
                index = min(buckets-1, int((at-start)/max(.000001, end-start)*buckets))
                bins[index].append(p)
            boundary = p.raw.get("_boundary", False)
            if previous and detect_boundaries:
                old, current = previous.metric, p.metric
                a, b = previous.raw, p.raw
                same_time = previous.at == p.at
                boundary |= (b["plan"] != a["plan"] or old is None or current is None or
                    (kind == "weekly" and (b["resets_at"] != a["resets_at"] or current < old)) or
                    (same_time and (b["plan"], current, b.get("resets_at"), b.get("reset_credits")) !=
                        (a["plan"], old, a.get("resets_at"), a.get("reset_credits"))) or
                    (kind == "balance" and b["change"] is None))
                if boundary:
                    for candidate in (previous, p):
                        candidate = replace(candidate, raw={**candidate.raw, "_boundary": True})
                        retained[candidate.signature] = candidate
            previous = p
            if p.raw.get("_boundary"):
                retained[p.signature] = p
        for items in bins.values():
            finite = [p for p in items if p.metric is not None]
            selected = [items[0], items[-1]]
            if finite:
                selected += [min(finite, key=lambda p: p.metric), max(finite, key=lambda p: p.metric)]
            for p in selected:
                if p.signature not in retained:
                    retained[p.signature] = p
    return sorted(retained.values(), key=lambda p: p.stamp)


def display_partitions(points, kind, timezone):
    days = defaultdict(list)
    # Mark boundaries before splitting days, preserving cross-midnight neighbors.
    if not points:
        return {}
    prepared = [_DisplayPoint.prepare(p, kind) for p in points]
    first = min(p.stamp for p in prepared)
    last = max(p.stamp for p in prepared)
    reduced = _reduce_points(prepared, kind, first, last + .000001, buckets=1, detect_boundaries=True)
    boundaries = {p.signature for p in reduced if p.raw.get("_boundary")}
    signatures = defaultdict(set)
    if kind == "weekly":
        for item in prepared:
            p = item.raw
            signatures[(item.stamp, p["limit_id"])].add(
                (p["plan"], p["duration_minutes"], p["used_percent"], p["resets_at"], p.get("reset_credits")))
    for item in prepared:
        p = item.raw
        day = item.at.astimezone(timezone).date().isoformat()
        annotated = {**p, "_boundary": True} if item.signature in boundaries else p
        if kind == "weekly" and len(signatures[(item.stamp, p["limit_id"])]) > 1:
            annotated = {**annotated, "_boundary": True, "_conflict": True}
        days[day].append(replace(item, raw=annotated) if annotated is not p else item)
    partitions = {}
    prefix = "meter-display:" if kind == "weekly" else "balance-display:"
    for day, raw in days.items():
        local = datetime.fromisoformat(day).replace(tzinfo=timezone)
        partitions[prefix + day] = {"count": len(raw), "points": [p.raw for p in _reduce_points(
            raw, kind, local.timestamp(), (local+timedelta(days=1)).timestamp(), buckets=24)]}
    return partitions
