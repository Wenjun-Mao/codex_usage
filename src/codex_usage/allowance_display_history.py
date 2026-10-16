"""Raw-evidence display periods, deliberately independent of monetary fits."""
from itertools import groupby

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_pace_evidence import Continuity, Group
from codex_usage.allowance_windows import seconds


SUPPORTED = {"scheduled reset", "reset credit decrease"}


def _reset_boundary(reason, time, previous_reset, credits_seen, credit_drop):
    if reason in SUPPORTED and credit_drop and credits_seen is not None:
        # Missing credit metadata cannot narrow the actual reset interval.
        return dict(kind=reason, earliest=credits_seen, latest=time)
    if reason == "scheduled reset":
        return dict(kind=reason, earliest=previous_reset, latest=previous_reset)
    return None


def _identities(timeline):
    plans = [{p.plan for p in points if p.plan} for _, points in timeline]
    labels = [next(iter(values)) if len(values) == 1 else "" for values in plans]
    ambiguous = [len(values) > 1 for values in plans]
    previous = ""
    index = 0
    while index < len(labels):
        if labels[index]:
            previous = labels[index]
            index += 1
            continue
        end = index
        while end < len(labels) and not labels[end]:
            end += 1
        following = labels[end] if end < len(labels) else ""
        bridge = bool(previous and following and previous != following)
        # Conflicting plans cannot provide identity for adjacent missing metadata.
        conflict = any(ambiguous[index:end])
        for offset in range(index, end):
            labels[offset] = "" if bridge or conflict else previous or following
            ambiguous[offset] |= bridge or conflict
        previous = following
        index = end
    return list(zip(labels, ambiguous, strict=True))


def _segment(points, positions):
    """Segment one evidence-authority lane without dropping raw conflicts."""
    limits = {}
    for point in points:
        limits.setdefault(point.limit_id, []).append(point)
    fragments = []
    owners = {}
    for limit, readings in limits.items():
        timeline = [(time, list(group)) for time, group in groupby(readings, seconds)]
        active = {}
        previous_identity = None
        known_plan = ""
        tainted = set()
        for (time, simultaneous), identity in zip(timeline, _identities(timeline), strict=True):
            plan_change = bool(known_plan and identity[0] and known_plan != identity[0])
            if previous_identity is not None and identity != previous_identity:
                for fragment, _ in active.values():
                    fragment["ended_by"] = "plan change" if plan_change else "ambiguous plan metadata"
                    if fragment["uncertain"] or identity[1]:
                        tainted.add(fragment["duration_minutes"])
                active = {}
            if plan_change:
                tainted.clear()
            if identity[0]:
                known_plan = identity[0]
            identity_boundary = previous_identity is not None and identity != previous_identity
            previous_identity = identity
            durations = {}
            for point in simultaneous:
                durations.setdefault(point.duration_minutes, []).append(point)
            for duration, members in durations.items():
                group = Group.from_points(time, members)
                existing = active.get(duration)
                continuity = existing[1] if existing else Continuity()
                previous_reset, credits_seen = continuity.reset, continuity.credits_seen
                credit_drop = continuity.credits is not None and group.credits is not None and group.credits < continuity.credits
                reason = continuity.push(group) if not group.conflict else "observation conflict"
                boundary = _reset_boundary(reason, time, previous_reset, credits_seen, credit_drop)
                # A distant advanced deadline may skip entire unobserved cycles.
                skipped = (reason == "scheduled reset" and
                           (duration is None or group.reset - previous_reset > duration * 60 + 60))
                if group.conflict:
                    continuity = Continuity()
                if reason in SUPPORTED:
                    tainted.discard(duration)
                uncertain = (duration in tainted or identity[1] or group.conflict
                             or bool(reason and reason not in SUPPORTED))
                if existing is None or reason:
                    if existing:
                        existing[0]["ended_by"] = reason
                        existing[0]["reset_closure"] = boundary
                    fragment = {
                        "limit_id": limit, "duration_minutes": duration, "plan": identity[0],
                        "boundary": reason or ("plan change" if plan_change else
                                               "ambiguous plan metadata" if identity_boundary else "left censored"),
                        "uncertain": uncertain or bool(existing and existing[0]["uncertain"] and reason not in SUPPORTED),
                        "capture_indices": [], "fit_indices": [], "ended_by": "",
                        "current": False, "next_reset": None,
                        "reset_opening": None if skipped else boundary, "reset_closure": None,
                    }
                    fragments.append(fragment)
                    active[duration] = (fragment, continuity)
                else:
                    fragment = existing[0]
                for point in members:
                    fragment["capture_indices"].append(positions[point])
                    owners[point] = fragment
                fragment["next_reset"] = (continuity.reset if continuity.reset is not None
                                          and continuity.reset > time else None)
    return fragments, owners


def display_history(points, provenance, windows, anchors, *, live_points=None):
    """Display authority never changes monetary segmentation or fit facts."""
    from codex_usage.allowance_display_authority import source_aware_fragments
    ordered = sorted(dict.fromkeys(points), key=lambda p: (seconds(p), p.limit_id, p.slot))
    positions = {point: index for index, point in enumerate(ordered)}
    captures = [dict(p.to_dict(), provenance=", ".join(sorted(provenance[p]))) for p in ordered]
    fragments, owners = source_aware_fragments(ordered, positions, provenance, live_points, _segment)
    # Captured current membership is independent of opening/reset certainty.
    current_resets = {}
    for anchor in anchors:
        owner = owners.get(anchor)
        if owner is not None:
            owner["current"] = True
            current_resets.setdefault(id(owner), set()).add(
                anchor.resets_at if anchor.resets_at is not None and anchor.resets_at > seconds(anchor) else None)
    by_identity = {id(fragment): fragment for fragment in fragments}
    for identity, resets in current_resets.items():
        by_identity[identity]["next_reset"] = next(iter(resets)) if len(resets) == 1 else None
    cross_boundary = []
    for index, window in enumerate(windows):
        fit_owners = {id(owners[QuotaObservation(**{key: point[key] for key in QuotaObservation.__dataclass_fields__})])
                      for point in window["points"]}
        if len(fit_owners) == 1:
            by_identity[next(iter(fit_owners))]["fit_indices"].append(index)
        else:
            cross_boundary.append(index)
    for fragment in fragments:
        fragment["capture_indices"].sort()
    fragments.sort(key=lambda f: f["capture_indices"][-1], reverse=True)
    return {"captures": captures, "periods": [f for f in fragments if f["current"] or not f["uncertain"]],
            "uncertain": [f for f in fragments if f["uncertain"] and not f["current"]],
            "cross_boundary_fit_indices": cross_boundary}
