"""Official display continuity and corroboration of task-only raw evidence."""
from bisect import bisect_left, bisect_right

from codex_usage.allowance_windows import seconds


def _corroboration(point, left, right, owner):
    if owner["uncertain"]:
        return "official range boundary uncertain"
    if point.plan and point.plan != owner["plan"]:
        return "task plan conflicts with official range"
    if not min(left.used_percent, right.used_percent) <= point.used_percent <= max(left.used_percent, right.used_percent):
        return "task meter outside bracketing official readings"
    if point.resets_at is not None and left.resets_at is None and right.resets_at is None:
        return "task deadline not corroborated by official readings"
    if point.reset_credits is not None and left.reset_credits is None and right.reset_credits is None:
        return "task reset credits not corroborated by official readings"
    for official in (left, right):
        if point.resets_at is not None and official.resets_at is not None and abs(point.resets_at-official.resets_at) > 60:
            return "task deadline conflicts with official range"
        if point.reset_credits is not None and official.reset_credits is not None and point.reset_credits != official.reset_credits:
            return "task reset credits conflict with official range"
    return ""


def source_aware_fragments(points, positions, provenance, live_points, segment):
    """Only official readings advance official continuity; tasks cannot rebase it.

    A task can join an observed official range only when two official captures
    in that same coherent range bracket and corroborate it. No extrapolation
    from a lone anchor supplies a period opening or a missing full duration.
    """
    live = (set(live_points) if live_points is not None else
            {point for point in points if "Live probe" in provenance[point]})
    official = [point for point in points if point in live]
    fragments, owners = segment(official, positions)
    series = {}
    for point in official:
        series.setdefault((point.limit_id, point.duration_minutes), []).append(point)
    times = {key: [seconds(point) for point in values] for key, values in series.items()}
    historical, uncertain, reasons = [], [], {}
    for point in points:
        if point in live:
            continue
        key = (point.limit_id, point.duration_minutes)
        readings = series.get(key)
        time = seconds(point)
        if not readings or time < times[key][0]:
            historical.append(point)
            continue
        left = bisect_right(times[key], time)-1
        right = bisect_left(times[key], time)
        reason = "task reading outside official observed coverage"
        if left >= 0 and right < len(readings):
            before, after = readings[left], readings[right]
            owner = owners[before]
            if owner is owners[after]:
                reason = _corroboration(point, before, after, owner)
                if not reason:
                    owner["capture_indices"].append(positions[point])
                    owners[point] = owner
                    continue
            else:
                reason = "task reading between distinct official ranges"
        uncertain.append(point)
        reasons[positions[point]] = reason
    earlier, earlier_owners = segment(historical, positions)
    fragments.extend(earlier)
    owners.update(earlier_owners)
    disputed, disputed_owners = segment(uncertain, positions)
    for fragment in disputed:
        fragment["uncertain"] = True
        fragment["evidence_reasons"] = sorted({reasons[index] for index in fragment["capture_indices"]})
    fragments.extend(disputed)
    owners.update(disputed_owners)
    return fragments, owners
