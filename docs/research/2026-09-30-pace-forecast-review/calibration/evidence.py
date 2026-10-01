"""Forecast-specific, as-of continuity checks; not the product segmenter."""
from dataclasses import dataclass
from itertools import groupby


@dataclass
class Evidence:
    points: list[dict]
    boundary: str
    conflict: bool = False
    corrections: int = 0


@dataclass
class Continuity:
    previous: dict | None = None
    known_reset: int | None = None
    reset_seen_at: float | None = None
    known_credits: int | None = None

    def push(self, current, metadata=None):
        group = metadata or [current]
        new_reset = next((point["reset"] for point in reversed(group) if point["reset"] is not None), None)
        new_credits = next((point["credits"] for point in reversed(group) if point["credits"] is not None), None)
        old_reset = self.known_reset
        crossed = old_reset is not None and self.reset_seen_at < old_reset <= current["seconds"]
        advanced = old_reset is not None and new_reset is not None and new_reset > old_reset + 60
        credit_drop = self.known_credits is not None and new_credits is not None and new_credits < self.known_credits
        if crossed and advanced:
            reason = "scheduled-compatible"
        elif credit_drop:
            reason = "reset-credit-decrease"
        elif old_reset is not None and new_reset is not None and abs(new_reset - old_reset) > 60:
            reason = "deadline-rebase"
        else:
            reason = "early/unknown" if self.previous and self.previous["used"] - current["used"] >= 5 else ""
        if reason:
            self.known_reset = self.reset_seen_at = self.known_credits = None
        if new_reset is not None:
            self.known_reset, self.reset_seen_at = new_reset, current["seconds"]
        if new_credits is not None:
            self.known_credits = new_credits
        self.previous = current
        return reason


def reset_boundary(previous, current):
    continuity = Continuity()
    continuity.push(previous)
    return continuity.push(current)


def plans_at_prefix(points):
    plans = [point["plan"] for point in points]
    previous = ""
    index = 0
    while index < len(plans):
        if plans[index]:
            previous = plans[index]
            index += 1
            continue
        end = index
        while end < len(plans) and not plans[end]:
            end += 1
        following = plans[end] if end < len(plans) else ""
        identity = "" if previous and following and previous != following else previous or following
        plans[index:end] = [identity] * (end - index)
        index = end
    return plans


def current_suffix(points, anchor):
    # Filter before every identity/continuity operation, not after segmentation.
    prefix = sorted((point for point in points if point["seconds"] <= anchor["seconds"]),
                    key=lambda point: (point["seconds"], point["read_id"] or 0))
    canonical, metadata, cut_positions = [], [], set()
    anchor_conflict = False
    pending_cut = False
    for stamp, grouped in groupby(prefix, key=lambda point: point["seconds"]):
        group = list(grouped)
        reset_values = [point["reset"] for point in group if point["reset"] is not None]
        known_plans = {point["plan"] for point in group if point["plan"]}
        known_credits = {point["credits"] for point in group if point["credits"] is not None}
        conflict = (len({point["used"] for point in group}) > 1 or len(known_plans) > 1
                    or len(known_credits) > 1 or (reset_values and max(reset_values) - min(reset_values) > 60))
        if conflict:
            anchor_conflict |= stamp == anchor["seconds"]
            pending_cut = True
            continue
        chosen = next((point for point in group if point["read_id"] == anchor["read_id"]), None)
        chosen = chosen or next((point for point in reversed(group) if point["source"] == "live"), group[-1])
        if pending_cut:
            cut_positions.add(len(canonical))
            pending_cut = False
        canonical.append(chosen)
        metadata.append(group)
    if anchor_conflict or not canonical or canonical[-1]["read_id"] != anchor["read_id"]:
        return Evidence([], "anchor-conflict-or-missing", True)
    identities = plans_at_prefix(canonical)
    start, kind, corrections = 0, "left-censored", 0
    continuity = Continuity()
    continuity.push(canonical[0], metadata[0])
    for index, (previous, current) in enumerate(zip(canonical, canonical[1:]), start=1):
        reason = ("observation-conflict" if index in cut_positions else
                  "identity-change" if identities[index] != identities[index - 1] else "")
        if reason:
            continuity = Continuity()
            continuity.push(current, metadata[index])
        else:
            reason = continuity.push(current, metadata[index])
        if reason:
            start, kind, corrections = index, reason, 0
        elif current["used"] < previous["used"]:
            corrections += 1
    return Evidence(canonical[start:], kind, corrections=corrections)
