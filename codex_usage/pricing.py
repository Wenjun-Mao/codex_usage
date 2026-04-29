from __future__ import annotations

from dataclasses import dataclass

from codex_usage.models import TokenUsage


PRICING_AS_OF = "2026-04-29"


@dataclass(frozen=True)
class ModelRate:
    input_per_1m: float
    cached_input_per_1m: float
    output_per_1m: float


@dataclass(frozen=True)
class CostBreakdown:
    uncached_input_usd: float = 0.0
    cached_input_usd: float = 0.0
    output_usd: float = 0.0
    total_usd: float = 0.0
    unpriced_tokens: int = 0

    def add(self, other: "CostBreakdown") -> "CostBreakdown":
        return CostBreakdown(
            uncached_input_usd=self.uncached_input_usd + other.uncached_input_usd,
            cached_input_usd=self.cached_input_usd + other.cached_input_usd,
            output_usd=self.output_usd + other.output_usd,
            total_usd=self.total_usd + other.total_usd,
            unpriced_tokens=self.unpriced_tokens + other.unpriced_tokens,
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "uncached_input_usd": round(self.uncached_input_usd, 6),
            "cached_input_usd": round(self.cached_input_usd, 6),
            "output_usd": round(self.output_usd, 6),
            "total_usd": round(self.total_usd, 6),
            "unpriced_tokens": self.unpriced_tokens,
        }


API_PRICING_USD_PER_1M: dict[str, ModelRate] = {
    "gpt-5.5": ModelRate(input_per_1m=5.00, cached_input_per_1m=0.50, output_per_1m=30.00),
    "gpt-5.4-mini": ModelRate(input_per_1m=0.75, cached_input_per_1m=0.075, output_per_1m=4.50),
    "gpt-5.4": ModelRate(input_per_1m=2.50, cached_input_per_1m=0.25, output_per_1m=15.00),
}

CODEX_CREDIT_RATES_PER_1M: dict[str, ModelRate] = {
    "gpt-5.5": ModelRate(input_per_1m=125.0, cached_input_per_1m=12.5, output_per_1m=750.0),
    "gpt-5.4-mini": ModelRate(input_per_1m=18.75, cached_input_per_1m=1.875, output_per_1m=113.0),
    "gpt-5.4": ModelRate(input_per_1m=62.5, cached_input_per_1m=6.25, output_per_1m=375.0),
    "gpt-5.3-codex": ModelRate(input_per_1m=43.75, cached_input_per_1m=4.375, output_per_1m=350.0),
    "gpt-5.2": ModelRate(input_per_1m=43.75, cached_input_per_1m=4.375, output_per_1m=350.0),
}


def rate_for_model(model: str) -> ModelRate | None:
    normalized = model.casefold()
    for known_model in sorted(API_PRICING_USD_PER_1M, key=len, reverse=True):
        if known_model in normalized:
            return API_PRICING_USD_PER_1M[known_model]
    return None


def estimate_cost(usage: TokenUsage, model: str) -> CostBreakdown | None:
    rate = rate_for_model(model)
    if rate is None:
        return None

    uncached_input_usd = usage.uncached_input_tokens / 1_000_000 * rate.input_per_1m
    cached_input_usd = usage.cached_input_tokens / 1_000_000 * rate.cached_input_per_1m
    output_usd = usage.output_tokens / 1_000_000 * rate.output_per_1m
    return CostBreakdown(
        uncached_input_usd=uncached_input_usd,
        cached_input_usd=cached_input_usd,
        output_usd=output_usd,
        total_usd=uncached_input_usd + cached_input_usd + output_usd,
    )
