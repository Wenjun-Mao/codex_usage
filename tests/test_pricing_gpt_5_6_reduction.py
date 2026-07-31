from datetime import UTC, datetime

import pytest

import codex_usage.pricing as pricing
from codex_usage.models import TokenUsage
from codex_usage.pricing import (
    ModelRate,
    credit_rate_for_model,
    estimate_cost,
    rate_for_model,
)


GPT_5_6_TERRA_LUNA_API_REDUCTION_AT = datetime(2026, 7, 31, tzinfo=UTC)
GPT_5_6_TERRA_LUNA_API_REDUCTION_BEFORE = datetime(
    2026,
    7,
    30,
    23,
    59,
    59,
    999_999,
    tzinfo=UTC,
)

GPT_5_6_TERRA_LUNA_REDUCTION_CASES = (
    (
        "gpt-5.6-terra",
        ModelRate(
            input_per_1m=2.5,
            cached_input_per_1m=0.25,
            output_per_1m=15.0,
            cache_write_input_per_1m=3.125,
        ),
        ModelRate(
            input_per_1m=2.0,
            cached_input_per_1m=0.2,
            output_per_1m=12.0,
            cache_write_input_per_1m=2.5,
        ),
    ),
    (
        "gpt-5.6-luna",
        ModelRate(
            input_per_1m=1.0,
            cached_input_per_1m=0.1,
            output_per_1m=6.0,
            cache_write_input_per_1m=1.25,
        ),
        ModelRate(
            input_per_1m=0.2,
            cached_input_per_1m=0.02,
            output_per_1m=1.2,
            cache_write_input_per_1m=0.25,
        ),
    ),
)


@pytest.mark.parametrize(
    ("model", "original_rate", "reduced_rate"),
    GPT_5_6_TERRA_LUNA_REDUCTION_CASES,
)
def test_terra_and_luna_api_reduction_uses_exact_effective_boundary(
    model: str,
    original_rate: ModelRate,
    reduced_rate: ModelRate,
) -> None:
    assert (
        rate_for_model(model, at=GPT_5_6_TERRA_LUNA_API_REDUCTION_BEFORE)
        == original_rate
    )
    assert (
        rate_for_model(model, at=GPT_5_6_TERRA_LUNA_API_REDUCTION_AT)
        == reduced_rate
    )
    assert rate_for_model(model) == reduced_rate


def test_terra_and_luna_reduction_does_not_change_sol_or_codex_credit_rates() -> None:
    assert rate_for_model(
        "gpt-5.6-sol",
        at=GPT_5_6_TERRA_LUNA_API_REDUCTION_AT,
    ) == ModelRate(
        input_per_1m=5.0,
        cached_input_per_1m=0.5,
        output_per_1m=30.0,
        cache_write_input_per_1m=6.25,
    )
    assert credit_rate_for_model(
        "gpt-5.6-terra",
        at=GPT_5_6_TERRA_LUNA_API_REDUCTION_AT,
    ) == ModelRate(
        input_per_1m=62.5,
        cached_input_per_1m=6.25,
        output_per_1m=375.0,
    )
    assert credit_rate_for_model(
        "gpt-5.6-luna",
        at=GPT_5_6_TERRA_LUNA_API_REDUCTION_AT,
    ) == ModelRate(
        input_per_1m=25.0,
        cached_input_per_1m=2.5,
        output_per_1m=150.0,
    )


@pytest.mark.parametrize(
    (
        "model",
        "expected_ordinary",
        "expected_cached",
        "expected_cache_write",
        "expected_output",
        "expected_total",
    ),
    (
        ("gpt-5.6-terra", 0.3, 0.0144, 0.125, 1.2, 1.6394),
        ("gpt-5.6-luna", 0.03, 0.00144, 0.0125, 0.12, 0.16394),
    ),
)
def test_terra_and_luna_reduced_short_context_costs(
    model: str,
    expected_ordinary: float,
    expected_cached: float,
    expected_cache_write: float,
    expected_output: float,
    expected_total: float,
) -> None:
    usage = TokenUsage(
        input_tokens=272_000,
        cached_input_tokens=72_000,
        cache_write_input_tokens=50_000,
        output_tokens=100_000,
        total_tokens=372_000,
    )

    cost = estimate_cost(
        usage,
        model,
        at=GPT_5_6_TERRA_LUNA_API_REDUCTION_AT,
    )

    assert cost is not None
    assert cost.ordinary_input_usd == pytest.approx(expected_ordinary)
    assert cost.cached_input_usd == pytest.approx(expected_cached)
    assert cost.cache_write_input_usd == pytest.approx(expected_cache_write)
    assert cost.output_usd == pytest.approx(expected_output)
    assert cost.total_usd == pytest.approx(expected_total)


@pytest.mark.parametrize(
    (
        "model",
        "expected_ordinary",
        "expected_cached",
        "expected_cache_write",
        "expected_output",
        "expected_total",
    ),
    (
        ("gpt-5.6-terra", 0.6, 0.0288004, 0.25, 1.8, 2.6788004),
        ("gpt-5.6-luna", 0.06, 0.00288004, 0.025, 0.18, 0.26788004),
    ),
)
def test_terra_and_luna_reduced_long_context_costs(
    model: str,
    expected_ordinary: float,
    expected_cached: float,
    expected_cache_write: float,
    expected_output: float,
    expected_total: float,
) -> None:
    usage = TokenUsage(
        input_tokens=272_001,
        cached_input_tokens=72_001,
        cache_write_input_tokens=50_000,
        output_tokens=100_000,
        total_tokens=372_001,
    )

    cost = estimate_cost(
        usage,
        model,
        at=GPT_5_6_TERRA_LUNA_API_REDUCTION_AT,
    )

    assert cost is not None
    assert cost.ordinary_input_usd == pytest.approx(expected_ordinary)
    assert cost.cached_input_usd == pytest.approx(expected_cached)
    assert cost.cache_write_input_usd == pytest.approx(expected_cache_write)
    assert cost.output_usd == pytest.approx(expected_output)
    assert cost.total_usd == pytest.approx(expected_total)


def test_pricing_table_date_covers_terra_and_luna_reduction() -> None:
    assert pricing.PRICING_AS_OF == "2026-07-31"
