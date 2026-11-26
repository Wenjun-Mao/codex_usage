"""Protect quota fits from stale task snapshots without changing raw evidence."""
from bisect import bisect_right
from itertools import groupby


LIVE_FLOOR_MAX_AGE_SECONDS = 30 * 60
TASK_SOURCES = frozenset({"Task snapshot", "Recovered task snapshot"})


def _series(point):
    return point.limit_id, point.duration_minutes


def _meter(point):
    return point.plan, point.resets_at, point.reset_credits, point.used_percent


def _live_timelines(live_points):
    series = {}
    for point in live_points:
        if point.duration_minutes:
            series.setdefault(_series(point), []).append(point)
    timelines = {}
    for key, readings in series.items():
        times, anchors = [], []
        ordered = sorted(readings, key=lambda point: point.timestamp_seconds)
        for stamp, group in groupby(ordered, key=lambda point: point.timestamp_seconds):
            first, *others = group
            times.append(stamp)
            anchors.append(first if all(_meter(point) == _meter(first) for point in others) else None)
        timelines[key] = times, anchors
    return timelines


def _stale_under_live_floor(point, timeline):
    if timeline is None:
        return False
    times, anchors = timeline
    stamp = point.timestamp_seconds
    index = bisect_right(times, stamp) - 1
    if index < 0 or not 0 < stamp - times[index] <= LIVE_FLOOR_MAX_AGE_SECONDS:
        return False
    anchor = anchors[index]
    return (
        anchor is not None
        and bool(anchor.plan)
        and point.plan == anchor.plan
        and point.resets_at == anchor.resets_at
        and anchor.resets_at is not None
        and stamp < anchor.resets_at
        and anchor.reset_credits is not None
        and point.reset_credits in (None, anchor.reset_credits)
        and anchor.used_percent - point.used_percent >= 5
    )


def calibration_points(points, provenance, live_points):
    """Use only earlier live evidence, so future readings cannot alter a prefix."""
    if not live_points:
        return points
    timelines = _live_timelines(live_points)
    return tuple(
        point for point in points
        if point in live_points
        or not TASK_SOURCES.intersection(provenance.get(point, ()))
        or not _stale_under_live_floor(point, timelines.get(_series(point)))
    )
