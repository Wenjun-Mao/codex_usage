from codex_usage.models import TokenUsage
from codex_usage.pricing import estimate_cost, rate_for_model


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
