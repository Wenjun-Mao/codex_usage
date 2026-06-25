from datetime import UTC, datetime

import codex_usage.pricing as pricing
from codex_usage.models import TokenUsage
from codex_usage.pricing import EffectiveModelRate, ModelRate, credit_rate_for_model, estimate_codex_credits, estimate_cost, rate_for_model


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


def test_future_model_without_checked_in_rate_is_unpriced() -> None:
    usage = TokenUsage(input_tokens=1_000, cached_input_tokens=100, output_tokens=50, total_tokens=1_050)

    assert rate_for_model("gpt-5.6") is None
    assert credit_rate_for_model("gpt-5.6") is None
    assert estimate_cost(usage, "gpt-5.6") is None
    assert estimate_codex_credits(usage, "gpt-5.6") is None


def test_unknown_model_has_no_api_or_credit_rate() -> None:
    usage = TokenUsage(input_tokens=10, total_tokens=10)

    assert rate_for_model("unknown-model") is None
    assert credit_rate_for_model("unknown-model") is None
    assert estimate_cost(usage, "unknown-model") is None
    assert estimate_codex_credits(usage, "unknown-model") is None
