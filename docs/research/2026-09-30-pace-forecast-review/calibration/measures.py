"""Small competing descriptive rates, with identical raw-evidence gates."""
import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class Gates:
    lookback_hours: float
    minimum_times: int
    minimum_span_hours: float
    maximum_gap_hours: float
    movement: float = 2
    bucket_minutes: int = 5
    half_life: float | None = None


RECENT = Gates(1, 3, .5, .5)
DAILY = Gates(24, 5, 3, 3, bucket_minutes=15, half_life=6)


def eligible(points, anchor, gates):
    lower = anchor["seconds"] - gates.lookback_hours * 3600
    selected = [point for point in points if lower <= point["seconds"] <= anchor["seconds"]]
    if len(selected) < gates.minimum_times:
        return selected, "too-few-observations"
    span = (selected[-1]["seconds"] - selected[0]["seconds"]) / 3600
    if span < gates.minimum_span_hours:
        return selected, "short-span"
    gaps = [(b["seconds"] - a["seconds"]) / 3600 for a, b in zip(selected, selected[1:])]
    if max(gaps) > gates.maximum_gap_hours:
        return selected, "large-gap"
    if selected[-1]["used"] - selected[0]["used"] < gates.movement:
        return selected, "low-net-movement"
    return selected, "available"


def paired(points):
    end = points[-1]["seconds"]
    return [((point["seconds"] - end) / 3600, point["used"]) for point in points]


def bucketed(points, minutes, *, use_median):
    buckets = defaultdict(list)
    for point in points:
        buckets[math.floor(point["seconds"] / (minutes * 60))].append(point)
    groups = [group for _, group in sorted(buckets.items())]
    if use_median:
        end = points[-1]["seconds"]
        return [((median(point["seconds"] for point in group) - end) / 3600,
                 median(point["used"] for point in group)) for group in groups]
    selected = [group[-1] for group in groups]
    selected[0], selected[-1] = points[0], points[-1]
    return paired(selected)


def level_rate(samples, half_life):
    weights = [1 if half_life is None else 2 ** (hours / half_life) for hours, _ in samples]
    total = sum(weights)
    center_time = sum(weight * hours for weight, (hours, _) in zip(weights, samples)) / total
    center_used = sum(weight * used for weight, (_, used) in zip(weights, samples)) / total
    numerator = sum(weight * (hours - center_time) * (used - center_used)
                    for weight, (hours, used) in zip(weights, samples))
    denominator = sum(weight * (hours - center_time) ** 2 for weight, (hours, _) in zip(weights, samples))
    return numerator / denominator if denominator else None


def net_rate(samples):
    return (samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0])


def interval_rate(samples, half_life):
    decay = math.log(2) / half_life
    numerator = denominator = 0
    for (start, old_used), (end, used) in zip(samples, samples[1:]):
        duration = end - start
        weight = math.exp(decay * end) * -math.expm1(-decay * duration) / decay
        numerator += weight * (used - old_used) / duration
        denominator += weight
    return numerator / denominator


def rates(points, gates):
    samples = paired(points)
    result = {
        "net": net_rate(samples),
        "level-median": level_rate(bucketed(points, gates.bucket_minutes, use_median=True), gates.half_life),
        "level-paired": level_rate(bucketed(points, gates.bucket_minutes, use_median=False), gates.half_life),
    }
    if gates.half_life:
        result["interval-weighted"] = interval_rate(samples, gates.half_life)
    return result


def forecast(anchor, rate):
    if rate is None or not math.isfinite(rate) or rate <= 0:
        return None
    if anchor["reset"] is None or anchor["reset"] <= anchor["seconds"]:
        return None
    remaining = 100 - anchor["used"]
    exhaustion = anchor["seconds"] + remaining / rate * 3600
    reset_balance = remaining - rate * (anchor["reset"] - anchor["seconds"]) / 3600
    outcome = "near-reset" if abs(exhaustion - anchor["reset"]) <= 900 else (
        "runs-out" if reset_balance <= 0 else "remains")
    return {"rate": rate, "exhaustion": exhaustion, "reset_balance": reset_balance, "outcome": outcome}
