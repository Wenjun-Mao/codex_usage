from datetime import UTC, datetime

import pytest

import codex_usage.pricing as pricing
from codex_usage.models import TokenUsage
from codex_usage.pricing import (
    EffectiveModelRate,
    ModelRate,
    credit_rate_for_model,
    estimate_codex_credits,
    estimate_cost,
    rate_for_model,
)


def test_rate_matching_prefers_mini_over_parent_model() -> None:
    rate = rate_for_model("gpt-5.4-mini")

    assert rate is not None
    assert rate.output_per_1m == 4.5


def test_estimate_cost_splits_cached_and_uncached_input() -> None:
    usage = TokenUsage(input_tokens=1_000_000, cached_input_tokens=250_000, output_tokens=100_000, total_tokens=1_100_000)

    cost = estimate_cost(usage, "gpt-5.5")

    assert cost is not None
    assert cost.uncached_input_usd == 3.75
    assert cost.cached_input_usd == 0.125
    assert cost.output_usd == 3.0
    assert cost.total_usd == 6.875


def test_estimate_codex_credits_splits_cached_and_uncached_input() -> None:
    usage = TokenUsage(input_tokens=1_000_000, cached_input_tokens=250_000, output_tokens=100_000, total_tokens=1_100_000)

    credits = estimate_codex_credits(usage, "gpt-5.3-codex")

    assert credits is not None
    assert credits.uncached_input_credits == 32.8125
    assert credits.cached_input_credits == 1.09375
    assert credits.output_credits == 35.0
    assert credits.total_credits == 68.90625


def test_codex_model_has_official_api_usd_and_credit_rate() -> None:
    usage = TokenUsage(input_tokens=1_000_000, cached_input_tokens=250_000, output_tokens=100_000, total_tokens=1_100_000)

    assert rate_for_model("gpt-5.3-codex") == ModelRate(input_per_1m=1.75, cached_input_per_1m=0.175, output_per_1m=14.0)
    assert credit_rate_for_model("gpt-5.3-codex") is not None
    cost = estimate_cost(usage, "gpt-5.3-codex")
    assert cost is not None
    assert cost.total_usd == 2.75625
    assert estimate_codex_credits(usage, "gpt-5.3-codex") is not None


def test_gpt_5_3_resolves_to_same_api_rate_as_gpt_5_3_codex() -> None:
    assert rate_for_model("gpt-5.3") == rate_for_model("gpt-5.3-codex")


GPT_5_6_API_EFFECTIVE_AT = datetime(2026, 6, 26, tzinfo=UTC)
GPT_5_6_CREDIT_EFFECTIVE_AT = datetime(2026, 7, 9, tzinfo=UTC)
GPT_5_6_RATE_CASES = (
    (
        "gpt-5.6-sol",
        ModelRate(input_per_1m=5.0, cached_input_per_1m=0.5, output_per_1m=30.0),
        ModelRate(input_per_1m=125.0, cached_input_per_1m=12.5, output_per_1m=750.0),
        12.25,
        171.875,
    ),
    (
        "gpt-5.6-terra",
        ModelRate(input_per_1m=2.5, cached_input_per_1m=0.25, output_per_1m=15.0),
        ModelRate(input_per_1m=62.5, cached_input_per_1m=6.25, output_per_1m=375.0),
        6.125,
        85.9375,
    ),
    (
        "gpt-5.6-luna",
        ModelRate(input_per_1m=1.0, cached_input_per_1m=0.1, output_per_1m=6.0),
        ModelRate(input_per_1m=25.0, cached_input_per_1m=2.5, output_per_1m=150.0),
        2.45,
        34.375,
    ),
)


@pytest.mark.parametrize(
    ("model", "api_rate", "credit_rate", "expected_cost", "expected_credits"),
    GPT_5_6_RATE_CASES,
)
def test_gpt_5_6_family_has_official_rates(
    model: str,
    api_rate: ModelRate,
    credit_rate: ModelRate,
    expected_cost: float,
    expected_credits: float,
) -> None:
    usage = TokenUsage(
        input_tokens=1_000_000,
        cached_input_tokens=250_000,
        output_tokens=100_000,
        total_tokens=1_100_000,
    )

    assert rate_for_model(model, at=GPT_5_6_API_EFFECTIVE_AT) == api_rate
    assert credit_rate_for_model(model, at=GPT_5_6_CREDIT_EFFECTIVE_AT) == credit_rate

    cost = estimate_cost(usage, model, at=GPT_5_6_API_EFFECTIVE_AT)
    credits = estimate_codex_credits(usage, model, at=GPT_5_6_CREDIT_EFFECTIVE_AT)

    assert cost is not None
    assert credits is not None
    assert cost.total_usd == pytest.approx(expected_cost)
    assert credits.total_credits == pytest.approx(expected_credits)


@pytest.mark.parametrize("model", [case[0] for case in GPT_5_6_RATE_CASES])
def test_gpt_5_6_api_rates_start_on_preview_pricing_date(model: str) -> None:
    before_api = datetime(2026, 6, 25, 23, 59, 59, tzinfo=UTC)
    before_credits = datetime(2026, 7, 8, 23, 59, 59, tzinfo=UTC)

    assert rate_for_model(model, at=before_api) is None
    assert rate_for_model(model, at=GPT_5_6_API_EFFECTIVE_AT) is not None
    assert credit_rate_for_model(model, at=before_credits) is None
    assert credit_rate_for_model(model, at=GPT_5_6_CREDIT_EFFECTIVE_AT) is not None


def test_gpt_5_6_short_context_api_cost_uses_base_rate_at_threshold() -> None:
    usage = TokenUsage(
        input_tokens=272_000,
        cached_input_tokens=72_000,
        output_tokens=10_000,
        total_tokens=282_000,
    )

    cost = estimate_cost(usage, "gpt-5.6-sol", at=GPT_5_6_API_EFFECTIVE_AT)

    assert cost is not None
    assert cost.uncached_input_usd == pytest.approx(1.0)
    assert cost.cached_input_usd == pytest.approx(0.036)
    assert cost.output_usd == pytest.approx(0.3)
    assert cost.total_usd == pytest.approx(1.336)


@pytest.mark.parametrize(
    ("model", "expected_uncached", "expected_cached", "expected_output"),
    (
        ("gpt-5.6-sol", 2.0, 0.072001, 4.5),
        ("gpt-5.6-terra", 1.0, 0.0360005, 2.25),
        ("gpt-5.6-luna", 0.4, 0.0144002, 0.9),
    ),
)
def test_gpt_5_6_long_context_api_cost_uses_request_level_rates(
    model: str,
    expected_uncached: float,
    expected_cached: float,
    expected_output: float,
) -> None:
    usage = TokenUsage(
        input_tokens=272_001,
        cached_input_tokens=72_001,
        output_tokens=100_000,
        total_tokens=372_001,
    )

    cost = estimate_cost(usage, model, at=GPT_5_6_API_EFFECTIVE_AT)

    assert cost is not None
    assert cost.uncached_input_usd == pytest.approx(expected_uncached)
    assert cost.cached_input_usd == pytest.approx(expected_cached)
    assert cost.output_usd == pytest.approx(expected_output)
    assert cost.total_usd == pytest.approx(expected_uncached + expected_cached + expected_output)


def test_gpt_5_6_long_context_does_not_change_codex_credit_rates() -> None:
    usage = TokenUsage(
        input_tokens=272_001,
        cached_input_tokens=72_001,
        output_tokens=100_000,
        total_tokens=372_001,
    )

    credits = estimate_codex_credits(usage, "gpt-5.6-sol", at=GPT_5_6_CREDIT_EFFECTIVE_AT)

    assert credits is not None
    assert credits.uncached_input_credits == pytest.approx(25.0)
    assert credits.cached_input_credits == pytest.approx(0.9000125)
    assert credits.output_credits == pytest.approx(75.0)
    assert credits.total_credits == pytest.approx(100.9000125)


def test_gpt_5_6_alias_resolves_to_sol_api_and_credit_rates() -> None:
    assert rate_for_model("gpt-5.6", at=GPT_5_6_API_EFFECTIVE_AT) == rate_for_model(
        "gpt-5.6-sol",
        at=GPT_5_6_API_EFFECTIVE_AT,
    )
    assert credit_rate_for_model("gpt-5.6", at=GPT_5_6_CREDIT_EFFECTIVE_AT) == credit_rate_for_model(
        "gpt-5.6-sol",
        at=GPT_5_6_CREDIT_EFFECTIVE_AT,
    )


def test_pricing_table_date_covers_gpt_5_6_general_availability() -> None:
    assert pricing.PRICING_AS_OF == "2026-07-09"


def test_rate_lookup_requires_exact_model_or_explicit_alias(monkeypatch) -> None:
    base_rate = ModelRate(input_per_1m=1.0, cached_input_per_1m=0.1, output_per_1m=2.0)
    schedule = (
        EffectiveModelRate(
            model_key="gpt-5.6",
            effective_from=datetime(1970, 1, 1, tzinfo=UTC),
            rate=base_rate,
            aliases=("gpt-5.6-2026-08-18",),
        ),
    )
    monkeypatch.setattr(pricing, "API_PRICING_USD_SCHEDULE", schedule)

    assert rate_for_model("gpt-5.6") == base_rate
    assert rate_for_model("GPT-5.6") == base_rate
    assert rate_for_model("gpt-5.6-2026-08-18") == base_rate
    assert rate_for_model("gpt-5.6-pro") is None
    assert rate_for_model("gpt-5.6-mini") is None
    assert rate_for_model("wrapper-gpt-5.6") is None


def test_effective_dated_rate_lookup_uses_latest_rate_when_at_is_omitted(monkeypatch) -> None:
    monkeypatch.setattr(
        pricing,
        "API_PRICING_USD_SCHEDULE",
        (
            EffectiveModelRate(
                model_key="example-model",
                effective_from=datetime(1970, 1, 1, tzinfo=UTC),
                rate=ModelRate(input_per_1m=1.0, cached_input_per_1m=0.1, output_per_1m=10.0),
            ),
            EffectiveModelRate(
                model_key="example-model",
                effective_from=datetime(2026, 8, 18, tzinfo=UTC),
                rate=ModelRate(input_per_1m=2.0, cached_input_per_1m=0.2, output_per_1m=20.0),
            ),
        ),
    )

    assert rate_for_model("example-model").input_per_1m == 2.0


def test_effective_dated_rate_lookup_uses_record_timestamp(monkeypatch) -> None:
    monkeypatch.setattr(
        pricing,
        "API_PRICING_USD_SCHEDULE",
        (
            EffectiveModelRate(
                model_key="example-model",
                effective_from=datetime(1970, 1, 1, tzinfo=UTC),
                rate=ModelRate(input_per_1m=1.0, cached_input_per_1m=0.1, output_per_1m=10.0),
            ),
            EffectiveModelRate(
                model_key="example-model",
                effective_from=datetime(2026, 8, 18, tzinfo=UTC),
                rate=ModelRate(input_per_1m=2.0, cached_input_per_1m=0.2, output_per_1m=20.0),
            ),
        ),
    )

    before = rate_for_model("example-model", at=datetime(2026, 8, 17, 23, 59, 59, tzinfo=UTC))
    after = rate_for_model("example-model", at=datetime(2026, 8, 18, tzinfo=UTC))

    assert before is not None
    assert before.input_per_1m == 1.0
    assert after is not None
    assert after.input_per_1m == 2.0


@pytest.mark.parametrize(
    "model",
    ("gpt-5.6-pro", "gpt-5.6-mini", "wrapper-gpt-5.6-sol", "wrapper-gpt-5.6"),
)
def test_unpublished_gpt_5_6_variants_remain_unpriced(model: str) -> None:
    usage = TokenUsage(input_tokens=1_000, cached_input_tokens=100, output_tokens=50, total_tokens=1_050)
    at = datetime(2026, 7, 9, tzinfo=UTC)

    assert rate_for_model(model, at=at) is None
    assert credit_rate_for_model(model, at=at) is None
    assert estimate_cost(usage, model, at=at) is None
    assert estimate_codex_credits(usage, model, at=at) is None


def test_unknown_model_has_no_api_or_credit_rate() -> None:
    usage = TokenUsage(input_tokens=10, total_tokens=10)

    assert rate_for_model("unknown-model") is None
    assert credit_rate_for_model("unknown-model") is None
    assert estimate_cost(usage, "unknown-model") is None
    assert estimate_codex_credits(usage, "unknown-model") is None
