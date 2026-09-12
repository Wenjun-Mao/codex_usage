"""Effective-dated, independently aggregated image valuation contracts."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import cache

from codex_usage.image_models import (
    ImageModelFamily,
    ImageModelVariant,
    ImageUsage,
    NormalizedImageModel,
)


IMAGE_PRICING_AS_OF = "2026-09-12"
IMAGE_PRICING_REVISION = "gpt-image-2-and-2.5-v1"
IMAGE_PRICING_EFFECTIVE_FROM = datetime(2026, 9, 12, tzinfo=UTC)


class ImagePricingState(StrEnum):
    EXACT = "exact"
    ESTIMATED_RANGE = "estimated_range"
    UNPRICED = "unpriced"


@dataclass(frozen=True, slots=True)
class ImageApiRate:
    text_input_per_1m: float
    cached_text_input_per_1m: float
    image_input_per_1m: float
    cached_image_input_per_1m: float
    image_output_per_1m: float


@dataclass(frozen=True, slots=True)
class ImageCreditRate:
    text_input_per_1m: float
    cached_text_input_per_1m: float
    text_output_per_1m: float
    image_input_per_1m: float
    cached_image_input_per_1m: float
    image_output_per_1m: float
    equivalent_estimate: bool = False


@dataclass(frozen=True, slots=True)
class ImageOutputEstimator:
    """A documented output bound for one image family/variant contract.

    Estimators carry their applicability rather than accepting naked token
    bounds, preventing a calculator contract for one family from leaking into
    another merely because the API rates currently match.
    """

    family: ImageModelFamily
    variants: frozenset[ImageModelVariant]
    low_output_tokens_per_image: int
    high_output_tokens_per_image: int

    def __post_init__(self) -> None:
        if (
            not self.variants
            or self.low_output_tokens_per_image < 0
            or self.high_output_tokens_per_image < self.low_output_tokens_per_image
        ):
            raise ValueError("invalid image output estimator")

    def supports(self, model: NormalizedImageModel) -> bool:
        return model.family is self.family and model.variant in self.variants


@dataclass(frozen=True, slots=True)
class EffectiveImageRate:
    family: ImageModelFamily
    effective_from: datetime
    api_rate: ImageApiRate
    credit_rate: ImageCreditRate | None = None


@dataclass(frozen=True, slots=True)
class ImageMoneyRange:
    state: ImagePricingState
    low: float | None = None
    high: float | None = None
    excluded_components: tuple[str, ...] = ()
    credit_equivalent: bool = False

    def __post_init__(self) -> None:
        if self.state is ImagePricingState.UNPRICED and (self.low is not None or self.high is not None):
            raise ValueError("unpriced image valuation cannot carry amounts")
        if self.state is not ImagePricingState.UNPRICED and (self.low is None or self.high is None):
            raise ValueError("priced image valuation requires both range bounds")
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError("image valuation low bound exceeds high bound")


@dataclass(frozen=True, slots=True)
class ImageValuation:
    api_usd: ImageMoneyRange
    credits: ImageMoneyRange


_DOCUMENTED_API_RATE = ImageApiRate(5.0, 1.25, 8.0, 2.0, 30.0)
_GPT_IMAGE_2_CREDITS = ImageCreditRate(125.0, 31.25, 250.0, 200.0, 50.0, 750.0)
_GPT_IMAGE_2_5_CREDITS = ImageCreditRate(125.0, 31.25, 250.0, 200.0, 50.0, 750.0, equivalent_estimate=True)

IMAGE_PRICING_SCHEDULE: tuple[EffectiveImageRate, ...] = (
    EffectiveImageRate(
        ImageModelFamily.GPT_IMAGE_2,
        IMAGE_PRICING_EFFECTIVE_FROM,
        _DOCUMENTED_API_RATE,
        _GPT_IMAGE_2_CREDITS,
    ),
    EffectiveImageRate(
        ImageModelFamily.GPT_IMAGE_2_5,
        IMAGE_PRICING_EFFECTIVE_FROM,
        _DOCUMENTED_API_RATE,
        _GPT_IMAGE_2_5_CREDITS,
    ),
)


def image_rate_for_model(
    model: NormalizedImageModel,
    *,
    at: datetime | None = None,
) -> EffectiveImageRate | None:
    if model.pricing_key is None:
        return None
    entries = _compiled_schedule(IMAGE_PRICING_SCHEDULE).get(model.family, ())
    if not entries:
        return None
    if at is None:
        return entries[-1]
    effective_at = _normalize_at(at)
    starts = tuple(entry.effective_from for entry in entries)
    index = bisect_right(starts, effective_at) - 1
    return None if index < 0 else entries[index]


def value_image_usage(
    usage: ImageUsage,
    model: NormalizedImageModel,
    *,
    at: datetime | None = None,
    evidence_conflicts: bool = False,
) -> ImageValuation:
    """Value complete upstream usage only; absent fields never become zeros."""
    rate = image_rate_for_model(model, at=at)
    if rate is None or evidence_conflicts:
        return ImageValuation(_unpriced(), _unpriced())

    api = _value_api_usage(usage, rate.api_rate)
    credits = _value_credit_usage(usage, rate.credit_rate)
    return ImageValuation(api, credits)


def estimate_output_only_range(
    *,
    output_count: int,
    estimator: ImageOutputEstimator,
    model: NormalizedImageModel,
    at: datetime | None = None,
) -> ImageMoneyRange:
    """Create a documented output-only range without pretending inputs are free.

    Callers must supply a model- and variant-specific estimator.  This intentionally has no
    cross-family fallback: GPT Image 2 calculator numbers cannot price GPT Image
    2.5 activity.
    """
    if output_count < 0:
        raise ValueError("invalid image output range")
    if not estimator.supports(model):
        return _unpriced()
    rate = image_rate_for_model(model, at=at)
    if rate is None:
        return _unpriced()
    low = (
        output_count
        * estimator.low_output_tokens_per_image
        / 1_000_000
        * rate.api_rate.image_output_per_1m
    )
    high = (
        output_count
        * estimator.high_output_tokens_per_image
        / 1_000_000
        * rate.api_rate.image_output_per_1m
    )
    return ImageMoneyRange(
        state=ImagePricingState.ESTIMATED_RANGE,
        low=low,
        high=high,
        excluded_components=("text input", "cached text input", "reference image input", "cached reference image input"),
    )


def _value_api_usage(usage: ImageUsage, rate: ImageApiRate) -> ImageMoneyRange:
    if not usage.has_complete_api_usage:
        return _unpriced()
    amount = (
        usage.text_input_tokens / 1_000_000 * rate.text_input_per_1m
        + usage.cached_text_input_tokens / 1_000_000 * rate.cached_text_input_per_1m
        + usage.image_input_tokens / 1_000_000 * rate.image_input_per_1m
        + usage.cached_image_input_tokens / 1_000_000 * rate.cached_image_input_per_1m
        + usage.image_output_tokens / 1_000_000 * rate.image_output_per_1m
    )
    return ImageMoneyRange(ImagePricingState.EXACT, amount, amount)


def _value_credit_usage(usage: ImageUsage, rate: ImageCreditRate | None) -> ImageMoneyRange:
    if rate is None or not usage.has_complete_credit_usage:
        return _unpriced()
    amount = (
        usage.text_input_tokens / 1_000_000 * rate.text_input_per_1m
        + usage.cached_text_input_tokens / 1_000_000 * rate.cached_text_input_per_1m
        + usage.text_output_tokens / 1_000_000 * rate.text_output_per_1m
        + usage.image_input_tokens / 1_000_000 * rate.image_input_per_1m
        + usage.cached_image_input_tokens / 1_000_000 * rate.cached_image_input_per_1m
        + usage.image_output_tokens / 1_000_000 * rate.image_output_per_1m
    )
    return ImageMoneyRange(
        (
            ImagePricingState.ESTIMATED_RANGE
            if rate.equivalent_estimate
            else ImagePricingState.EXACT
        ),
        amount,
        amount,
        credit_equivalent=rate.equivalent_estimate,
    )


def _unpriced() -> ImageMoneyRange:
    return ImageMoneyRange(ImagePricingState.UNPRICED)


@cache
def _compiled_schedule(
    schedule: tuple[EffectiveImageRate, ...],
) -> dict[ImageModelFamily, tuple[EffectiveImageRate, ...]]:
    indexed: dict[ImageModelFamily, list[EffectiveImageRate]] = {}
    for entry in schedule:
        indexed.setdefault(entry.family, []).append(entry)
    return {
        family: tuple(sorted(entries, key=lambda entry: entry.effective_from))
        for family, entries in indexed.items()
    }


def _normalize_at(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
