"""Request-local ordered totals; freeze only at public aggregation boundaries."""
from codex_usage.models import TokenUsage
from codex_usage.pricing import CostBreakdown, CreditBreakdown


class SummaryAccumulator:
    """Preserve every component and the original sequential floating additions."""

    __slots__ = (
        "usage_input_tokens", "usage_cached_input_tokens", "usage_output_tokens", "usage_reasoning_output_tokens", "usage_total_tokens", "usage_cache_write_input_tokens",
        "cost_ordinary_input_usd", "cost_cached_input_usd", "cost_cache_write_input_usd", "cost_output_usd", "cost_total_usd", "cost_unpriced_tokens", "cost_unpriced_ordinary_input_tokens", "cost_unpriced_cached_input_tokens", "cost_unpriced_cache_write_input_tokens", "cost_unpriced_output_tokens",
        "credits_uncached_input_credits", "credits_cached_input_credits", "credits_output_credits", "credits_total_credits", "credits_unpriced_tokens", "credits_ordinary_input_credits", "credits_cache_write_input_credits", "credits_unpriced_ordinary_input_tokens", "credits_unpriced_cached_input_tokens", "credits_unpriced_cache_write_input_tokens", "credits_unpriced_output_tokens",
        "record_count",
    )

    def __init__(self, initial=None):
        self.usage_input_tokens = initial.usage.input_tokens if initial is not None else 0
        self.usage_cached_input_tokens = initial.usage.cached_input_tokens if initial is not None else 0
        self.usage_output_tokens = initial.usage.output_tokens if initial is not None else 0
        self.usage_reasoning_output_tokens = initial.usage.reasoning_output_tokens if initial is not None else 0
        self.usage_total_tokens = initial.usage.total_tokens if initial is not None else 0
        self.usage_cache_write_input_tokens = initial.usage.cache_write_input_tokens if initial is not None else 0
        self.cost_ordinary_input_usd = initial.cost.ordinary_input_usd if initial is not None else 0.0
        self.cost_cached_input_usd = initial.cost.cached_input_usd if initial is not None else 0.0
        self.cost_cache_write_input_usd = initial.cost.cache_write_input_usd if initial is not None else 0.0
        self.cost_output_usd = initial.cost.output_usd if initial is not None else 0.0
        self.cost_total_usd = initial.cost.total_usd if initial is not None else 0.0
        self.cost_unpriced_tokens = initial.cost.unpriced_tokens if initial is not None else 0
        self.cost_unpriced_ordinary_input_tokens = initial.cost.unpriced_ordinary_input_tokens if initial is not None else 0
        self.cost_unpriced_cached_input_tokens = initial.cost.unpriced_cached_input_tokens if initial is not None else 0
        self.cost_unpriced_cache_write_input_tokens = initial.cost.unpriced_cache_write_input_tokens if initial is not None else 0
        self.cost_unpriced_output_tokens = initial.cost.unpriced_output_tokens if initial is not None else 0
        self.credits_uncached_input_credits = initial.credits.uncached_input_credits if initial is not None else 0.0
        self.credits_cached_input_credits = initial.credits.cached_input_credits if initial is not None else 0.0
        self.credits_output_credits = initial.credits.output_credits if initial is not None else 0.0
        self.credits_total_credits = initial.credits.total_credits if initial is not None else 0.0
        self.credits_unpriced_tokens = initial.credits.unpriced_tokens if initial is not None else 0
        self.credits_ordinary_input_credits = initial.credits.ordinary_input_credits if initial is not None else 0.0
        self.credits_cache_write_input_credits = initial.credits.cache_write_input_credits if initial is not None else 0.0
        self.credits_unpriced_ordinary_input_tokens = initial.credits.unpriced_ordinary_input_tokens if initial is not None else 0
        self.credits_unpriced_cached_input_tokens = initial.credits.unpriced_cached_input_tokens if initial is not None else 0
        self.credits_unpriced_cache_write_input_tokens = initial.credits.unpriced_cache_write_input_tokens if initial is not None else 0
        self.credits_unpriced_output_tokens = initial.credits.unpriced_output_tokens if initial is not None else 0
        self.record_count = initial.record_count if initial is not None else 0

    def add(self, value):
        usage = value.usage
        self.usage_input_tokens += usage.input_tokens
        self.usage_cached_input_tokens += usage.cached_input_tokens
        self.usage_output_tokens += usage.output_tokens
        self.usage_reasoning_output_tokens += usage.reasoning_output_tokens
        self.usage_total_tokens += usage.total_tokens
        self.usage_cache_write_input_tokens += usage.cache_write_input_tokens
        cost = value.cost
        self.cost_ordinary_input_usd += cost.ordinary_input_usd
        self.cost_cached_input_usd += cost.cached_input_usd
        self.cost_cache_write_input_usd += cost.cache_write_input_usd
        self.cost_output_usd += cost.output_usd
        self.cost_total_usd += cost.total_usd
        self.cost_unpriced_tokens += cost.unpriced_tokens
        self.cost_unpriced_ordinary_input_tokens += cost.unpriced_ordinary_input_tokens
        self.cost_unpriced_cached_input_tokens += cost.unpriced_cached_input_tokens
        self.cost_unpriced_cache_write_input_tokens += cost.unpriced_cache_write_input_tokens
        self.cost_unpriced_output_tokens += cost.unpriced_output_tokens
        credits = value.credits
        self.credits_uncached_input_credits += credits.uncached_input_credits
        self.credits_cached_input_credits += credits.cached_input_credits
        self.credits_output_credits += credits.output_credits
        self.credits_total_credits += credits.total_credits
        self.credits_unpriced_tokens += credits.unpriced_tokens
        self.credits_ordinary_input_credits += credits.ordinary_input_credits
        self.credits_cache_write_input_credits += credits.cache_write_input_credits
        self.credits_unpriced_ordinary_input_tokens += credits.unpriced_ordinary_input_tokens
        self.credits_unpriced_cached_input_tokens += credits.unpriced_cached_input_tokens
        self.credits_unpriced_cache_write_input_tokens += credits.unpriced_cache_write_input_tokens
        self.credits_unpriced_output_tokens += credits.unpriced_output_tokens
        self.record_count += value.record_count

    def freeze(self):
        from codex_usage.aggregation import UsageSummary
        return UsageSummary(
            usage=TokenUsage(
                input_tokens=self.usage_input_tokens,
                cached_input_tokens=self.usage_cached_input_tokens,
                output_tokens=self.usage_output_tokens,
                reasoning_output_tokens=self.usage_reasoning_output_tokens,
                total_tokens=self.usage_total_tokens,
                cache_write_input_tokens=self.usage_cache_write_input_tokens,
            ),
            cost=CostBreakdown(
                ordinary_input_usd=self.cost_ordinary_input_usd,
                cached_input_usd=self.cost_cached_input_usd,
                cache_write_input_usd=self.cost_cache_write_input_usd,
                output_usd=self.cost_output_usd,
                total_usd=self.cost_total_usd,
                unpriced_tokens=self.cost_unpriced_tokens,
                unpriced_ordinary_input_tokens=self.cost_unpriced_ordinary_input_tokens,
                unpriced_cached_input_tokens=self.cost_unpriced_cached_input_tokens,
                unpriced_cache_write_input_tokens=self.cost_unpriced_cache_write_input_tokens,
                unpriced_output_tokens=self.cost_unpriced_output_tokens,
            ),
            credits=CreditBreakdown(
                uncached_input_credits=self.credits_uncached_input_credits,
                cached_input_credits=self.credits_cached_input_credits,
                output_credits=self.credits_output_credits,
                total_credits=self.credits_total_credits,
                unpriced_tokens=self.credits_unpriced_tokens,
                ordinary_input_credits=self.credits_ordinary_input_credits,
                cache_write_input_credits=self.credits_cache_write_input_credits,
                unpriced_ordinary_input_tokens=self.credits_unpriced_ordinary_input_tokens,
                unpriced_cached_input_tokens=self.credits_unpriced_cached_input_tokens,
                unpriced_cache_write_input_tokens=self.credits_unpriced_cache_write_input_tokens,
                unpriced_output_tokens=self.credits_unpriced_output_tokens,
            ),
            record_count=self.record_count,
        )
