"""Quota-relevant USD evidence, without changing report token/API accounting."""
from datetime import datetime

from codex_usage.pricing_breakdowns import CostBreakdown
from codex_usage.subscription_usage import is_included_subscription_usage


def allowance_cost_components(
    cost: CostBreakdown | None,
    *,
    model: str,
    at: datetime,
    total_tokens: int,
) -> tuple[float, int]:
    if is_included_subscription_usage(model, at):
        return 0.0, 0
    if cost is not None:
        return cost.total_usd, cost.unpriced_tokens
    return 0.0, total_tokens
