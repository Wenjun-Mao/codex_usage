from datetime import UTC, datetime

import pytest

from codex_usage.models import TokenUsage
from codex_usage.pricing import (
    ModelRate,
    credit_rate_for_model,
    estimate_codex_credits,
    estimate_cost,
    rate_for_model,
)


GPT_6_ASTRA_PRICING_AT = datetime(2026, 9, 4, tzinfo=UTC)
GPT_6_ASTRA_PRICING_BEFORE = datetime(
    2026,
    9,
    3,
    23,
    59,
    59,
    999_999,
    tzinfo=UTC,
)


def test_gpt_6_astra_rates_start_at_the_verified_boundary() -> None:
    assert rate_for_model("gpt-6-astra", at=GPT_6_ASTRA_PRICING_BEFORE) is None
    assert (
        credit_rate_for_model("gpt-6-astra", at=GPT_6_ASTRA_PRICING_BEFORE)
        is None
    )
    assert rate_for_model("gpt-6-astra", at=GPT_6_ASTRA_PRICING_AT) == ModelRate(
        input_per_1m=10.0,
        cached_input_per_1m=1.0,
        output_per_1m=50.0,
        cache_write_input_per_1m=12.5,
    )
    assert credit_rate_for_model(
        "gpt-6-astra",
        at=GPT_6_ASTRA_PRICING_AT,
    ) == ModelRate(
        input_per_1m=250.0,
        cached_input_per_1m=25.0,
        output_per_1m=1_250.0,
    )


def test_gpt_6_astra_uses_exact_model_matching() -> None:
    assert rate_for_model("GPT-6-ASTRA") == rate_for_model("gpt-6-astra")
    assert rate_for_model("gpt-6") is None
    assert rate_for_model("gpt-6-astra-fast") is None


@pytest.mark.parametrize(
    ("input_tokens", "cached_tokens", "expected"),
    (
        (272_000, 72_000, (1.5, 0.072, 0.625, 5.0, 7.197)),
        (272_001, 72_001, (3.0, 0.144002, 1.25, 7.5, 11.894002)),
    ),
)
def test_gpt_6_astra_api_cost_obeys_request_level_long_context_pricing(
    input_tokens: int,
    cached_tokens: int,
    expected: tuple[float, float, float, float, float],
) -> None:
    usage = TokenUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached_tokens,
        cache_write_input_tokens=50_000,
        output_tokens=100_000,
        total_tokens=input_tokens + 100_000,
    )

    cost = estimate_cost(usage, "gpt-6-astra", at=GPT_6_ASTRA_PRICING_AT)

    assert cost is not None
    assert cost.ordinary_input_usd == pytest.approx(expected[0])
    assert cost.cached_input_usd == pytest.approx(expected[1])
    assert cost.cache_write_input_usd == pytest.approx(expected[2])
    assert cost.output_usd == pytest.approx(expected[3])
    assert cost.total_usd == pytest.approx(expected[4])


def test_gpt_6_astra_credit_estimate_uses_standard_published_rates() -> None:
    usage = TokenUsage(
        input_tokens=272_001,
        cached_input_tokens=72_001,
        cache_write_input_tokens=50_000,
        output_tokens=100_000,
        total_tokens=372_001,
    )

    credits = estimate_codex_credits(
        usage,
        "gpt-6-astra",
        at=GPT_6_ASTRA_PRICING_AT,
    )

    assert credits is not None
    assert credits.uncached_input_credits == pytest.approx(50.0)
    assert credits.cached_input_credits == pytest.approx(1.800025)
    assert credits.output_credits == pytest.approx(125.0)
    assert credits.total_credits == pytest.approx(176.800025)


@pytest.mark.parametrize(
    ("model", "historical_rate", "current_rate"),
    (
        (
            "gpt-5.6-sol",
            ModelRate(125.0, 12.5, 750.0),
            ModelRate(100.0, 10.0, 500.0),
        ),
        (
            "gpt-5.6-terra",
            ModelRate(62.5, 6.25, 375.0),
            ModelRate(50.0, 5.0, 300.0),
        ),
        (
            "gpt-5.6-luna",
            ModelRate(25.0, 2.5, 150.0),
            ModelRate(5.0, 0.5, 30.0),
        ),
    ),
)
def test_current_gpt_5_6_credit_rates_preserve_earlier_history(
    model: str,
    historical_rate: ModelRate,
    current_rate: ModelRate,
) -> None:
    assert credit_rate_for_model(model, at=GPT_6_ASTRA_PRICING_BEFORE) == historical_rate
    assert credit_rate_for_model(model, at=GPT_6_ASTRA_PRICING_AT) == current_rate
    assert credit_rate_for_model(model) == current_rate


def test_current_gpt_5_6_alias_follows_the_sol_credit_timeline() -> None:
    assert credit_rate_for_model(
        "gpt-5.6",
        at=GPT_6_ASTRA_PRICING_BEFORE,
    ) == credit_rate_for_model("gpt-5.6-sol", at=GPT_6_ASTRA_PRICING_BEFORE)
    assert credit_rate_for_model(
        "gpt-5.6",
        at=GPT_6_ASTRA_PRICING_AT,
    ) == credit_rate_for_model("gpt-5.6-sol", at=GPT_6_ASTRA_PRICING_AT)
