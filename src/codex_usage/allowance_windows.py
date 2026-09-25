"""Conservative quota reset segmentation, independent of nominal duration."""
from dataclasses import dataclass, field
from datetime import datetime

from codex_usage.allowance_models import QuotaObservation


@dataclass(slots=True)
class AllowanceWindow:
    points: list[QuotaObservation] = field(default_factory=list)
    closure: str = "ongoing"
    corrections: int = 0
    ambiguous: bool = False

    @property
    def completed(self):
        return self.closure not in {"ongoing", "identity-change"}


def seconds(point):
    return datetime.fromisoformat(point.timestamp).timestamp()


def boundary(previous, current):
    drop = previous.used_percent - current.used_percent
    if 0 < drop <= 1:
        return "correction"
    crossed = (previous.resets_at is not None and seconds(previous) < previous.resets_at <= seconds(current))
    advanced = (previous.resets_at is not None and current.resets_at is not None
                and current.resets_at > previous.resets_at + 60)
    credit = (previous.reset_credits is not None and current.reset_credits is not None
              and current.reset_credits < previous.reset_credits)
    if drop <= 0:
        return "scheduled-compatible" if crossed and advanced else ""
    if drop < 5 and not (crossed and advanced or credit):
        return "correction"
    if crossed and advanced:
        return "scheduled-compatible"
    if credit:
        return "banked-reset-compatible"
    return "early/unknown"


def segment_windows(points):
    grouped = {}
    # Keep ledger insertion order for conflicting samples at the same timestamp
    # and slot. A set's iteration order changes across processes and can move
    # a reset boundary between views.
    for point in sorted(dict.fromkeys(points), key=lambda p: (p.timestamp, p.slot)):
        # Slot is transport layout, not identity. Duration and plan changes
        # break the fit, even when the producer reuses a limit ID.
        grouped.setdefault(point.limit_id, []).append(point)
    results = []
    candidates = []
    for series in grouped.values():
        active = {}
        prior_plan = None
        for point in series:
            if prior_plan is not None and point.plan != prior_plan:
                for old_window in active.values():
                    old_window.closure = "identity-change"
                active = {}
            prior_plan = point.plan
            key = (point.plan, point.duration_minutes)
            window = active.get(key)
            if window is None:
                window = AllowanceWindow()
                active[key] = window
                results.append(window)
            if window.points:
                previous = window.points[-1]
                if previous.timestamp == point.timestamp:
                    if previous.used_percent != point.used_percent:
                        window.ambiguous = True
                    continue
                kind = boundary(previous, point)
                if kind == "correction":
                    window.corrections += 1
                elif kind:
                    window.closure = kind
                    window.ambiguous |= kind == "early/unknown"
                    candidates.append((point.timestamp, (point.limit_id, point.duration_minutes), window))
                    window = AllowanceWindow(ambiguous=kind == "early/unknown")
                    active[key] = window
                    results.append(window)
            window.points.append(point)
    # Simultaneous material drops across independent buckets support a global
    # reset classification; they do not prove the server's reason.
    for stamp, limit_id, window in candidates:
        if window.closure == "early/unknown" and any(
            other_id != limit_id and abs((datetime.fromisoformat(stamp) - datetime.fromisoformat(other_stamp)).total_seconds()) <= 60
            for other_stamp, other_id, _ in candidates
        ):
            window.closure = "global-reset-compatible"
    return results
