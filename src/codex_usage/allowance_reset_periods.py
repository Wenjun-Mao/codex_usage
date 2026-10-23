"""Reset lifecycles, separate from conservative capture/fit fragments."""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import replace
from itertools import groupby

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_pace_evidence import Group
from codex_usage.allowance_windows import seconds


def _edge(before, after, *, exact=None, kind="reset"):
    return dict(kind=kind, earliest=exact if exact is not None else before,
                latest=exact if exact is not None else after)


def _confirmed(groups, index, previous, anchor_points):
    group = groups[index]
    if group.members & anchor_points:
        return True
    following = next((g for g in groups[index+1:] if not g.conflict and g.reset is not None
                      and g.plan == group.plan), None)
    # A second reset need not repeat the intermediate deadline. Reject only an
    # explicit return to the previous clock and meter, not missing corroboration.
    return not (following and previous.reset is not None
                and abs(following.reset-previous.reset) <= 60
                and following.point.used_percent >= previous.point.used_percent-1)


def _refine(edge, group, candidates):
    if edge["earliest"] == edge["latest"] or group.reset is None or not group.plan:
        return edge
    times, readings = candidates
    first = bisect_right(times, edge["earliest"])
    last = bisect_right(times, edge["latest"])
    for at, simultaneous in groupby(readings[first:last], seconds):
        candidate = Group.from_points(at, list(simultaneous))
        if (not candidate.conflict and candidate.reset is not None
                and abs(candidate.reset-group.reset) <= 60 and candidate.plan == group.plan
                and candidate.point.used_percent <= group.point.used_percent+1):
            return dict(edge, latest=at)
    return edge


def reset_periods(captures, live_points, anchors, *, through=None, points=None):
    """Only authoritative readings establish a reset; matching tasks refine time.

    A changed deadline plus a restarted meter is an early reset even when the
    account's banked-reset count has not changed. Stale task readings cannot
    create periods, revert the clock, or choose the meter's final percentage.
    """
    fields = QuotaObservation.__dataclass_fields__
    if points is None:
        points = [QuotaObservation(**{key: p[key] for key in fields}) for p in captures]
    primary = {(a.limit_id, a.duration_minutes) for a in anchors if a.duration_minutes == 10080}
    primary = primary or {(a.limit_id, a.duration_minutes) for a in anchors if a.duration_minutes}
    if not primary:
        primary = {(p.limit_id, p.duration_minutes) for p in live_points if p.duration_minutes == 10080}
    primary = {min(primary, key=lambda key: (-key[1], key[0] != "codex", key[0]))} if primary else set()
    raw, official = defaultdict(list), defaultdict(list)
    for index, point in enumerate(points):
        key = point.limit_id, point.duration_minutes
        if key not in primary:
            continue
        raw[key].append((index, seconds(point), point))
        if point in live_points:
            official[key].append((index, point))
    result = []
    disputed = set()
    anchor_points = set(anchors)
    for key, indexed in official.items():
        readings = [p for _, p in indexed]
        groups = [Group.from_points(time, list(members)) for time, members in groupby(readings, seconds)]
        candidates = ([t for _, t, _ in raw[key]], [p for _, _, p in raw[key]])
        active = previous = None
        reset_seen = reset_meter = credits_seen = credits_meter = None
        for index, group in enumerate(groups):
            if group.conflict:
                disputed.update(group.members)
                continue
            explicit_reset, explicit_credits = group.reset, group.credits
            if active is not None and not active["plan"] and group.plan:
                active["plan"] = group.plan
            plan_change = bool(active and group.plan and active["plan"] and group.plan != active["plan"])
            if previous is not None and not plan_change:
                group = replace(group, reset=group.reset if group.reset is not None else previous.reset,
                                credits=group.credits if group.credits is not None else previous.credits)
            reason, edge = "", None
            if previous is not None:
                changed = group.reset is not None and previous.reset is not None and abs(group.reset-previous.reset) > 60
                baseline = max(previous.point.used_percent, reset_meter if reset_meter is not None else 0)
                restarted = baseline-group.point.used_percent > 1
                credit = previous.credits is not None and group.credits is not None and group.credits < previous.credits
                credit_restart = credits_meter is not None and credits_meter-group.point.used_percent > 1
                crossed = previous.reset is not None and reset_seen < previous.reset <= group.time
                advanced = changed and group.reset > previous.reset
                if plan_change:
                    reason = "plan change"
                elif ((changed and restarted) or (credit and credit_restart) or (crossed and advanced)) and _confirmed(groups, index, previous, anchor_points):
                    reason = "scheduled reset" if crossed and advanced and not credit else "early reset"
                if reason:
                    exact = (previous.reset if reason == "scheduled reset"
                             and group.reset-previous.reset <= key[1]*60+60 else None)
                    before = previous.time
                    if reason == "early reset" and previous.point.used_percent-group.point.used_percent <= 1:
                        before = reset_seen if changed and restarted else credits_seen
                    # Once a boundary is established, only its explicit metadata
                    # belongs to the new lifecycle; old clocks/credits cannot
                    # create a second retroactive reset when missing data arrives.
                    group = replace(group, reset=explicit_reset, credits=explicit_credits)
                    reset_seen = reset_meter = credits_seen = credits_meter = None
                    edge = _refine(_edge(before, group.time, exact=exact, kind=reason), group, candidates)
                    active["identity_closure" if plan_change else "reset_closure"] = edge
                    active["end"] = edge["latest"]
                    active["ended_by"] = reason
            if active is None or edge:
                active = dict(limit_id=key[0], duration_minutes=key[1], plan=group.plan,
                    boundary=reason or "first capture", reset_opening=edge if reason != "plan change" else None,
                    reset_closure=None, identity_opening=edge if reason == "plan change" else None,
                    identity_closure=None,
                    start=edge["latest"] if edge else group.time, end=group.time,
                    observed_start=group.time, observed_end=group.time,
                    current=False, next_reset=None, ended_by="", uncertain=False,
                    capture_indices=[], fit_indices=[], deadlines=[], meter_start=group.point.used_percent,
                    meter_end=group.point.used_percent, saturated_at=None)
                result.append(active)
            if group.reset is not None and group.reset not in active["deadlines"]:
                active["deadlines"].append(group.reset)
            active.update(observed_end=group.time, end=group.time, meter_end=group.point.used_percent)
            if group.point.used_percent >= 100 and active["saturated_at"] is None:
                active["saturated_at"] = group.time
            if group.members & anchor_points:
                active["current"] = True
                active["next_reset"] = group.reset if group.reset is not None and group.reset > group.time else None
            if explicit_reset is not None:
                reset_seen, reset_meter = group.time, group.point.used_percent
            if explicit_credits is not None:
                credits_seen, credits_meter = group.time, group.point.used_percent
            previous = group
    # Membership uses detected reset intervals, not obsolete announced deadlines.
    series = defaultdict(list)
    for period in result:
        if period["current"] and through is not None:
            period["end"] = max(period["end"], through)
        series[(period["limit_id"], period["duration_minutes"])].append(period)
    owners = {}
    for key, periods in series.items():
        starts = [p["start"] for p in periods]
        for index, at, point in raw[key]:
            if point in disputed:
                continue
            position = bisect_right(starts, at)-1
            if position < 0:
                continue
            period = periods[position]
            closing = period["reset_closure"]
            if (closing and closing["earliest"] < at < closing["latest"]
                    and point.resets_at is None):
                continue
            if (at > period["end"] and not (period["reset_closure"] or period["identity_closure"])
                    or point.plan and period["plan"] and point.plan != period["plan"]
                    or point not in live_points and (point.resets_at is None
                        or not any(abs(point.resets_at-r) <= 60 for r in period["deadlines"]))):
                continue
            period["capture_indices"].append(index)
            owners[index] = period
    # A later explicit deadline can reveal a scheduled reset inside a metadata
    # gap. Reconcile meter endpoints after assigning that retroactive boundary.
    for period in result:
        members = [points[i] for i in period["capture_indices"] if points[i] in live_points]
        if members:
            period.update(observed_start=seconds(members[0]), observed_end=seconds(members[-1]),
                          meter_start=members[0].used_percent, meter_end=members[-1].used_percent,
                          saturated_at=next((seconds(p) for p in members if p.used_percent >= 100), None))
    return result, owners
