"""Percentage-bin regression and explicit confidence gates (ADR 0044)."""
from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import median


@dataclass(frozen=True, slots=True)
class AllowanceEstimate:
    confidence: str = "insufficient"
    value: float | None = None
    span: float = 0
    bins: int = 0
    r_squared: float = 0
    sensitivity_ratio: float | None = None
    cost_span: float = 0

    def to_dict(self):
        return asdict(self)


def allowance_fit_points(window):
    """A saturated quota meter cannot identify included-allowance consumption.

    Keep its raw tail for reset reconstruction, but stop calibration before
    the first reported-full point, including subsequent meter corrections.
    """
    cutoff = datetime.fromisoformat(window.reported_full_at).timestamp() if window.reported_full_at else None
    end = next((index for index, point in enumerate(window.points)
                if point.used_percent >= 100 or (cutoff is not None
                    and datetime.fromisoformat(point.timestamp).timestamp() >= cutoff)), len(window.points))
    return window.points[:end]


def percentile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (position - lower)


def estimate_window(window, cumulative_costs, *, fully_priced: bool, coverage_complete: bool = True):
    points = allowance_fit_points(window)
    costs = cumulative_costs[:len(points)]
    if len(cumulative_costs) != len(window.points):
        raise ValueError("allowance points and costs must have the same length")
    bins = {}
    for point, cost in zip(points, costs, strict=True):
        bins.setdefault(round(point.used_percent), []).append(cost)
    pairs = [(percent, median(costs)) for percent, costs in sorted(bins.items())]
    count = len(pairs)
    span = pairs[-1][0] - pairs[0][0] if count else 0
    if count < 5 or span < 10 or len({p.timestamp for p in points}) < 5:
        return AllowanceEstimate(span=span, bins=count)
    x_mean = sum(x for x, _ in pairs) / count
    y_mean = sum(y for _, y in pairs) / count
    xx = sum((x - x_mean) ** 2 for x, _ in pairs)
    slope = sum((x - x_mean) * (y - y_mean) for x, y in pairs) / xx
    yy = sum((y - y_mean) ** 2 for _, y in pairs)
    if slope <= 0 or yy <= 0:
        return AllowanceEstimate(span=span, bins=count)
    residual = sum((y - (y_mean + slope * (x - x_mean))) ** 2 for x, y in pairs)
    r_squared = max(0, 1 - residual / yy)
    slopes = [(yb - ya) / (xb - xa) for index, (xa, ya) in enumerate(pairs)
              for xb, yb in pairs[index + 1:]]
    p10, p90 = percentile(slopes, .1), percentile(slopes, .9)
    ratio = p90 / p10 if p10 > 0 else None
    confidence = "Low/provisional"
    identifiable = all(p.plan and p.duration_minutes for p in points)
    if fully_priced and coverage_complete and identifiable and window.completed and ratio is not None:
        if span >= 50 and count >= 10 and r_squared >= .98 and ratio <= 1.15 and not window.ambiguous:
            confidence = "High"
        elif span >= 20 and count >= 5 and r_squared >= .95 and ratio <= 1.35:
            confidence = "Medium"
    # Partial/unpriced evidence is disclosed but cannot manufacture dollars.
    value = slope * 100 if fully_priced else None
    return AllowanceEstimate(confidence, value, span, count, r_squared, ratio,
                             max(costs) - min(costs))
