from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from codex_usage.models import TokenUsage


PRICING_AS_OF = "2026-07-09"
PRICING_METHOD = "effective_dated"
BASELINE_EFFECTIVE_FROM = datetime(1970, 1, 1, tzinfo=UTC)
GPT_5_6_API_EFFECTIVE_FROM = datetime(2026, 6, 26, tzinfo=UTC)
GPT_5_6_CREDIT_EFFECTIVE_FROM = datetime(2026, 7, 9, tzinfo=UTC)


@dataclass(frozen=True)
class ModelRate:
    input_per_1m: float
    cached_input_per_1m: float
    output_per_1m: float


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
            cached_input_per_1m=rate.cached_input_per_1m * self.cached_input_rate_multiplier,
            output_per_1m=rate.output_per_1m * self.output_rate_multiplier,
        )


@dataclass(frozen=True)
class RequestPricingContract:
    long_context_pricing: RequestLevelLongContextPricing | None = None

    def rate_for_usage(self, base_rate: ModelRate, usage: TokenUsage) -> ModelRate:
        if self.long_context_pricing is not None and self.long_context_pricing.applies_to(usage):
            return self.long_context_pricing.apply(base_rate)
        return base_rate


STANDARD_REQUEST_PRICING = RequestPricingContract()
GPT_5_6_API_LONG_CONTEXT_PRICING = RequestPricingContract(
    long_context_pricing=RequestLevelLongContextPricing(
        input_token_threshold=272_000,
        input_rate_multiplier=2.0,
        cached_input_rate_multiplier=2.0,
        output_rate_multiplier=1.5,
    )
)


@dataclass(frozen=True)
class EffectiveModelRate:
    model_key: str
    effective_from: datetime
    rate: ModelRate
    aliases: tuple[str, ...] = ()
    request_pricing_contract: RequestPricingContract = STANDARD_REQUEST_PRICING

    def rate_for_usage(self, usage: TokenUsage) -> ModelRate:
        return self.request_pricing_contract.rate_for_usage(self.rate, usage)


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


@dataclass(frozen=True)
class CreditBreakdown:
    uncached_input_credits: float = 0.0
    cached_input_credits: float = 0.0
    output_credits: float = 0.0
    total_credits: float = 0.0
    unpriced_tokens: int = 0

    def add(self, other: "CreditBreakdown") -> "CreditBreakdown":
        return CreditBreakdown(
            uncached_input_credits=self.uncached_input_credits + other.uncached_input_credits,
            cached_input_credits=self.cached_input_credits + other.cached_input_credits,
            output_credits=self.output_credits + other.output_credits,
            total_credits=self.total_credits + other.total_credits,
            unpriced_tokens=self.unpriced_tokens + other.unpriced_tokens,
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "uncached_input_credits": round(self.uncached_input_credits, 6),
            "cached_input_credits": round(self.cached_input_credits, 6),
            "output_credits": round(self.output_credits, 6),
            "total_credits": round(self.total_credits, 6),
            "unpriced_tokens": self.unpriced_tokens,
        }


def _effective_rate(
    model_key: str,
    *,
    input_per_1m: float,
    cached_input_per_1m: float,
    output_per_1m: float,
    effective_from: datetime = BASELINE_EFFECTIVE_FROM,
    aliases: tuple[str, ...] = (),
    request_pricing_contract: RequestPricingContract = STANDARD_REQUEST_PRICING,
) -> EffectiveModelRate:
    return EffectiveModelRate(
        model_key=model_key,
        effective_from=effective_from,
        rate=ModelRate(
            input_per_1m=input_per_1m,
            cached_input_per_1m=cached_input_per_1m,
            output_per_1m=output_per_1m,
        ),
        aliases=aliases,
        request_pricing_contract=request_pricing_contract,
    )


API_PRICING_USD_SCHEDULE: tuple[EffectiveModelRate, ...] = (
    _effective_rate(
        "gpt-5.6-sol",
        input_per_1m=5.00,
        cached_input_per_1m=0.50,
        output_per_1m=30.00,
        effective_from=GPT_5_6_API_EFFECTIVE_FROM,
        aliases=("gpt-5.6",),
        request_pricing_contract=GPT_5_6_API_LONG_CONTEXT_PRICING,
    ),
    _effective_rate(
        "gpt-5.6-terra",
        input_per_1m=2.50,
        cached_input_per_1m=0.25,
        output_per_1m=15.00,
        effective_from=GPT_5_6_API_EFFECTIVE_FROM,
        request_pricing_contract=GPT_5_6_API_LONG_CONTEXT_PRICING,
    ),
    _effective_rate(
        "gpt-5.6-luna",
        input_per_1m=1.00,
        cached_input_per_1m=0.10,
        output_per_1m=6.00,
        effective_from=GPT_5_6_API_EFFECTIVE_FROM,
        request_pricing_contract=GPT_5_6_API_LONG_CONTEXT_PRICING,
    ),
    _effective_rate("gpt-5.5", input_per_1m=5.00, cached_input_per_1m=0.50, output_per_1m=30.00),
    _effective_rate("gpt-5.4-mini", input_per_1m=0.75, cached_input_per_1m=0.075, output_per_1m=4.50),
    _effective_rate("gpt-5.4", input_per_1m=2.50, cached_input_per_1m=0.25, output_per_1m=15.00),
    _effective_rate("gpt-5.3-codex", input_per_1m=1.75, cached_input_per_1m=0.175, output_per_1m=14.00),
    _effective_rate("gpt-5.3", input_per_1m=1.75, cached_input_per_1m=0.175, output_per_1m=14.00),
)

CODEX_CREDIT_RATE_SCHEDULE: tuple[EffectiveModelRate, ...] = (
    _effective_rate(
        "gpt-5.6-sol",
        input_per_1m=125.0,
        cached_input_per_1m=12.5,
        output_per_1m=750.0,
        effective_from=GPT_5_6_CREDIT_EFFECTIVE_FROM,
        aliases=("gpt-5.6",),
    ),
    _effective_rate(
        "gpt-5.6-terra",
        input_per_1m=62.5,
        cached_input_per_1m=6.25,
        output_per_1m=375.0,
        effective_from=GPT_5_6_CREDIT_EFFECTIVE_FROM,
    ),
    _effective_rate(
        "gpt-5.6-luna",
        input_per_1m=25.0,
        cached_input_per_1m=2.5,
        output_per_1m=150.0,
        effective_from=GPT_5_6_CREDIT_EFFECTIVE_FROM,
    ),
    _effective_rate("gpt-5.5", input_per_1m=125.0, cached_input_per_1m=12.5, output_per_1m=750.0),
    _effective_rate("gpt-5.4-mini", input_per_1m=18.75, cached_input_per_1m=1.875, output_per_1m=113.0),
    _effective_rate("gpt-5.4", input_per_1m=62.5, cached_input_per_1m=6.25, output_per_1m=375.0),
    _effective_rate("gpt-5.3-codex", input_per_1m=43.75, cached_input_per_1m=4.375, output_per_1m=350.0),
    _effective_rate("gpt-5.2", input_per_1m=43.75, cached_input_per_1m=4.375, output_per_1m=350.0),
)


def rate_for_model(model: str, at: datetime | None = None) -> ModelRate | None:
    return _rate_for_model(API_PRICING_USD_SCHEDULE, model, at)


def credit_rate_for_model(model: str, at: datetime | None = None) -> ModelRate | None:
    return _rate_for_model(CODEX_CREDIT_RATE_SCHEDULE, model, at)


def _rate_for_model(
    schedule: tuple[EffectiveModelRate, ...],
    model: str,
    at: datetime | None = None,
) -> ModelRate | None:
    entry = _schedule_entry_for_model(schedule, model, at)
    if entry is None:
        return None
    return entry.rate


def _schedule_entry_for_model(
    schedule: tuple[EffectiveModelRate, ...],
    model: str,
    at: datetime | None = None,
) -> EffectiveModelRate | None:
    normalized = _normalize_model_id(model)
    effective_at = _normalize_effective_at(at)
    candidates = [
        entry
        for entry in schedule
        if _matches_model(entry, normalized)
        and (effective_at is None or _normalize_effective_at(entry.effective_from) <= effective_at)
    ]
    if candidates:
        return max(
            candidates,
            key=lambda entry: _normalize_effective_at(entry.effective_from) or BASELINE_EFFECTIVE_FROM,
        )
    return None


def estimate_cost(usage: TokenUsage, model: str, at: datetime | None = None) -> CostBreakdown | None:
    entry = _schedule_entry_for_model(API_PRICING_USD_SCHEDULE, model, at)
    if entry is None:
        return None
    rate = entry.rate_for_usage(usage)

    uncached_input_usd = usage.uncached_input_tokens / 1_000_000 * rate.input_per_1m
    cached_input_usd = usage.cached_input_tokens / 1_000_000 * rate.cached_input_per_1m
    output_usd = usage.output_tokens / 1_000_000 * rate.output_per_1m
    return CostBreakdown(
        uncached_input_usd=uncached_input_usd,
        cached_input_usd=cached_input_usd,
        output_usd=output_usd,
        total_usd=uncached_input_usd + cached_input_usd + output_usd,
    )


def estimate_codex_credits(usage: TokenUsage, model: str, at: datetime | None = None) -> CreditBreakdown | None:
    rate = credit_rate_for_model(model, at=at)
    if rate is None:
        return None

    uncached_input_credits = usage.uncached_input_tokens / 1_000_000 * rate.input_per_1m
    cached_input_credits = usage.cached_input_tokens / 1_000_000 * rate.cached_input_per_1m
    output_credits = usage.output_tokens / 1_000_000 * rate.output_per_1m
    return CreditBreakdown(
        uncached_input_credits=uncached_input_credits,
        cached_input_credits=cached_input_credits,
        output_credits=output_credits,
        total_credits=uncached_input_credits + cached_input_credits + output_credits,
    )


def _normalize_effective_at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_model_id(value: str) -> str:
    return value.strip().casefold()


def _matches_model(entry: EffectiveModelRate, normalized_model: str) -> bool:
    aliases = {_normalize_model_id(alias) for alias in entry.aliases}
    return normalized_model == _normalize_model_id(entry.model_key) or normalized_model in aliases
