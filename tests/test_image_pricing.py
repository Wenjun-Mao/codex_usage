from datetime import UTC, datetime, timedelta

from codex_usage.image_models import ImageModelFamily, ImageModelVariant, ImageUsage, NormalizedImageModel
from codex_usage.image_pricing import (
    IMAGE_PRICING_EFFECTIVE_FROM,
    ImagePricingState,
    estimate_output_only_range,
    image_rate_for_model,
    value_image_usage,
)


def _model(family: ImageModelFamily, variant: ImageModelVariant = ImageModelVariant.UNKNOWN) -> NormalizedImageModel:
    return NormalizedImageModel(family, variant, family.value, True)


def _complete_usage() -> ImageUsage:
    return ImageUsage(
        text_input_tokens=1_000_000,
        cached_text_input_tokens=1_000_000,
        text_output_tokens=1_000_000,
        image_input_tokens=1_000_000,
        cached_image_input_tokens=1_000_000,
        image_output_tokens=1_000_000,
        total_tokens=6_000_000,
    )


def test_documented_gpt_image_2_token_rates_value_complete_usage_exactly() -> None:
    valuation = value_image_usage(
        _complete_usage(),
        _model(ImageModelFamily.GPT_IMAGE_2),
        at=IMAGE_PRICING_EFFECTIVE_FROM,
    )

    assert valuation.api_usd.state is ImagePricingState.EXACT
    assert valuation.api_usd.low == 46.25
    assert valuation.api_usd.high == 46.25
    assert valuation.credits.state is ImagePricingState.EXACT
    assert valuation.credits.low == 1_406.25
    assert valuation.credits.credit_equivalent is False


def test_gpt_image_2_5_keeps_api_rate_and_marks_credit_as_equivalent_estimate() -> None:
    valuation = value_image_usage(
        _complete_usage(),
        _model(ImageModelFamily.GPT_IMAGE_2_5, ImageModelVariant.SUNBURST),
        at=IMAGE_PRICING_EFFECTIVE_FROM,
    )

    assert valuation.api_usd == valuation.api_usd.__class__(ImagePricingState.EXACT, 46.25, 46.25)
    assert valuation.credits.state is ImagePricingState.EXACT
    assert valuation.credits.credit_equivalent is True


def test_missing_independent_usage_field_is_unpriced_instead_of_assumed_zero() -> None:
    usage = ImageUsage(
        text_input_tokens=1,
        cached_text_input_tokens=0,
        image_input_tokens=0,
        cached_image_input_tokens=0,
        image_output_tokens=1,
    )

    valuation = value_image_usage(usage, _model(ImageModelFamily.GPT_IMAGE_2), at=IMAGE_PRICING_EFFECTIVE_FROM)

    assert valuation.api_usd.state is ImagePricingState.EXACT
    assert valuation.credits.state is ImagePricingState.UNPRICED


def test_evidence_conflict_prevents_unsupported_exact_valuation() -> None:
    valuation = value_image_usage(
        _complete_usage(),
        _model(ImageModelFamily.GPT_IMAGE_2),
        at=IMAGE_PRICING_EFFECTIVE_FROM,
        evidence_conflicts=True,
    )

    assert valuation.api_usd.state is ImagePricingState.UNPRICED
    assert valuation.credits.state is ImagePricingState.UNPRICED


def test_effective_date_does_not_price_an_earlier_event() -> None:
    model = _model(ImageModelFamily.GPT_IMAGE_2)

    assert image_rate_for_model(model, at=IMAGE_PRICING_EFFECTIVE_FROM - timedelta(microseconds=1)) is None
    assert image_rate_for_model(model, at=datetime(2026, 9, 12, tzinfo=UTC)) is not None


def test_output_only_range_discloses_that_inputs_are_excluded() -> None:
    result = estimate_output_only_range(
        output_count=2,
        low_output_tokens_per_image=1_000,
        high_output_tokens_per_image=3_000,
        model=_model(ImageModelFamily.GPT_IMAGE_2),
        at=IMAGE_PRICING_EFFECTIVE_FROM,
    )

    assert result.state is ImagePricingState.ESTIMATED_RANGE
    assert (result.low, result.high) == (0.06, 0.18)
    assert "text input" in result.excluded_components
    assert "reference image input" in result.excluded_components


def test_unknown_or_pre_rate_model_refuses_an_output_range() -> None:
    unknown = NormalizedImageModel(ImageModelFamily.UNKNOWN, ImageModelVariant.UNKNOWN, "gpt-image-2.6", True)
    result = estimate_output_only_range(
        output_count=1,
        low_output_tokens_per_image=1,
        high_output_tokens_per_image=2,
        model=unknown,
    )

    assert result.state is ImagePricingState.UNPRICED
