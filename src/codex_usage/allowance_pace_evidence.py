"""Revision-scoped causal quota index; fitting never reconstructs its prefix.

Preparation builds shared series indexes and records continuity at each
origin. No future identity or reset metadata is incorporated into earlier
checkpoints. Leading unknown plans can be resolved when the first known plan
arrives; that origin's state is rebuilt once without changing earlier states.
"""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from itertools import groupby

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_windows import seconds


@dataclass(slots=True)
class Continuity:
    previous: QuotaObservation | None = None
    reset: int | None = None
    reset_seen: float | None = None
    credits: int | None = None

    def push(self, group):
        point, reset, credits = group.point, group.reset, group.credits
        crossed = self.reset is not None and self.reset_seen < self.reset <= group.time
        advanced = self.reset is not None and reset is not None and reset > self.reset + 60
        credit_drop = self.credits is not None and credits is not None and credits < self.credits
        rebase = self.reset is not None and reset is not None and abs(reset - self.reset) > 60
        reason = ("scheduled reset" if crossed and advanced else
                  "reset credit decrease" if credit_drop else
                  "deadline rebase" if rebase else
                  "unknown boundary" if self.previous and self.previous.used_percent - point.used_percent >= 5 else "")
        if reason:
            self.reset = self.reset_seen = self.credits = None
        if reset is not None:
            self.reset, self.reset_seen = reset, group.time
        if credits is not None:
            self.credits = credits
        self.previous = point
        return reason


@dataclass(frozen=True, slots=True)
class Group:
    time: float
    point: QuotaObservation
    members: frozenset
    plan: str
    reset: int | None
    credits: int | None
    conflict: bool

    @classmethod
    def from_points(cls, time, points):
        resets = [p.resets_at for p in points if p.resets_at is not None]
        plans = {p.plan for p in points if p.plan}
        credits = {p.reset_credits for p in points if p.reset_credits is not None}
        conflict = (len({p.used_percent for p in points}) > 1 or len(plans) > 1
                    or len(credits) > 1 or bool(resets and max(resets) - min(resets) > 60))
        point = next((p for p in reversed(points) if p.plan), points[-1])
        return cls(time, point, frozenset(points), next(iter(plans), ""),
                   resets[-1] if resets else None, next(iter(credits), None), conflict)


@dataclass(slots=True)
class Cursor:
    continuity: Continuity = field(default_factory=Continuity)
    known_plan: str = ""
    previous_time: float | None = None
    start: int = 0
    boundary: str = "left censored"
    conflicts: int = 0
    pending_cut: bool = False
    plan_cursor: int = 0
    previous_used: float | None = None
    maximum_gap: float = 0
    corrections: int = 0
    reported_full_at: float | None = None

    def push(self, index, group, plan_events):
        if any(p.used_percent >= 100 for p in group.members) and self.reported_full_at is None:
            self.reported_full_at = group.time
        if group.conflict:
            self.conflicts += 1
            self.pending_cut = True
            return
        reason = ("observation conflict" if self.pending_cut else
                  "plan change" if group.plan and self.known_plan and group.plan != self.known_plan else "")
        # Events from other duration buckets participate in limit-wide plan
        # continuity. The cursor stops at this origin, even in a future ledger.
        while self.plan_cursor < len(plan_events) and plan_events[self.plan_cursor][0] <= group.time:
            stamp, plan = plan_events[self.plan_cursor]
            if self.previous_time is not None and stamp > self.previous_time and plan != self.known_plan:
                reason = "plan change"
            self.plan_cursor += 1
        continuity_reason = ""
        if reason:
            # Retain supported reset evidence across a conflict when deciding
            # whether a raw full-meter cutoff belongs to the resumed cycle.
            continuity_reason = self.continuity.push(group)
            # Consume the boundary point's raw metadata for its new suffix.
            self.continuity = Continuity()
            self.continuity.push(group)
        else:
            reason = self.continuity.push(group)
        if reason:
            if reason != "observation conflict" or continuity_reason:
                self.reported_full_at = group.time if any(p.used_percent >= 100 for p in group.members) else None
            self.start, self.boundary = index, reason
            self.maximum_gap = 0
            self.corrections = 0
        elif self.previous_time is not None:
            self.maximum_gap = max(self.maximum_gap, group.time - self.previous_time)
            self.corrections += group.point.used_percent < self.previous_used
        if group.plan:
            self.known_plan = group.plan
        self.previous_time = group.time
        self.previous_used = group.point.used_percent
        self.pending_cut = False


@dataclass(frozen=True, slots=True)
class Series:
    times: tuple
    groups: tuple
    checkpoints: tuple
    cycle_stats: tuple

    @classmethod
    def prepare(cls, points, plan_events):
        ordered = sorted(dict.fromkeys(points), key=lambda p: (seconds(p), p.slot))
        groups = tuple(Group.from_points(time, list(group)) for time, group in groupby(ordered, seconds))
        first_known = next((i for i, g in enumerate(groups) if g.plan and not g.conflict), None)
        cursor = Cursor()
        checkpoints = []
        cycle_stats = []
        for index, group in enumerate(groups):
            if index == first_known:
                # The prefix's leading unknown run now has its first known
                # endpoint. Replaying it once preserves prefix-local identity
                # resolution, while older origins retain their unknown state.
                cursor = Cursor(known_plan=group.plan)
                for earlier in range(index):
                    cursor.push(earlier, groups[earlier], plan_events)
            cursor.push(index, group, plan_events)
            checkpoints.append((cursor.start, cursor.boundary, cursor.conflicts))
            cycle_stats.append((cursor.maximum_gap, cursor.corrections, cursor.reported_full_at, cursor.known_plan))
        return cls(tuple(g.time for g in groups), groups, tuple(checkpoints), tuple(cycle_stats))


@dataclass(frozen=True, slots=True)
class CycleEvidence:
    first: QuotaObservation | None
    observations: int
    maximum_gap: float
    corrections: int
    boundary: str
    conflicts: int
    reported_full_at: float | None = None
    plan: str = ""


@dataclass(frozen=True, slots=True)
class PreparedPaceEvidence:
    series: dict
    live_points: frozenset

    def _origin(self, anchor):
        series = self.series.get((anchor.limit_id, anchor.duration_minutes))
        if series is None:
            return None, 0, "exact live anchor missing", 0
        time = seconds(anchor)
        end = bisect_left(series.times, time)
        prior = bisect_right(series.times, time) - 1
        conflicts = series.checkpoints[prior][2] if prior >= 0 else 0
        if end < len(series.times) and series.times[end] == time and series.groups[end].conflict:
            return None, 0, "live anchor conflict", conflicts
        if (anchor not in self.live_points or end == len(series.times) or series.times[end] != time
                or anchor not in series.groups[end].members):
            return None, 0, "exact live anchor missing", conflicts
        return series, end, "", conflicts

    def select(self, anchor, *, horizon=86400):
        series, end, error, conflicts = self._origin(anchor)
        if error:
            return [], error, conflicts
        start, boundary, conflicts = series.checkpoints[end]
        start = max(start, bisect_left(series.times, seconds(anchor) - horizon))
        sample = [group.point for group in series.groups[start:end + 1]]
        sample[-1] = anchor
        return sample, boundary, conflicts

    def cycle(self, anchor):
        """Read observed-cycle endpoints and summaries without scanning its points."""
        series, end, error, conflicts = self._origin(anchor)
        if error:
            return CycleEvidence(None, 0, 0, 0, error, conflicts)
        start, boundary, conflicts = series.checkpoints[end]
        gap, corrections, full_at, plan = series.cycle_stats[end]
        first = anchor if start == end else series.groups[start].point
        return CycleEvidence(first, end - start + 1, gap, corrections, boundary, conflicts, full_at, plan)


def prepare_pace_evidence(points, live_points, *, series_keys=None):
    """Build shared series indexes once; preserve raw points and provenance."""
    grouped, events = {}, {}
    limits = {key[0] for key in series_keys} if series_keys is not None else None
    for point in points:
        key = (point.limit_id, point.duration_minutes)
        if series_keys is None or key in series_keys:
            grouped.setdefault(key, []).append(point)
        if point.plan and (limits is None or point.limit_id in limits):
            events.setdefault(point.limit_id, set()).add((seconds(point), point.plan))
    events = {key: sorted(value) for key, value in events.items()}
    return PreparedPaceEvidence({key: Series.prepare(value, events.get(key[0], ()))
                                 for key, value in grouped.items()}, frozenset(live_points))
