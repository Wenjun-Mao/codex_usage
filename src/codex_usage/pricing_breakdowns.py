from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostBreakdown:
    ordinary_input_usd: float = 0.0
    cached_input_usd: float = 0.0
    cache_write_input_usd: float = 0.0
    output_usd: float = 0.0
    total_usd: float = 0.0
    unpriced_tokens: int = 0
    unpriced_ordinary_input_tokens: int = 0
    unpriced_cached_input_tokens: int = 0
    unpriced_cache_write_input_tokens: int = 0
    unpriced_output_tokens: int = 0

    @property
    def input_usd(self) -> float:
        return (
            self.ordinary_input_usd + self.cached_input_usd + self.cache_write_input_usd
        )

    @property
    def unpriced_input_tokens(self) -> int:
        return (
            self.unpriced_ordinary_input_tokens
            + self.unpriced_cached_input_tokens
            + self.unpriced_cache_write_input_tokens
        )

    @property
    def uncached_input_usd(self) -> float:
        return self.ordinary_input_usd + self.cache_write_input_usd

    def add(self, other: "CostBreakdown") -> "CostBreakdown":
        return CostBreakdown(
            ordinary_input_usd=self.ordinary_input_usd + other.ordinary_input_usd,
            cached_input_usd=self.cached_input_usd + other.cached_input_usd,
            cache_write_input_usd=self.cache_write_input_usd
            + other.cache_write_input_usd,
            output_usd=self.output_usd + other.output_usd,
            total_usd=self.total_usd + other.total_usd,
            unpriced_tokens=self.unpriced_tokens + other.unpriced_tokens,
            unpriced_ordinary_input_tokens=self.unpriced_ordinary_input_tokens
            + other.unpriced_ordinary_input_tokens,
            unpriced_cached_input_tokens=self.unpriced_cached_input_tokens
            + other.unpriced_cached_input_tokens,
            unpriced_cache_write_input_tokens=self.unpriced_cache_write_input_tokens
            + other.unpriced_cache_write_input_tokens,
            unpriced_output_tokens=self.unpriced_output_tokens
            + other.unpriced_output_tokens,
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "uncached_input_usd": round(self.uncached_input_usd, 6),
            "ordinary_input_usd": round(self.ordinary_input_usd, 6),
            "cached_input_usd": round(self.cached_input_usd, 6),
            "cache_write_input_usd": round(self.cache_write_input_usd, 6),
            "output_usd": round(self.output_usd, 6),
            "total_usd": round(self.total_usd, 6),
            "unpriced_tokens": self.unpriced_tokens,
            "unpriced_ordinary_input_tokens": self.unpriced_ordinary_input_tokens,
            "unpriced_cached_input_tokens": self.unpriced_cached_input_tokens,
            "unpriced_cache_write_input_tokens": self.unpriced_cache_write_input_tokens,
            "unpriced_output_tokens": self.unpriced_output_tokens,
        }


@dataclass(frozen=True)
class CreditBreakdown:
    uncached_input_credits: float = 0.0
    cached_input_credits: float = 0.0
    output_credits: float = 0.0
    total_credits: float = 0.0
    unpriced_tokens: int = 0
    ordinary_input_credits: float = 0.0
    cache_write_input_credits: float = 0.0
    unpriced_ordinary_input_tokens: int = 0
    unpriced_cached_input_tokens: int = 0
    unpriced_cache_write_input_tokens: int = 0
    unpriced_output_tokens: int = 0

    @property
    def input_credits(self) -> float:
        return self.uncached_input_credits + self.cached_input_credits

    @property
    def unpriced_input_tokens(self) -> int:
        return (
            self.unpriced_ordinary_input_tokens
            + self.unpriced_cached_input_tokens
            + self.unpriced_cache_write_input_tokens
        )

    def add(self, other: "CreditBreakdown") -> "CreditBreakdown":
        return CreditBreakdown(
            uncached_input_credits=self.uncached_input_credits
            + other.uncached_input_credits,
            ordinary_input_credits=self.ordinary_input_credits
            + other.ordinary_input_credits,
            cache_write_input_credits=self.cache_write_input_credits
            + other.cache_write_input_credits,
            cached_input_credits=self.cached_input_credits + other.cached_input_credits,
            output_credits=self.output_credits + other.output_credits,
            total_credits=self.total_credits + other.total_credits,
            unpriced_tokens=self.unpriced_tokens + other.unpriced_tokens,
            unpriced_ordinary_input_tokens=self.unpriced_ordinary_input_tokens
            + other.unpriced_ordinary_input_tokens,
            unpriced_cached_input_tokens=self.unpriced_cached_input_tokens
            + other.unpriced_cached_input_tokens,
            unpriced_cache_write_input_tokens=self.unpriced_cache_write_input_tokens
            + other.unpriced_cache_write_input_tokens,
            unpriced_output_tokens=self.unpriced_output_tokens
            + other.unpriced_output_tokens,
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "uncached_input_credits": round(self.uncached_input_credits, 6),
            "ordinary_input_credits": round(self.ordinary_input_credits, 6),
            "cache_write_input_credits": round(self.cache_write_input_credits, 6),
            "cached_input_credits": round(self.cached_input_credits, 6),
            "output_credits": round(self.output_credits, 6),
            "total_credits": round(self.total_credits, 6),
            "unpriced_tokens": self.unpriced_tokens,
            "unpriced_ordinary_input_tokens": self.unpriced_ordinary_input_tokens,
            "unpriced_cached_input_tokens": self.unpriced_cached_input_tokens,
            "unpriced_cache_write_input_tokens": self.unpriced_cache_write_input_tokens,
            "unpriced_output_tokens": self.unpriced_output_tokens,
        }
