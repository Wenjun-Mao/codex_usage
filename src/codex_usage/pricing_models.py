"""Request-level rate contracts shared by effective-dated pricing schedules."""
from dataclasses import dataclass

from codex_usage.models import TokenUsage


@dataclass(frozen=True)
class ModelRate:
    input_per_1m: float
    cached_input_per_1m: float
    output_per_1m: float
    cache_write_input_per_1m: float | None = None

    @property
    def resolved_cache_write_input_per_1m(self) -> float:
        return (
            self.input_per_1m
            if self.cache_write_input_per_1m is None
            else self.cache_write_input_per_1m
        )


@dataclass(frozen=True)
class RequestLevelLongContextPricing:
    input_token_threshold: int
    input_rate_multiplier: float
    cached_input_rate_multiplier: float
    output_rate_multiplier: float

    def applies_to(self, usage: TokenUsage) -> bool:
        return usage.input_tokens > self.input_token_threshold

    def apply(self, rate: ModelRate) -> ModelRate:
        return ModelRate(
            input_per_1m=rate.input_per_1m * self.input_rate_multiplier,
            cached_input_per_1m=rate.cached_input_per_1m
            * self.cached_input_rate_multiplier,
            output_per_1m=rate.output_per_1m * self.output_rate_multiplier,
            cache_write_input_per_1m=(
                None
                if rate.cache_write_input_per_1m is None
                else rate.cache_write_input_per_1m * self.input_rate_multiplier
            ),
        )


@dataclass(frozen=True)
class RequestPricingContract:
    long_context_pricing: RequestLevelLongContextPricing | None = None

    def rate_for_usage(self, base_rate: ModelRate, usage: TokenUsage) -> ModelRate:
        if (
            self.long_context_pricing is not None
            and self.long_context_pricing.applies_to(usage)
        ):
            return self.long_context_pricing.apply(base_rate)
        return base_rate


STANDARD_REQUEST_PRICING = RequestPricingContract()
LARGE_CONTEXT_API_PRICING = RequestPricingContract(
    long_context_pricing=RequestLevelLongContextPricing(
        input_token_threshold=272_000,
        input_rate_multiplier=2.0,
        cached_input_rate_multiplier=2.0,
        output_rate_multiplier=1.5,
    )
)
