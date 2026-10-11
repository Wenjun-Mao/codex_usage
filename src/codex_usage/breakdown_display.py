"""Actual-point display reduction; raw observations remain in day partitions."""
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
import json


def identity(point):
    return json.dumps({k: v for k, v in point.items() if not k.startswith("_")}, sort_keys=True, separators=(",", ":"))


def value(point, kind):
    if kind == "weekly":
        return Decimal(str(point["used_percent"]))
    return Decimal(point["balance"]) if point["balance"] is not None and not point["diagnostic"] and not point["unlimited"] else None


def series(point, kind):
    return (point["limit_id"], point["duration_minutes"]) if kind == "weekly" else ("balance",)


def reduce_points(points, kind, start, end, *, buckets=180, detect_boundaries=False):
    """Keep bucket endpoints/extrema plus both sides of every evidence boundary.

    Boundaries are exempt from the ordinary mark budget. In adversarial histories
    boundary count can dominate; no conflict is silently discarded for a cap.
    """
    groups = defaultdict(list)
    for point in points:
        groups[series(point, kind)].append(point)
    retained = {}
    for group in groups.values():
        ordered = sorted(group, key=lambda p: datetime.fromisoformat(p["timestamp"]).timestamp())
        bins = defaultdict(list)
        previous = None
        for p in ordered:
            at = datetime.fromisoformat(p["timestamp"]).timestamp()
            if start <= at < end:
                index = min(buckets-1, int((at-start)/max(.000001, end-start)*buckets))
                bins[index].append(p)
            boundary = p.get("_boundary", False)
            if previous and detect_boundaries:
                old = value(previous, kind)
                current = value(p, kind)
                same_time = datetime.fromisoformat(previous["timestamp"]) == datetime.fromisoformat(p["timestamp"])
                boundary |= (p["plan"] != previous["plan"] or old is None or current is None or
                    (kind == "weekly" and (p["resets_at"] != previous["resets_at"] or current < old)) or
                    (same_time and (p["plan"], current, p.get("resets_at"), p.get("reset_credits")) !=
                        (previous["plan"], old, previous.get("resets_at"), previous.get("reset_credits"))) or
                    (kind == "balance" and p["change"] is None))
                if boundary:
                    for candidate in (previous, p):
                        candidate = {**candidate, "_boundary": True}
                        retained[identity(candidate)] = candidate
            previous = p
            if p.get("_boundary"):
                retained[identity(p)] = p
        for items in bins.values():
            finite = [p for p in items if value(p, kind) is not None]
            selected = [items[0], items[-1]]
            if finite:
                selected += [min(finite, key=lambda p: value(p, kind)), max(finite, key=lambda p: value(p, kind))]
            for p in selected:
                if identity(p) not in retained:
                    retained[identity(p)] = p
    return sorted(retained.values(), key=lambda p: datetime.fromisoformat(p["timestamp"]).timestamp())


def display_partitions(points, kind, timezone):
    days = defaultdict(list)
    # Mark boundaries before splitting days, preserving cross-midnight neighbors.
    if not points:
        return {}
    first = min(datetime.fromisoformat(p["timestamp"]).timestamp() for p in points)
    last = max(datetime.fromisoformat(p["timestamp"]).timestamp() for p in points)
    reduced = reduce_points(points, kind, first, last + .000001, buckets=1, detect_boundaries=True)
    boundaries = {identity({k: v for k, v in p.items() if k != "_boundary"}) for p in reduced if p.get("_boundary")}
    signatures = defaultdict(set)
    if kind == "weekly":
        for p in points:
            signatures[(datetime.fromisoformat(p["timestamp"]).timestamp(), p["limit_id"])].add(
                (p["plan"], p["duration_minutes"], p["used_percent"], p["resets_at"], p.get("reset_credits")))
    for p in points:
        day = datetime.fromisoformat(p["timestamp"]).astimezone(timezone).date().isoformat()
        annotated = {**p, "_boundary": True} if identity(p) in boundaries else p
        if kind == "weekly" and len(signatures[(datetime.fromisoformat(p["timestamp"]).timestamp(), p["limit_id"])]) > 1:
            annotated = {**annotated, "_boundary": True, "_conflict": True}
        days[day].append(annotated)
    partitions = {}
    prefix = "meter-display:" if kind == "weekly" else "balance-display:"
    for day, raw in days.items():
        local = datetime.fromisoformat(day).replace(tzinfo=timezone)
        partitions[prefix + day] = {"count": len(raw), "points": reduce_points(raw, kind, local.timestamp(), (local+timedelta(days=1)).timestamp(), buckets=24)}
    return partitions
